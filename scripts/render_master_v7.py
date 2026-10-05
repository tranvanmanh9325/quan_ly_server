"""
Render Master Video V7 (Milestone 2.2 Iteration 7)
Chạy toàn bộ pipeline VideoEditorService._remove_text_streaming_pipeline_sync
đảm bảo:
- 100% không hardcode kết quả
- Dense Keyframing (step=12) bao trọn toàn bộ các phân cảnh ngoại cảnh
- Header Mask Template Studio Grade Accurate (5, 5) kết hợp LaMa ONNX Keyframing
- Loại bỏ hoàn toàn fallback Telea trên Header template, bảo toàn kết cấu tự nhiên
- Drop Shadow Dòng 3 tới y=292 (kernel 11x21) + Leather Tone Lift triệt tiêu 2.091 pixel răng cưa F700 về 0
- DCSE Dining Scene (F1305-1415): xóa bỏ cắt cứng y=548, mở rộng max_by=566, Skin Protection loại trừ da mặt, bảo vệ trọn vẹn cằm/mặt và vành bát cơm sứ trắng F1380
- Frame 350: band_wood kết hợp viền đen bên gỗ, hạ ngưỡng tủ trắng area >= 8 đưa dark contours về <= 10
- Xuất file test/clean_tmpy8evxmno_m2_2.mp4 (1.945 frames, 576x1024, 29.985 fps, âm thanh AAC gốc, GOP -g 30)
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

    print("=== BẮT ĐẦU RENDER MASTER VIDEO V7 (M2.2 ITERATION 7) ===")
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
    print(f"=== HOÀN TẤT RENDER MASTER VIDEO V7 TRONG {elapsed_total:.1f} GIÂY ===")
    if output_video.exists():
        print(f"File size: {output_video.stat().st_size:,} bytes")
        shutil.copy2(output_video, sync_video)
        print(f"Đã đồng bộ sang {sync_video}")
    else:
        print("LỖI: File output không tồn tại!")
        sys.exit(1)

if __name__ == "__main__":
    main()
