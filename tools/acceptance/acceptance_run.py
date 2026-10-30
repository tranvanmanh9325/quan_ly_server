#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance/acceptance_run.py — CLI Acceptance Test Runner.
Milestone M0: Frozen Acceptance Judge Infrastructure.

Usage:
  python tools/acceptance/acceptance_run.py --suite public|sabotage|all --out <dir>
  python tools/acceptance/acceptance_run.py --input <vid> --output-video <clean_vid> --out <dir>

Outputs:
  - <out>/summary.json
  - <out>/per_frame_metrics.csv
  - <out>/sabotage_summary.json (when running sabotage suite)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

# Ensure parent path is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.acceptance.metrics import (
        StreamingMetricsAccumulator,
        evaluate_c1_residual_text,
        evaluate_c5_negatives,
        evaluate_c7_av_integrity,
        evaluate_c8_resource_limits,
    )
    from tools.acceptance.sabotage_suite import SabotageSuiteRunner
    from tools.acceptance.synthetic_generator import P_CASES, SyntheticBenchmarkGenerator
except ImportError:
    from metrics import (
        StreamingMetricsAccumulator,
        evaluate_c1_residual_text,
        evaluate_c5_negatives,
        evaluate_c7_av_integrity,
        evaluate_c8_resource_limits,
    )
    from sabotage_suite import SabotageSuiteRunner
    from synthetic_generator import P_CASES, SyntheticBenchmarkGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("acceptance_run")


def run_video_evaluation(
    pred_video_path: Path,
    out_dir: Path,
    case_id: Optional[str] = None,
    clean_gt_path: Optional[Path] = None,
    mask_dir: Optional[Path] = None,
    baseline_video_path: Optional[Path] = None,
    category: str = "R",
    target_scope: str = "overlay",
    is_scene_text: bool = False,
    scene_mask_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluates a single video through streaming frame-by-frame measurement."""
    cap_pred = cv2.VideoCapture(str(pred_video_path))
    if not cap_pred.isOpened():
        raise RuntimeError(f"Cannot open video: {pred_video_path}")

    fps = float(cap_pred.get(cv2.CAP_PROP_FPS))
    total_frames = int(cap_pred.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap_pred.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap_pred.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cap_gt = cv2.VideoCapture(str(clean_gt_path)) if clean_gt_path and clean_gt_path.exists() else None
    cap_base = cv2.VideoCapture(str(baseline_video_path)) if baseline_video_path and baseline_video_path.exists() else None

    accumulator = StreamingMetricsAccumulator(worst_k=5)
    f_idx = 0

    while True:
        ret_p, f_pred = cap_pred.read()
        if not ret_p:
            break

        f_gt = None
        if cap_gt:
            ret_g, f_gt = cap_gt.read()

        f_base = None
        if cap_base:
            ret_b, f_base = cap_base.read()

        # Load mask if available
        mask = None
        if mask_dir and mask_dir.exists():
            mask_file = mask_dir / f"frame_{f_idx:04d}.png"
            if mask_file.exists():
                mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)

        # Load scene_text_mask if available
        st_mask = None
        if scene_mask_dir and scene_mask_dir.exists():
            st_mask_file = scene_mask_dir / f"frame_{f_idx:04d}.png"
            if st_mask_file.exists():
                st_mask = cv2.imread(str(st_mask_file), cv2.IMREAD_GRAYSCALE)

        accumulator.process_frame(
            frame_idx=f_idx,
            fps=fps,
            pred_frame=f_pred,
            clean_gt=f_gt,
            inpaint_mask=mask,
            baseline_frame=f_base,
            category=category,
            target_scope=target_scope,
            is_scene_text=is_scene_text,
            scene_text_mask=st_mask,
        )
        f_idx += 1

    cap_pred.release()
    if cap_gt:
        cap_gt.release()
    if cap_base:
        cap_base.release()

    # Export per-frame CSV with unique case_id prefix if available
    if case_id:
        csv_filename = f"per_frame_metrics_{case_id}_{pred_video_path.stem}.csv"
    else:
        csv_filename = f"per_frame_metrics_{pred_video_path.stem}.csv"
    csv_path = out_dir / csv_filename
    accumulator.export_csv(csv_path)

    summary = accumulator.compute_summary()
    summary["video_path"] = str(pred_video_path)
    summary["resolution"] = [width, height]
    summary["fps"] = fps
    summary["category"] = category
    summary["csv_path"] = str(csv_path)

    # Audio integrity if reference provided
    if clean_gt_path and clean_gt_path.exists():
        av_res = evaluate_c7_av_integrity(clean_gt_path, pred_video_path)
        summary["av_integrity"] = av_res
        if not av_res["is_pass"]:
            summary["is_pass"] = False

    return summary


def run_public_suite(out_dir: Path, seed: int = 42) -> Dict[str, Any]:
    """Runs acceptance evaluation against the 10 frozen public synthetic cases P1-P10."""
    logger.info("Initializing synthetic public cases P1-P10...")
    bench_dir = out_dir / "synthetic_benchmarks"
    gen = SyntheticBenchmarkGenerator(bench_dir, seed=seed)
    gen.generate_all()

    case_results: Dict[str, Any] = {}
    all_pass = True

    for cid, cfg in P_CASES.items():
        case_dir = bench_dir / cid
        clean_mp4 = case_dir / "clean.mp4"
        text_mp4 = case_dir / "text.mp4"
        mask_dir = case_dir / "mask_ground_truth"
        scene_mask_dir = case_dir / "scene_text_mask"

        logger.info(f"Evaluating case {cid} ({cfg['category']}: {cfg['description']})...")

        # For baseline verification test, evaluate clean_mp4 as ideal output
        res = run_video_evaluation(
            pred_video_path=clean_mp4,
            out_dir=out_dir,
            case_id=cid,
            clean_gt_path=clean_mp4,
            mask_dir=mask_dir,
            baseline_video_path=clean_mp4,
            category=cfg["category"],
            target_scope="overlay",
            is_scene_text=(cfg["category"] == "SceneText"),
            scene_mask_dir=scene_mask_dir if scene_mask_dir.exists() else None,
        )
        case_results[cid] = res
        if not res["is_pass"]:
            all_pass = False

    c8_res = evaluate_c8_resource_limits()

    overall_summary = {
        "suite": "public_synthetic_p1_p10",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": len(case_results),
        "passed_cases": sum(1 for r in case_results.values() if r["is_pass"]),
        "all_cases_passed": all_pass,
        "resource_limits": c8_res,
        "case_results": case_results,
        "is_pass": (all_pass and c8_res["is_pass"]),
    }

    summary_file = out_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(overall_summary, f, indent=2)

    return overall_summary


def main():
    parser = argparse.ArgumentParser(description="Acceptance Test Runner for Video Text Removal")
    parser.add_argument("--suite", choices=["public", "sabotage", "all"], default="public", help="Evaluation suite to execute")
    parser.add_argument("--out", default="acceptance_out", help="Directory to save report artifacts")
    parser.add_argument("--input", default=None, help="Input video to evaluate")
    parser.add_argument("--output-video", default=None, help="Processed output video to evaluate")
    parser.add_argument("--clean-gt", default=None, help="Ground truth clean video")
    parser.add_argument("--mask-dir", default=None, help="Ground truth mask directory")
    parser.add_argument("--baseline", default=None, help="Baseline plain re-encode video")
    parser.add_argument("--scope", default="overlay", choices=["overlay", "all"], help="Target scope mode")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0

    if args.output_video:
        # Direct evaluation of a specific video
        pred_p = Path(args.output_video)
        gt_p = Path(args.clean_gt) if args.clean_gt else None
        mask_p = Path(args.mask_dir) if args.mask_dir else None
        base_p = Path(args.baseline) if args.baseline else None

        logger.info(f"Direct video evaluation on {pred_p}")
        res = run_video_evaluation(
            pred_video_path=pred_p,
            out_dir=out_dir,
            clean_gt_path=gt_p,
            mask_dir=mask_p,
            baseline_video_path=base_p,
            target_scope=args.scope,
        )
        with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["is_pass"] else 1)

    if args.suite in ["sabotage", "all"]:
        logger.info("Executing Sabotage Suite (10 attacks a-j + 2 Ground Truth checks)...")
        sab_runner = SabotageSuiteRunner(out_dir / "sabotage")
        sab_res = sab_runner.run_all()
        with open(out_dir / "sabotage_summary.json", "w", encoding="utf-8") as f:
            json.dump(sab_res, f, indent=2)

        print("\n" + "=" * 70)
        print("SABOTAGE SUITE VERIFICATION:")
        print("=" * 70)
        for a in sab_res["attacks"]:
            status = "[CAUGHT FAIL]" if a["caught_by_judge"] else "[MISSED PASS]"
            print(f"  {a['attack']:<45} -> {status}")
        for g in sab_res["ground_truths"]:
            status = "[VERIFIED PASS]" if g["is_pass"] else "[UNEXPECTED FAIL]"
            print(f"  {g['test']:<45} -> {status}")
        print(f"Sabotage Suite Pass: {sab_res['overall_suite_pass']}")
        print("=" * 70 + "\n")

        if not sab_res["overall_suite_pass"]:
            exit_code = 1

    if args.suite in ["public", "all"]:
        logger.info("Executing Public Synthetic Suite (P1-P10)...")
        pub_res = run_public_suite(out_dir, seed=args.seed)
        print("\n" + "=" * 70)
        print("PUBLIC SUITE VERIFICATION:")
        print("=" * 70)
        print(f"Total Cases: {pub_res['total_cases']}, Passed: {pub_res['passed_cases']}")
        print(f"All Cases Passed: {pub_res['all_cases_passed']}")
        print(f"Overall Suite Pass: {pub_res['is_pass']}")
        print("=" * 70 + "\n")

        if not pub_res["is_pass"]:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
