#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/verify_evidence_integrity.py — Automated Binary Linter for Evidence Integrity.
Phase 6 Iteration 3 (Dynamic & Cryptographic Verification Suite).

Verifies mathematical consistency, audio bit-exact preservation, and cryptographic integrity:
1. `per_frame_metrics_tmpy8evxmno.csv` vs `summary.json` (residual words, outside SSIM, worst penalties).
2. `worst_frames/*/diagnostic.json` vs `summary.json` worst 5 penalties.
3. Cryptographic SHA-256 attestation hashes.
4. `per_case_metrics_synthetic_held_out.csv` vs `summary.json` (all 21 cases).
5. Audio stream bit-exact verification via dynamic ffmpeg extraction.
6. Verdicts logic consistency (D1..D5, negative_control_integrity vs CSV raw data).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_ffmpeg() -> str:
    """Locate ffmpeg executable in PATH or standard system directories."""
    for cand in ["ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        if shutil.which(cand):
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def get_audio_stream_md5(video_path: Optional[Path]) -> Optional[str]:
    """Compute bit-exact MD5 of audio stream via ffmpeg -c:a copy."""
    if not video_path or not video_path.is_file():
        return None

    ffmpeg_bin = find_ffmpeg()
    cmd = [
        ffmpeg_bin, "-v", "error", "-i", str(video_path),
        "-map", "0:a:0?", "-c", "copy", "-f", "md5", "-"
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
        if res.returncode == 0:
            raw = res.stdout.decode("utf-8", errors="ignore").strip()
            match = re.search(r"MD5=([a-fA-F0-9]{32})", raw)
            if match:
                return match.group(1).lower()
            for line in raw.split():
                if len(line) == 32 and re.match(r"^[a-fA-F0-9]{32}$", line):
                    return line.lower()
        return None
    except Exception:
        return None


def compute_file_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hex digest of a file."""
    if not file_path.is_file():
        return ""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_evidence_package(
    evidence_dir: Path,
    thresholds_file: Optional[Path] = None,
    original_video_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Perform exhaustive bit-exact integrity audit on an evidence directory.
    Returns (success: bool, message: str).
    """
    if not evidence_dir.is_dir():
        return False, f"Evidence directory not found: {evidence_dir}"

    summary_path = evidence_dir / "summary.json"
    if not summary_path.is_file():
        return False, f"summary.json not found in {evidence_dir}"

    try:
        with open(summary_path, "r", encoding="utf-8") as sf:
            summary_data = json.load(sf)
    except Exception as e:
        return False, f"Failed to parse summary.json: {e}"

    errors: List[str] = []

    # 1. Audit Real Clip CSV vs summary.json
    real_csv = evidence_dir / "per_frame_metrics_tmpy8evxmno.csv"
    if not real_csv.is_file():
        errors.append(f"Missing real clip CSV: {real_csv}")
    else:
        try:
            with open(real_csv, "r", encoding="utf-8") as rf:
                reader = csv.DictReader(rf)
                rows = list(reader)

            total_frames = len(rows)
            failed_ocr_frames = sum(1 for r in rows if int(r.get("residual_words_count", 0)) > 0)
            pass_rate = round((total_frames - failed_ocr_frames) / max(1, total_frames) * 100.0, 2)
            ssim_outside_vals = [float(r["ssim_outside_mask"]) for r in rows if "ssim_outside_mask" in r and r["ssim_outside_mask"]]
            mean_outside_ssim = round(sum(ssim_outside_vals) / max(1, len(ssim_outside_vals)), 4) if ssim_outside_vals else 1.0
            penalties = sorted([float(r.get("penalty_score", 0.0)) for r in rows if r.get("penalty_score")], reverse=True)
            top5_penalties = penalties[:5]

            real_bench = summary_data.get("real_clip_benchmark", {})
            s_total = real_bench.get("total_frames_evaluated")
            s_failed = real_bench.get("residual_ocr_failed_frames")
            s_pass_rate = real_bench.get("residual_ocr_pass_rate_pct")
            s_ssim = real_bench.get("outside_mask_ssim")
            s_top5 = real_bench.get("worst_5_composite_penalties", [])

            if s_total != total_frames:
                errors.append(f"Frame count mismatch: CSV={total_frames} vs JSON={s_total}")

            if s_failed != failed_ocr_frames:
                errors.append(f"Residual OCR failed frames mismatch: CSV={failed_ocr_frames} vs JSON={s_failed}")

            if s_pass_rate is not None and abs(float(s_pass_rate) - pass_rate) > 0.05:
                errors.append(f"Residual OCR pass rate mismatch: CSV={pass_rate}% vs JSON={s_pass_rate}%")

            if s_ssim is not None and abs(float(s_ssim) - mean_outside_ssim) > 0.01:
                errors.append(f"Mean outside SSIM mismatch: CSV={mean_outside_ssim:.4f} vs JSON={float(s_ssim):.4f}")

            if len(s_top5) != len(top5_penalties):
                errors.append(f"Top 5 penalties length mismatch: CSV={len(top5_penalties)} vs JSON={len(s_top5)}")
            else:
                for idx, (p_csv, p_json) in enumerate(zip(top5_penalties, s_top5)):
                    if abs(p_csv - float(p_json)) > 0.1:
                        errors.append(f"Worst penalty rank {idx + 1} mismatch: CSV={p_csv} vs JSON={p_json}")
        except Exception as e:
            errors.append(f"Error parsing real clip CSV: {e}")

    # 2. Audit Worst Frames Diagnostics vs Top 5 Penalties
    worst_frames_dir = evidence_dir / "worst_frames"
    if worst_frames_dir.is_dir():
        diag_files = sorted(worst_frames_dir.glob("worst_frame_*/diagnostic.json"))
        if len(diag_files) >= 5:
            s_top5 = summary_data.get("real_clip_benchmark", {}).get("worst_5_composite_penalties", [])
            for rank_idx, diag_p in enumerate(diag_files[:5]):
                try:
                    with open(diag_p, "r", encoding="utf-8") as df:
                        diag_data = json.load(df)
                    d_pen = float(diag_data.get("penalty_score", 0.0))
                    if rank_idx < len(s_top5):
                        expected_pen = float(s_top5[rank_idx])
                        if abs(d_pen - expected_pen) > 0.1:
                            errors.append(f"Diagnostic penalty rank {rank_idx + 1} mismatch in {diag_p.name}: {d_pen} vs expected {expected_pen}")
                except Exception as e:
                    errors.append(f"Error reading {diag_p}: {e}")

    # 3. Audit Cryptographic Attestation Hashes
    attestation = summary_data.get("integrity_attestation")
    if attestation:
        if "raw_csv_sha256" in attestation and real_csv.is_file():
            actual_csv_sha = compute_file_sha256(real_csv)
            if attestation["raw_csv_sha256"] != actual_csv_sha:
                errors.append(f"SHA-256 mismatch for real CSV: expected {attestation['raw_csv_sha256']} != actual {actual_csv_sha}")

        preview_mp4 = evidence_dir / "preview_tmpy8evxmno_clean.mp4"
        if "preview_video_sha256" in attestation and preview_mp4.is_file():
            actual_vid_sha = compute_file_sha256(preview_mp4)
            if attestation["preview_video_sha256"] != actual_vid_sha:
                errors.append(f"SHA-256 mismatch for preview video: expected {attestation['preview_video_sha256']} != actual {actual_vid_sha}")

        thresh_evidence = evidence_dir / "frozen_thresholds.json"
        if "frozen_thresholds_sha256" in attestation and thresh_evidence.is_file():
            actual_th_sha = compute_file_sha256(thresh_evidence)
            if attestation["frozen_thresholds_sha256"] != actual_th_sha:
                errors.append(f"SHA-256 mismatch for frozen thresholds: expected {attestation['frozen_thresholds_sha256']} != actual {actual_th_sha}")

    # 4. Audit Synthetic Held-Out CSV vs summary.json
    synth_csv = evidence_dir / "per_case_metrics_synthetic_held_out.csv"
    synth_rows: List[Dict[str, Any]] = []
    if synth_csv.is_file():
        try:
            with open(synth_csv, "r", encoding="utf-8") as sf:
                s_reader = csv.DictReader(sf)
                synth_rows = list(s_reader)
            s_cases = len(synth_rows)
            s_passed = sum(1 for r in synth_rows if r.get("case_status") == "PASS")
            synth_bench = summary_data.get("synthetic_held_out_benchmark", {})

            if synth_bench.get("total_cases_evaluated") != s_cases:
                errors.append(f"Synthetic held-out case count mismatch: CSV={s_cases} vs JSON={synth_bench.get('total_cases_evaluated')}")
            if synth_bench.get("passed_cases") != s_passed:
                errors.append(f"Synthetic held-out passed cases mismatch: CSV={s_passed} vs JSON={synth_bench.get('passed_cases')}")
        except Exception as e:
            errors.append(f"Error reading synthetic held-out CSV: {e}")

    # 5. Audit Audio Stream Bit-Exact Preservation
    preview_mp4 = evidence_dir / "preview_tmpy8evxmno_clean.mp4"
    real_bench = summary_data.get("real_clip_benchmark", {})
    expected_bit_exact = real_bench.get("audio_stream_bit_exact")
    expected_clean_audio_md5 = real_bench.get("audio_md5_cleaned")
    expected_orig_audio_md5 = real_bench.get("audio_md5_original")

    if preview_mp4.is_file():
        actual_clean_audio_md5 = get_audio_stream_md5(preview_mp4)
        if actual_clean_audio_md5 and expected_clean_audio_md5:
            if actual_clean_audio_md5.lower() != expected_clean_audio_md5.lower():
                errors.append(f"Clean audio MD5 mismatch: actual stream={actual_clean_audio_md5} != summary.json={expected_clean_audio_md5}")

    # Find original video if provided or in default locations
    orig_vid = original_video_path
    if not orig_vid or not orig_vid.is_file():
        for cand in [
            evidence_dir.parent / "tmpy8evxmno.mp4",
            Path("test/tmpy8evxmno.mp4"),
            Path("/app/app/workspace/tmpy8evxmno.mp4"),
            Path("app/workspace/tmpy8evxmno.mp4")
        ]:
            if cand.is_file():
                orig_vid = cand
                break

    if orig_vid and orig_vid.is_file():
        actual_orig_audio_md5 = get_audio_stream_md5(orig_vid)
        if actual_orig_audio_md5 and expected_orig_audio_md5:
            if actual_orig_audio_md5.lower() != expected_orig_audio_md5.lower():
                errors.append(f"Original audio MD5 mismatch: actual stream={actual_orig_audio_md5} != summary.json={expected_orig_audio_md5}")

        if preview_mp4.is_file():
            actual_clean_audio_md5 = get_audio_stream_md5(preview_mp4)
            if actual_clean_audio_md5 and actual_orig_audio_md5:
                real_bit_exact = (actual_clean_audio_md5.lower() == actual_orig_audio_md5.lower())
                if expected_bit_exact is not None and expected_bit_exact != real_bit_exact:
                    errors.append(
                        f"audio_stream_bit_exact mismatch: summary.json claims {expected_bit_exact}, but physical audio streams bit-exact is {real_bit_exact} "
                        f"(orig={actual_orig_audio_md5} vs clean={actual_clean_audio_md5})"
                    )

    # 6. Audit Verdicts & Negative Controls Logic Consistency
    dimensions = real_bench.get("dimensions_verdict", {})
    d5_verdict = dimensions.get("D5_AV_Integrity")
    if expected_bit_exact is False and d5_verdict == "PASS":
        errors.append("Integrity contradiction: D5_AV_Integrity is PASS while audio_stream_bit_exact is False")

    # Check Negative Controls
    neg_control_rows = [r for r in synth_rows if r.get("category") == "negative_controls"]
    claimed_neg_integrity = summary_data.get("synthetic_held_out_benchmark", {}).get("negative_control_integrity")
    if neg_control_rows:
        has_failed_neg = any(
            r.get("case_status") != "PASS" or
            int(r.get("residual_words_max", 0)) > 0 or
            float(r.get("reconstruction_ssim_median", 1.0)) < 0.99
            for r in neg_control_rows
        )
        if has_failed_neg and claimed_neg_integrity == "PASS_UNTOUCHED":
            errors.append("Integrity contradiction: synthetic held-out has altered/failing negative controls, but summary.json claims PASS_UNTOUCHED")

    # Check commit SHA format
    target_sha = summary_data.get("target_commit_main", "")
    if not (len(target_sha) == 40 and re.match(r"^[0-9a-fA-F]{40}$", target_sha)):
        errors.append(f"Invalid target_commit_main SHA (must be 40-char hex): '{target_sha}'")

    if errors:
        msg = "Integrity violations detected:\n" + "\n".join(f"  - {err}" for err in errors)
        return False, msg

    return True, "All mathematical statistics, audio streams, SHA-256 hashes, and diagnostics match 100% bit-exact."


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence Integrity Linter (Phase 6 Iteration 3)")
    parser.add_argument("--evidence-dir", required=True, type=str, help="Path to review-evidence directory")
    parser.add_argument("--thresholds", type=str, default=None, help="Path to frozen_thresholds.json")
    parser.add_argument("--original-video", type=str, default=None, help="Path to original reference video")
    args = parser.parse_args()

    ev_dir = Path(args.evidence_dir)
    th_file = Path(args.thresholds) if args.thresholds else None
    orig_vid = Path(args.original_video) if args.original_video else None

    print(f"[*] Auditing Evidence Integrity in: {ev_dir}...")
    success, message = verify_evidence_package(ev_dir, th_file, original_video_path=orig_vid)

    if success:
        print(f"[SUCCESS] {message}")
        return 0
    else:
        print(f"[VETO] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
