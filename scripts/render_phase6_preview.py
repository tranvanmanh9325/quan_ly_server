#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_phase6_preview.py — Phase 6 Clean Video Renderer.
Renders tmpy8evxmno.mp4 with VideoEditorService 5-Pillar streaming pipeline:
- Pillar 1: Scene Text Guard (Preserves laptop screens F1400-F1422)
- Pillar 2: Line Clustering (Clusters sub-boxes, avoids mega-box 669px)
- Pillar 3: Adaptive Dilation 8-12px (Full coverage of TikTok text strokes & drop shadows)
- Pillar 4: Strict Non-Mask Invariance & Photometric Gating <= 12.0
- Pillar 5: Studio Grade CRF 18 Encoding (Zero bit-rate clamping)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_audio_stream_md5(video_path: Path) -> Optional[str]:
    """Trích xuất MD5 của audio stream 0:a:0 bằng FFmpeg."""
    if not video_path.is_file():
        return None
    try:
        cmd = [
            "ffmpeg", "-v", "error",
            "-i", str(video_path),
            "-map", "0:a:0?",
            "-c", "copy",
            "-f", "md5", "-"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = res.stdout.strip()
        if "MD5=" in out:
            return out.split("MD5=")[-1].strip().lower()
        return out.lower() if len(out) == 32 else None
    except Exception:
        return None

# Add paths
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/app")
sys.path.insert(0, str(_REPO_ROOT / "services" / "ai-agent-service"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.services.video_editor_service import VideoEditorService


def render_preview(
    input_path: Path,
    output_path: Path,
    target_regions_path: Optional[Path] = None
) -> bool:
    print("=" * 70, flush=True)
    print("PHASE 6 PREVIEW CLEAN VIDEO RENDERER", flush=True)
    print(f"Input:  {input_path} ({input_path.stat().st_size:,} bytes)", flush=True)
    print(f"Output: {output_path}", flush=True)
    print("=" * 70, flush=True)

    start_t = time.time()

    def progress(pct: int, msg: str) -> None:
        elapsed = time.time() - start_t
        print(f"[{elapsed:6.1f}s] [{pct:3d}%] {msg}", flush=True)

    ves = VideoEditorService()

    # Load or detect target regions
    target_regions = None
    if target_regions_path and target_regions_path.exists():
        print(f"[*] Loading target regions from {target_regions_path}...", flush=True)
        with open(target_regions_path, "r", encoding="utf-8") as f:
            target_regions = json.load(f)
    else:
        # Check adjacent target_regions_tmpy8evxmno.json
        candidate_file = input_path.parent / "target_regions_tmpy8evxmno.json"
        if candidate_file.exists():
            print(f"[*] Loading target regions from adjacent {candidate_file}...", flush=True)
            with open(candidate_file, "r", encoding="utf-8") as f:
                target_regions = json.load(f)
        else:
            print("[*] Auto-detecting text regions across video frames...", flush=True)
            try:
                target_regions = asyncio.run(ves._auto_detect_text_region(input_path, target_scope="overlay"))
                with open(candidate_file, "w", encoding="utf-8") as f:
                    json.dump(target_regions, f, ensure_ascii=False, indent=2)
                print(f"[OK] Saved detected regions to {candidate_file}", flush=True)
            except Exception as det_err:
                print(f"[!] Auto-detect failed: {det_err}. Proceeding with default scope.", flush=True)
                target_regions = None

    if target_regions:
        print(f"[OK] Loaded {len(target_regions)} target regions for inpainting pipeline.", flush=True)
    else:
        print("[!] Warning: No target regions provided.", flush=True)

    try:
        ves._remove_text_streaming_pipeline_sync(
            input_file=input_path,
            output_file=output_path,
            progress_callback=progress,
            target_regions=target_regions,
            target_scope="overlay",
        )
    except Exception as e:
        print(f"[ERROR] Pipeline rendering failed: {e}", file=sys.stderr, flush=True)
        return False

    elapsed_total = time.time() - start_t
    if output_path.exists() and output_path.stat().st_size > 1000:
        # Kiểm tra tính toàn vẹn Bit-Exact Audio Stream
        orig_audio_md5 = get_audio_stream_md5(input_path)
        clean_audio_md5 = get_audio_stream_md5(output_path)
        print(f"[*] Audio Integrity Audit:", flush=True)
        print(f"    - Original Audio MD5: {orig_audio_md5}", flush=True)
        print(f"    - Cleaned Audio MD5:  {clean_audio_md5}", flush=True)
        if orig_audio_md5 and clean_audio_md5:
            if orig_audio_md5 != clean_audio_md5:
                print(f"[ERROR] Audio stream MD5 mismatch! Preservation failed ({orig_audio_md5} != {clean_audio_md5})", file=sys.stderr, flush=True)
                return False
            print(f"[OK] Audio stream bit-exact verified (100% match)!", flush=True)

        print("=" * 70, flush=True)
        print(f"[OK] Render completed in {elapsed_total:.1f}s! Size: {output_path.stat().st_size:,} bytes", flush=True)
        print("=" * 70, flush=True)
        return True
    else:
        print(f"[ERROR] Output file missing or invalid!", file=sys.stderr, flush=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 6 Video Renderer")
    parser.add_argument("--input", default="/tmp/tmpy8evxmno.mp4", type=str)
    parser.add_argument("--output", default="/tmp/preview_tmpy8evxmno_clean.mp4", type=str)
    parser.add_argument("--target-regions", default=None, type=str)
    args = parser.parse_args()

    success = render_preview(
        input_path=Path(args.input),
        output_path=Path(args.output),
        target_regions_path=Path(args.target_regions) if args.target_regions else None
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
