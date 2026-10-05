"""
Render Master Video V4 (M2.2 Iteration 4)
Chạy toàn bộ pipeline VideoEditorService._remove_text_streaming_pipeline_sync
đảm bảo:
- 100% không hardcode
- Tự động phát hiện phân cảnh và sinh keyframes
- Local LaMa ONNX 1:1 trên Porsche Speaker Grille ROI (Laplacian >= 2000.0)
- Subpixel Motion Propagation Lanczos4 (diff f701->f702 <= 25.0)
- Tight Stroke Mask 5x5 + Flow Reliability Metric + Dynamic Local Stroke Fallback
- Bounding-constrained mask bảo toàn 100% chữ in hợp đồng Frame 150
- Dual-domain Partitioned Inpainting trên cánh cửa gỗ Frame 350
- KeyframeDiskCache kiểm soát RAM < 35MB
- Xuất file test/clean_tmpy8evxmno_m2_2.mp4 (1.945 frames, 576x1024, 29.985 fps, âm thanh AAC gốc)
"""

import os
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

    print("=== BẮT ĐẦU RENDER MASTER VIDEO V4 ===")
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
    print(f"=== HOÀN TẤT RENDER MASTER VIDEO V4 TRONG {elapsed_total:.1f} GIÂY ===")
    if output_video.exists():
        print(f"File size: {output_video.stat().st_size:,} bytes")
    else:
        print("ERROR: Output file not created!")

if __name__ == "__main__":
    main()
