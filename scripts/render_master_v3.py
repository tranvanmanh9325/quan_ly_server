"""
Render Master Video V3 (M2.2 Iteration 3)
Chạy toàn bộ pipeline VideoEditorService._remove_text_streaming_pipeline_sync
đảm bảo:
- 100% không hardcode
- Tự động phát hiện phân cảnh và sinh keyframes
- Dynamic Stroke Mask 2 pha
- KeyframeDiskCache kiểm soát RAM < 35MB
- Xuất file test/clean_tmpy8evxmno_m2_2.mp4
"""

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

    print(f"=== BẮT ĐẦU RENDER MASTER VIDEO V3 ===")
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
    print(f"=== HOÀN TẤT RENDER MASTER VIDEO V3 TRONG {elapsed_total:.1f} GIÂY ===")
    print(f"File size: {output_video.stat().st_size:,} bytes")

if __name__ == "__main__":
    main()
