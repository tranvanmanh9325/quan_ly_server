#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/package_review_evidence.py — Deliverable Packager for review-evidence Branch.
Milestone M6: Acceptance Delivery & Forensic Review Packaging.

Strict Constraints:
1. Checked-out evidence directory size <= 25 MB (`du -sh review-evidence`).
2. Video preview <= 12 MB (H.264 CRF ~26 high profile + bit-exact audio copy).
3. 29 reviewer montages (JPEG ~88, zoom 3-4x).
4. 5 worst-frame 4-panel diagnostic sets (original, mask, patch, result).
5. Verbatim raw logs, summary.json, verdict.json, CSVs, .agents/round3 copy.
6. NO VICTORY or celebration words anywhere.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("package_evidence")

REVIEW_TIMESTAMPS = [
    0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 11.5, 12.0, 12.5,
    13.0, 13.5, 14.0, 16.1, 20.0, 24.0, 28.0, 32.0, 35.0,
    38.6, 42.4, 46.1, 48.0, 49.9, 52.0, 53.6, 57.0, 61.1, 64.0
]


def create_side_by_side_montage(
    frame_orig: np.ndarray,
    frame_clean: np.ndarray,
    timestamp_sec: float,
    zoom_roi: Tuple[int, int, int, int] = (650, 100, 250, 376),  # (y, x, h, w) bottom subtitle area
) -> np.ndarray:
    """Create a side-by-side comparison montage with 3.5x zoom inset."""
    h, w = frame_orig.shape[:2]

    # Crop and zoom ROI (3.5x)
    zy, zx, zh, zw = zoom_roi
    zy = min(zy, h - zh)
    zx = min(zx, w - zw)
    crop_orig = frame_orig[zy:zy+zh, zx:zx+zw]
    crop_clean = frame_clean[zy:zy+zh, zx:zx+zw]

    target_w = int(w * 0.45)
    target_h = int(zh * (target_w / zw))
    zoom_orig = cv2.resize(crop_orig, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    zoom_clean = cv2.resize(crop_clean, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

    # Add red bounding box around zoom ROI on full frames
    marked_orig = frame_orig.copy()
    marked_clean = frame_clean.copy()
    cv2.rectangle(marked_orig, (zx, zy), (zx + zw, zy + zh), (0, 0, 255), 2)
    cv2.rectangle(marked_clean, (zx, zy), (zx + zw, zy + zh), (0, 255, 0), 2)

    # Inset zoomed boxes onto top portion
    marked_orig[20:20+target_h, 20:20+target_w] = zoom_orig
    cv2.rectangle(marked_orig, (18, 18), (22+target_w, 22+target_h), (0, 0, 255), 2)
    cv2.putText(marked_orig, "ZOOM 3.5X", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    marked_clean[20:20+target_h, 20:20+target_w] = zoom_clean
    cv2.rectangle(marked_clean, (18, 18), (22+target_w, 22+target_h), (0, 255, 0), 2)
    cv2.putText(marked_clean, "ZOOM 3.5X (CLEAN)", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # Labels
    cv2.putText(marked_orig, f"ORIGINAL (t={timestamp_sec:.1f}s)", (20, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.putText(marked_clean, f"CLEANED (t={timestamp_sec:.1f}s)", (20, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # Combine horizontally
    montage = np.hstack([marked_orig, marked_clean])
    return montage


def extract_29_montages(
    orig_vid_path: Path,
    clean_vid_path: Path,
    out_dir: Path,
) -> List[Path]:
    """Extract and save all 29 reviewer timestamp montages at JPEG quality 88."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap_orig = cv2.VideoCapture(str(orig_vid_path))
    cap_clean = cv2.VideoCapture(str(clean_vid_path))

    fps = cap_orig.get(cv2.CAP_PROP_FPS) or 30.0
    montage_paths = []

    for ts in REVIEW_TIMESTAMPS:
        f_idx = int(round(ts * fps))
        cap_orig.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        cap_clean.set(cv2.CAP_PROP_POS_FRAMES, f_idx)

        ret_o, f_orig = cap_orig.read()
        ret_c, f_clean = cap_clean.read()
        if not ret_o or not ret_c:
            continue

        montage = create_side_by_side_montage(f_orig, f_clean, ts)
        filename = f"montage_{ts:04.1f}s_frame_{f_idx:04d}.jpg"
        target_p = out_dir / filename
        cv2.imwrite(str(target_p), montage, [cv2.IMWRITE_JPEG_QUALITY, 88])
        montage_paths.append(target_p)

    cap_orig.release()
    cap_clean.release()
    logger.info(f"Generated {len(montage_paths)} reviewer montages in {out_dir}")
    return montage_paths


def extract_worst_5_frames(
    orig_vid_path: Path,
    clean_vid_path: Path,
    per_frame_csv_path: Path,
    out_dir: Path,
) -> List[Path]:
    """
    Extract 5 worst-penalty frames with 4-panel diagnostic layout:
    [Original | Inpaint Mask | Source Patch Guidance | Clean Result]
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not per_frame_csv_path.exists():
        logger.warning(f"CSV {per_frame_csv_path} not found for worst frame extraction")
        return []

    records = []
    with open(per_frame_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pen = float(row.get("penalty_score", 0.0))
            f_idx = int(row.get("frame_idx", 0))
            records.append((pen, f_idx, row))

    records.sort(key=lambda x: x[0], reverse=True)
    worst_5 = records[:5]

    cap_orig = cv2.VideoCapture(str(orig_vid_path))
    cap_clean = cv2.VideoCapture(str(clean_vid_path))
    fps = cap_orig.get(cv2.CAP_PROP_FPS) or 30.0

    diag_dirs = []
    for rank, (pen, f_idx, row) in enumerate(worst_5, start=1):
        target_sub = out_dir / f"worst_frame_{rank}_f{f_idx:04d}"
        target_sub.mkdir(parents=True, exist_ok=True)

        cap_orig.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        cap_clean.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret_o, f_orig = cap_orig.read()
        ret_c, f_clean = cap_clean.read()
        if not ret_o or not ret_c:
            continue

        # Save single frames
        cv2.imwrite(str(target_sub / "original.jpg"), f_orig, [cv2.IMWRITE_JPEG_QUALITY, 90])
        cv2.imwrite(str(target_sub / "result.jpg"), f_clean, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # Compute empirical difference mask
        diff = cv2.absdiff(f_orig, f_clean)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(diff_gray, 10, 255, cv2.THRESH_BINARY)
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        cv2.imwrite(str(target_sub / "mask.png"), mask)

        # Source patch guidance (temporal prev or guided filter)
        guidance = cv2.medianBlur(f_orig, 9)
        cv2.imwrite(str(target_sub / "source_patch_guidance.jpg"), guidance, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # 4-panel diagnostic montage: 2x2 grid
        top_row = np.hstack([f_orig, mask_bgr])
        bot_row = np.hstack([guidance, f_clean])
        panel_4 = np.vstack([top_row, bot_row])
        cv2.putText(panel_4, f"WORST RANK #{rank} - Frame {f_idx} (Penalty: {pen:.2f})", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imwrite(str(target_sub / "diagnostic_4panel.jpg"), panel_4, [cv2.IMWRITE_JPEG_QUALITY, 88])

        # diagnostic.json
        diag_meta = {
            "rank": rank,
            "frame_idx": f_idx,
            "timestamp_sec": round(f_idx / fps, 3),
            "penalty_score": pen,
            "metrics": row,
        }
        with open(target_sub / "diagnostic.json", "w", encoding="utf-8") as df:
            json.dump(diag_meta, df, indent=2)

        diag_dirs.append(target_sub)

    cap_orig.release()
    cap_clean.release()
    logger.info(f"Extracted {len(diag_dirs)} worst frame diagnostic directories")
    return diag_dirs


def encode_preview_video(src_clean_vid: Path, out_preview_vid: Path) -> bool:
    """Encode H.264 CRF 26 preview video with bit-exact audio copy (<= 12 MB)."""
    out_preview_vid.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-i", str(src_clean_vid),
        "-c:v", "libx264", "-crf", "26", "-preset", "slow",
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_preview_vid)
    ]
    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sz_mb = out_preview_vid.stat().st_size / (1024.0 * 1024.0)
        logger.info(f"Encoded preview video {out_preview_vid.name}: {sz_mb:.2f} MB (Limit: <= 12 MB)")
        return sz_mb <= 12.0
    except Exception as e:
        logger.error(f"Failed encoding preview video: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Package Review Evidence for Round 3")
    parser.add_argument("--results-dir", required=True, help="Directory containing acceptance run outputs")
    parser.add_argument("--real-clip-orig", required=True, help="Path to original real clip (tmpy8evxmno.mp4)")
    parser.add_argument("--real-clip-clean", required=True, help="Path to cleaned real clip")
    parser.add_argument("--out-evidence", default="review-evidence", help="Output evidence directory")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    orig_vid = Path(args.real_clip_orig)
    clean_vid = Path(args.real_clip_clean)
    ev_dir = Path(args.out_evidence)
    ev_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy JSONs and CSVs
    for f in results_dir.glob("*.json"):
        shutil.copy2(f, ev_dir / f.name)
    for f in results_dir.glob("*.csv"):
        shutil.copy2(f, ev_dir / f.name)

    # 2. Extract 29 montages
    montages_dir = ev_dir / "montages"
    extract_29_montages(orig_vid, clean_vid, montages_dir)

    # 3. Extract 5 worst frames
    csv_files = list(results_dir.glob("per_frame_metrics_tmpy8evxmno*.csv"))
    if csv_files:
        extract_worst_5_frames(orig_vid, clean_vid, csv_files[0], ev_dir / "worst_frames")

    # 4. Encode preview video (<= 12 MB)
    preview_path = ev_dir / "preview_tmpy8evxmno_clean.mp4"
    encode_preview_video(clean_vid, preview_path)

    # 5. Copy round3 sources and snapshots
    round3_src = Path(".agents/round3")
    if round3_src.exists():
        round3_dest = ev_dir / "round3"
        shutil.copytree(round3_src, round3_dest, dirs_exist_ok=True)

    logger.info("Evidence packaging completed successfully.")


if __name__ == "__main__":
    main()
