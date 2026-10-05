import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

# Add app to path
sys.path.insert(0, "/app")

from app.services.video_editor_service import VideoEditorService

async def main():
    input_path = Path("/tmp/parent_orig.mp4")
    output_path = Path("/tmp/cleaned_tmpy8evxmno.mp4")

    if not input_path.exists():
        print(f"Error: {input_path} does not exist!")
        sys.exit(1)

    print("=== BẮT ĐẦU RENDER VIDEO M2.6 (ITERATION 6) ===", flush=True)
    print(f"Input: {input_path} ({input_path.stat().st_size:,} bytes)", flush=True)
    print(f"Output: {output_path}", flush=True)
    start_t = time.time()

    ves = VideoEditorService()

    # 1. Auto detect regions
    print("\n--- 1. Quét tìm text regions bằng Auto Detect ---", flush=True)
    target_regions = await ves._auto_detect_text_region(input_path)
    print(f"Tìm thấy {len(target_regions)} target regions:", flush=True)
    for r in target_regions:
        if r.get("type") == "title" or r.get("is_static", False):
            print(f"  Title: x={r.get('x')}, y={r.get('y')}, w={r.get('w')}, h={r.get('h')}", flush=True)
        else:
            print(f"  Subtitle: '{r.get('text', '')[:20]}' at y={r.get('y')}, frames {r.get('frame_start')}..{r.get('frame_end')}", flush=True)

    # 2. Chạy streaming pipeline
    print("\n--- 2. Chạy Streaming Pipeline (Hosted LaMa + DIS Flow + Guided Filter M2.6) ---", flush=True)
    def progress_cb(pct, msg):
        elapsed = time.time() - start_t
        print(f"[{elapsed:6.1f}s] [{pct:3d}%] {msg}", flush=True)

    await asyncio.to_thread(
        ves._remove_text_streaming_pipeline_sync,
        input_path,
        output_path,
        progress_cb,
        None,
        target_regions,
    )

    elapsed_total = time.time() - start_t
    print(f"\n=== HOÀN TẤT RENDER TRONG {elapsed_total:.1f} GIÂY ===", flush=True)
    if output_path.exists():
        sz = output_path.stat().st_size
        print(f"Output size: {sz:,} bytes ({sz / 1024 / 1024:.2f} MB)", flush=True)
    else:
        print("LỖI: Output file không tồn tại!", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
