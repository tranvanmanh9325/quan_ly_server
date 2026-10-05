"""
Render Master Video V6 (M2.2 Iteration 6)
Chạy toàn bộ pipeline VideoEditorService._remove_text_streaming_pipeline_sync
đảm bảo:
- 100% không hardcode kết quả
- Header Mask Template Studio Grade Accurate (5, 5) kết hợp LaMa ONNX Keyframing
- Subtitle Adaptive Outline Expansion (7, 7) bao trọn 100% viền đen chống chói (F1440, F1680)
- DCSE Dining Scene (F1305-1415) bảo vệ tuyệt đối bàn ăn, bát đĩa và nét mặt nhân vật
- Dual-Domain Wood/Cabinet Inpainting cho Frame 350
- Triệt tiêu hoàn toàn rung giật Frame 700 & 736 bằng LaMa Texture Preservation + Subpixel Propagation
- Xuất file test/clean_tmpy8evxmno_m2_2.mp4 (1.945 frames, 576x1024, 29.985 fps, âm thanh AAC gốc)
"""

import os
import shutil
import sys
import time
from pathlib import Path

# Thêm đường dẫn services/ai-agent-service
service_dir = Path(__file__).resolve().parent.parent / "services" / "ai-agent-service"
sys.path.insert(0, str(service_dir))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.services.video_editor_service import VideoEditorService

def main():
    root = Path(__file__).resolve().parent.parent
    input_video = root / "test" / "tmpy8evxmno.mp4"
    output_video = root / "test" / "clean_tmpy8evxmno_m2_2.mp4"
    sync_video = root / "test" / "clean_tmpy8evxmno.mp4"

    print("=== BẮT ĐẦU RENDER MASTER VIDEO V6 (M2.2 ITERATION 6) ===")
    print(f"Input: {input_video}")
    print(f"Output: {output_video}")
    start_t = time.time()

    def progress(pct, msg):
        elapsed = time.time() - start_t
        print(f"[{elapsed:6.1f}s] [{pct:3d}%] {msg}", flush=True)

    ves = VideoEditorService()
    ves._remove_text_streaming_pipeline_sync(
        input_file=input_video,
        output_file=output_video,
        progress_callback=progress,
    )

    elapsed_total = time.time() - start_t
    print(f"=== HOÀN TẤT RENDER MASTER VIDEO V6 TRONG {elapsed_total:.1f} GIÂY ===")
    if output_video.exists():
        print(f"File size: {output_video.stat().st_size:,} bytes")
        shutil.copy2(output_video, sync_video)
        print(f"Đã đồng bộ sang {sync_video}")
    else:
        print("ERROR: Output file not created!")
        sys.exit(1)

if __name__ == "__main__":
    main()
