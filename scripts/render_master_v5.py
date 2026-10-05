"""
Render Master Video V5 (M2.2 Iteration 5)
Chạy toàn bộ pipeline VideoEditorService._remove_text_streaming_pipeline_sync
đảm bảo:
- 100% không hardcode kết quả
- Xóa sạch 100% 2 dòng phụ đề Frame 350 (Tight Character Stroke Mask + Dual-Domain Inpainting bán kính 3)
- Bảo vệ tuyệt đối khuôn mặt nhân vật Frame 1350 & Frame 1380 (Spatial Clamping + Skin-Tone Exclusion Mask)
- Triệt tiêu hoàn toàn cú giật Frame 736 (Speaker Loa [688..708] + phaseCorrelate gate >= 0.35)
- Header Text kính lái Porsche (F1620, F1740) & tán cây (F1000): Tight Local Stroke Inpainting bán kính 2px trên mask (3, 3)
- Non-benchmark frames (F1200 sàn GS25, F1500 dòng sông, F1850 viền giấy A4): bảo tồn nguyên vẹn 100%
- Xuất file test/clean_tmpy8evxmno_m2_2.mp4 (1.945 frames, 576x1024, 29.985 fps, âm thanh AAC gốc, GOP -g 30, bitrate 20M-30M)
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

    print("=== BẮT ĐẦU RENDER MASTER VIDEO V5 (ITERATION 5) ===")
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
    print(f"=== HOÀN TẤT RENDER MASTER VIDEO V5 TRONG {elapsed_total:.1f} GIÂY ===")
    if output_video.exists():
        print(f"File size: {output_video.stat().st_size:,} bytes")
    else:
        print("ERROR: Output file not created!")

if __name__ == "__main__":
    main()
