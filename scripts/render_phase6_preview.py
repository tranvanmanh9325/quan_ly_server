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
import os
import shutil
import sys
import time
from pathlib import Path

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


def render_preview(input_path: Path, output_path: Path) -> bool:
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
    try:
        ves._remove_text_streaming_pipeline_sync(
            input_file=input_path,
            output_file=output_path,
            progress_callback=progress,
            target_scope="overlay_only",
        )
    except Exception as e:
        print(f"[ERROR] Pipeline rendering failed: {e}", file=sys.stderr, flush=True)
        return False

    elapsed_total = time.time() - start_t
    if output_path.exists() and output_path.stat().st_size > 1000:
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
    args = parser.parse_args()

    success = render_preview(Path(args.input), Path(args.output))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
