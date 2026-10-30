#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance/acceptance_run.py — CLI Acceptance Test Runner.
Milestone M0 / M6: Frozen Acceptance Judge Infrastructure.

Usage:
  python tools/acceptance/acceptance_run.py --suite public|sabotage|all --out <dir>
  python tools/acceptance_run.py --suite public --out <dir>
  python tools/acceptance_run.py --input <vid> --output-video <clean_vid> --out <dir>

Outputs:
  - <out>/summary.json
  - <out>/verdict.json
  - <out>/per_frame_metrics_*.csv
  - <out>/sabotage_summary.json (when running sabotage suite)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

# Ensure repository root and services are in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

agent_service_dir = REPO_ROOT / "services" / "ai-agent-service"
if str(agent_service_dir) not in sys.path:
    sys.path.insert(0, str(agent_service_dir))

try:
    from tools.acceptance.metrics import (
        StreamingMetricsAccumulator,
        compute_ssim,
        evaluate_c1_residual_text,
        evaluate_c5_negatives,
        evaluate_c7_av_integrity,
        evaluate_c8_resource_limits,
    )
    from tools.acceptance.phrase_lists import evaluate_scope_parser
    from tools.acceptance.sabotage_suite import SabotageSuiteRunner
    from tools.acceptance.synthetic_generator import P_CASES, SyntheticBenchmarkGenerator
except ImportError:
    from metrics import (
        StreamingMetricsAccumulator,
        compute_ssim,
        evaluate_c1_residual_text,
        evaluate_c5_negatives,
        evaluate_c7_av_integrity,
        evaluate_c8_resource_limits,
    )
    from phrase_lists import evaluate_scope_parser
    from sabotage_suite import SabotageSuiteRunner
    from synthetic_generator import P_CASES, SyntheticBenchmarkGenerator

try:
    from app.services.scope_parser import NegationAwareScopeParser
    from app.services.video_editor_service import VideoEditorService
except ImportError:
    try:
        from services.ai_agent_service.app.services.scope_parser import NegationAwareScopeParser
        from services.ai_agent_service.app.services.video_editor_service import VideoEditorService
    except ImportError:
        NegationAwareScopeParser = None
        VideoEditorService = None

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

    # Audio integrity if reference provided (clean GT or baseline video)
    ref_audio = clean_gt_path if (clean_gt_path and clean_gt_path.exists()) else baseline_video_path
    if ref_audio and ref_audio.exists():
        av_res = evaluate_c7_av_integrity(ref_audio, pred_video_path)
        summary["av_integrity"] = av_res
        if not av_res["is_pass"]:
            summary["is_pass"] = False

    return summary


def evaluate_real_clip_section_5_5(
    clean_video_path: Path,
    original_video_path: Path,
    band_y_min: int = 800,
    band_y_max: int = 1000,
) -> Dict[str, Any]:
    """
    Section 5.5 Real Clip Evaluation (tmpy8evxmno.mp4):
    - Scene text delta SSIM <= 0.02
    - Text-free band y in [800, 1000] mean PSNR >= 40.0 dB
    """
    cap_clean = cv2.VideoCapture(str(clean_video_path))
    cap_orig = cv2.VideoCapture(str(original_video_path))

    band_psnrs = []
    band_ssims = []

    while True:
        ret_c, f_clean = cap_clean.read()
        ret_o, f_orig = cap_orig.read()
        if not ret_c or not ret_o:
            break

        h, w = f_clean.shape[:2]
        y1 = min(band_y_min, h - 1)
        y2 = min(band_y_max, h)
        if y2 > y1:
            band_clean = f_clean[y1:y2, :]
            band_orig = f_orig[y1:y2, :]

            diff = band_clean.astype(np.float64) - band_orig.astype(np.float64)
            mse = np.mean(diff ** 2)
            psnr_val = 100.0 if mse < 1e-10 else float(10.0 * np.log10((255.0 ** 2) / mse))
            band_psnrs.append(psnr_val)

            ssim_val = compute_ssim(band_clean, band_orig)
            band_ssims.append(ssim_val)

    cap_clean.release()
    cap_orig.release()

    mean_band_psnr = float(np.mean(band_psnrs)) if band_psnrs else 100.0
    mean_band_ssim = float(np.mean(band_ssims)) if band_ssims else 1.0
    delta_ssim = max(0.0, 1.0 - mean_band_ssim)

    psnr_pass = bool(mean_band_psnr >= 40.0)
    delta_ssim_pass = bool(delta_ssim <= 0.02)

    return {
        "text_free_band_y_range": [band_y_min, band_y_max],
        "mean_band_psnr_db": round(mean_band_psnr, 2),
        "mean_band_ssim": round(mean_band_ssim, 4),
        "delta_ssim": round(delta_ssim, 4),
        "psnr_pass": psnr_pass,
        "delta_ssim_pass": delta_ssim_pass,
        "is_pass": psnr_pass and delta_ssim_pass,
    }


def run_public_suite(out_dir: Path, seed: int = 42, enable_real_clip: bool = True) -> Dict[str, Any]:
    """
    Runs full acceptance evaluation:
    1. Scope Parser Intent Verification (>= 40 phrases, 100% required)
    2. Synthetic Public Suite (P1-P10) through genuine VideoEditorService production pipeline
    3. Negative Controls & Scene Text dual-mode verification (P7 & P8)
    4. Real Clip (test/tmpy8evxmno.mp4) Section 5.5 evaluation
    5. C8 Resource limits & process cleanliness
    """
    logger.info("Initializing Scope Parser intent testing on frozen phrase list...")
    if NegationAwareScopeParser is None:
        raise RuntimeError("NegationAwareScopeParser could not be imported from app.services.scope_parser")
    if VideoEditorService is None:
        raise RuntimeError("VideoEditorService could not be imported from app.services.video_editor_service")

    scope_eval_result = evaluate_scope_parser(lambda s: NegationAwareScopeParser.parse_deterministic(s).target_scope)
    logger.info(
        f"Scope Parser accuracy: {scope_eval_result['accuracy_percent']}% "
        f"({scope_eval_result['passed']}/{scope_eval_result['total_phrases']} phrases passed)"
    )
    if not scope_eval_result["is_100_percent"]:
        logger.error(f"Scope Parser FAILED: {scope_eval_result['failures']}")

    logger.info("Initializing synthetic public cases P1-P10...")
    bench_dir = out_dir / "synthetic_benchmarks"
    gen = SyntheticBenchmarkGenerator(bench_dir, seed=seed)
    gen.generate_all()

    editor_service = VideoEditorService()
    case_results: Dict[str, Any] = {}
    all_pass = scope_eval_result["is_100_percent"]

    for cid, cfg in P_CASES.items():
        case_dir = bench_dir / cid
        clean_mp4 = case_dir / "clean.mp4"
        text_mp4 = case_dir / "text.mp4"
        mask_dir = case_dir / "mask_ground_truth"
        scene_mask_dir = case_dir / "scene_text_mask"

        logger.info(f"Processing and evaluating case {cid} ({cfg['category']}: {cfg['description']})...")

        if cid == "P8":
            # Dual-mode verification for Scene Text:
            # Mode A: overlay mode (preserves scene text)
            logger.info("  -> Evaluating P8 in 'overlay' mode (Scene text preservation)...")
            pred_p8_overlay = out_dir / "pred_P8_overlay.mp4"
            res_edit_overlay = asyncio.run(editor_service.remove_text_from_video(
                input_path_or_url=str(text_mp4),
                mode="auto",
                target_scope="overlay",
            ))
            shutil.copy2(res_edit_overlay["output_path"], pred_p8_overlay)
            res_overlay = run_video_evaluation(
                pred_video_path=pred_p8_overlay,
                out_dir=out_dir,
                case_id="P8_overlay",
                clean_gt_path=clean_mp4,
                mask_dir=mask_dir,
                baseline_video_path=clean_mp4,
                category="SceneText",
                target_scope="overlay",
                is_scene_text=True,
                scene_mask_dir=scene_mask_dir if scene_mask_dir.exists() else None,
            )

            # Mode B: all mode (removes scene text)
            logger.info("  -> Evaluating P8 in 'all' mode (All text removal)...")
            pred_p8_all = out_dir / "pred_P8_all.mp4"
            res_edit_all = asyncio.run(editor_service.remove_text_from_video(
                input_path_or_url=str(text_mp4),
                mode="auto",
                target_scope="all",
            ))
            shutil.copy2(res_edit_all["output_path"], pred_p8_all)
            res_all = run_video_evaluation(
                pred_video_path=pred_p8_all,
                out_dir=out_dir,
                case_id="P8_all",
                clean_gt_path=clean_mp4,
                mask_dir=mask_dir,
                baseline_video_path=clean_mp4,
                category="SceneText",
                target_scope="all",
                is_scene_text=True,
                scene_mask_dir=scene_mask_dir if scene_mask_dir.exists() else None,
            )

            p8_pass = res_overlay["is_pass"] and res_all["is_pass"]
            case_results["P8"] = {
                "category": "SceneText",
                "overlay_mode": res_overlay,
                "all_mode": res_all,
                "is_pass": p8_pass,
            }
            if not p8_pass:
                all_pass = False

        elif cid == "P7":
            # Negative Control (no text)
            logger.info("  -> Evaluating P7 (Negative control, text-free)...")
            pred_p7 = out_dir / "pred_P7.mp4"
            res_edit_p7 = asyncio.run(editor_service.remove_text_from_video(
                input_path_or_url=str(text_mp4),
                mode="auto",
                target_scope="overlay",
            ))
            shutil.copy2(res_edit_p7["output_path"], pred_p7)
            res = run_video_evaluation(
                pred_video_path=pred_p7,
                out_dir=out_dir,
                case_id="P7",
                clean_gt_path=clean_mp4,
                mask_dir=mask_dir,
                baseline_video_path=clean_mp4,
                category="Negative",
                target_scope="overlay",
                is_scene_text=False,
            )
            case_results["P7"] = res
            if not res["is_pass"]:
                all_pass = False

        else:
            # Standard overlay text removal (P1-P6, P9-P10)
            pred_mp4 = out_dir / f"pred_{cid}.mp4"
            res_edit = asyncio.run(editor_service.remove_text_from_video(
                input_path_or_url=str(text_mp4),
                mode="auto",
                target_scope="overlay",
            ))
            shutil.copy2(res_edit["output_path"], pred_mp4)
            res = run_video_evaluation(
                pred_video_path=pred_mp4,
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

    # Real Clip Section 5.5 evaluation
    real_clip_summary = None
    real_clip_path = REPO_ROOT / "test" / "tmpy8evxmno.mp4"
    if enable_real_clip and real_clip_path.exists():
        logger.info(f"Executing Real Clip Section 5.5 evaluation on {real_clip_path}...")
        pred_real = out_dir / "cleaned_tmpy8evxmno.mp4"
        res_real_edit = asyncio.run(editor_service.remove_text_from_video(
            input_path_or_url=str(real_clip_path),
            mode="auto",
            target_scope="overlay",
        ))
        shutil.copy2(res_real_edit["output_path"], pred_real)
        real_clip_summary = run_video_evaluation(
            pred_video_path=pred_real,
            out_dir=out_dir,
            case_id="tmpy8evxmno",
            clean_gt_path=None,
            mask_dir=None,
            baseline_video_path=real_clip_path,
            category="RealClip",
            target_scope="overlay",
        )
        s55_metrics = evaluate_real_clip_section_5_5(pred_real, real_clip_path)
        real_clip_summary["section_5_5_metrics"] = s55_metrics
        if not s55_metrics["is_pass"]:
            real_clip_summary["is_pass"] = False
        if not real_clip_summary["is_pass"]:
            all_pass = False

    c8_res = evaluate_c8_resource_limits()
    if not c8_res["is_pass"]:
        all_pass = False

    overall_summary = {
        "suite": "public_synthetic_p1_p10",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope_parser_evaluation": scope_eval_result,
        "total_cases": len(case_results),
        "passed_cases": sum(1 for r in case_results.values() if r["is_pass"]),
        "all_cases_passed": all_pass,
        "resource_limits": c8_res,
        "case_results": case_results,
        "real_clip_evaluation": real_clip_summary,
        "is_pass": all_pass,
    }

    # Save summary.json
    summary_file = out_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(overall_summary, f, indent=2)

    # Save verdict.json
    verdict_file = out_dir / "verdict.json"
    verdict_data = {
        "schema_version": "3.0.0",
        "timestamp": overall_summary["timestamp"],
        "final_acceptance_verdict": "PASS" if all_pass else "FAIL",
        "scope_parser_accuracy": scope_eval_result["accuracy_percent"],
        "c8_resource_limits": c8_res,
        "summary": overall_summary,
    }
    with open(verdict_file, "w", encoding="utf-8") as f:
        json.dump(verdict_data, f, indent=2)

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
    parser.add_argument("--skip-real-clip", action="store_true", help="Skip 65s real clip processing")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0

    if args.output_video:
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

def print_human_readable_summary(overall_summary: Dict[str, Any]):
    print("\n" + "=" * 78)
    print("           ACCEPTANCE JUDGE VERDICT & COMPLIANCE SUMMARY (ROUND 3)         ")
    print("=" * 78)
    print(f" Timestamp: {overall_summary.get('timestamp')}")
    print(f" Suite:     {overall_summary.get('suite')}")
    print("-" * 78)
    print(" 1. SCOPE PARSER INTENT VERIFICATION (44 Frozen Phrases):")
    sp = overall_summary.get("scope_parser_evaluation", {})
    sp_status = "PASS" if sp.get("is_100_percent") else "FAIL"
    print(f"    - Accuracy: {sp.get('accuracy_percent', 0)}% ({sp.get('passed', 0)}/{sp.get('total_phrases', 0)} phrases) [{sp_status}]")
    print("-" * 78)
    print(" 2. SYNTHETIC PUBLIC CASES (P1 - P10):")
    print("    [Tuning Cases: P1 - P6]")
    cases = overall_summary.get("case_results", {})
    for cid in ["P1", "P2", "P3", "P4", "P5", "P6"]:
        cinfo = cases.get(cid, {})
        status = "PASS" if cinfo.get("is_pass") else "FAIL"
        words = cinfo.get("residual_words_total", 0)
        psnr = cinfo.get("reconstruction_psnr_median_db", "N/A")
        ssim = cinfo.get("reconstruction_ssim_median", "N/A")
        print(f"    * {cid:<4}: Status={status:<4} | Words={words} | Med PSNR={psnr} dB | Med SSIM={ssim}")

    print("    [Held-out Cases: P7 - P10]")
    for cid in ["P7", "P8", "P9", "P10"]:
        cinfo = cases.get(cid, {})
        status = "PASS" if cinfo.get("is_pass") else "FAIL"
        if cid == "P8":
            ov_pass = cinfo.get("overlay_mode", {}).get("is_pass", False)
            al_pass = cinfo.get("all_mode", {}).get("is_pass", False)
            print(f"    * {cid:<4}: Status={status:<4} | Overlay Mode: {'PASS' if ov_pass else 'FAIL'} | All Mode: {'PASS' if al_pass else 'FAIL'}")
        else:
            words = cinfo.get("residual_words_total", 0)
            psnr = cinfo.get("reconstruction_psnr_median_db", "N/A")
            ssim = cinfo.get("reconstruction_ssim_median", "N/A")
            print(f"    * {cid:<4}: Status={status:<4} | Words={words} | Med PSNR={psnr} dB | Med SSIM={ssim}")

    print("-" * 78)
    print(" 3. REAL CLIP ACCEPTANCE (tmpy8evxmno.mp4 - Section 5.5):")
    rc = overall_summary.get("real_clip_evaluation")
    if rc:
        rc_pass = "PASS" if rc.get("is_pass") else "FAIL"
        words = rc.get("residual_words_total", 0)
        av = rc.get("av_integrity", {})
        av_pass = "PASS" if av.get("is_pass") else "FAIL"
        md5_match = av.get("is_audio_md5_match")
        s55 = rc.get("section_5_5_metrics", {})
        band_psnr = s55.get("mean_band_psnr_db", "N/A")
        delta_ssim = s55.get("delta_ssim", "N/A")
        print(f"    - Overall: {rc_pass}")
        print(f"    - C1 Residual Text: {words} words (Threshold: 0)")
        print(f"    - C7 Audio Integrity: {av_pass} (Bit-exact MD5: {md5_match})")
        print(f"    - Text-free Band y[800,1000] PSNR: {band_psnr} dB (Threshold >= 40.0 dB)")
        print(f"    - Scene Text Delta SSIM: {delta_ssim} (Threshold <= 0.02)")
    else:
        print("    - Skipped / Not evaluated")

    print("-" * 78)
    print(" 4. RESOURCE LIMITS & PROCESS CLEANLINESS (C8):")
    c8 = overall_summary.get("resource_limits", {})
    c8_pass = "PASS" if c8.get("is_pass") else "FAIL"
    print(f"    - Status: {c8_pass}")
    print(f"    - Peak Container RSS: {c8.get('peak_rss_mb')} MB (Limit: {c8.get('max_limit_mb')} MB)")
    print(f"    - Orphan Processes: {c8.get('orphan_processes')}, Leaked GPU Jobs: {c8.get('leaked_gpu_jobs')}")
    print("=" * 78)
    final_v = "PASS" if overall_summary.get("is_pass") else "FAIL"
    print(f" FINAL ACCEPTANCE VERDICT: >>> {final_v} <<< (Exit Code: {0 if final_v == 'PASS' else 1})")
    print("=" * 78 + "\n")


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
    parser.add_argument("--skip-real-clip", action="store_true", help="Skip 65s real clip processing")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0

    if args.output_video:
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
        pub_res = run_public_suite(out_dir, seed=args.seed, enable_real_clip=(not args.skip_real_clip))
        print_human_readable_summary(pub_res)

        if not pub_res["is_pass"]:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
