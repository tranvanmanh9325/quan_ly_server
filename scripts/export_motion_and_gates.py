"""
export_motion_and_gates.py
Xuất 4 ảnh Gate và clip chuyển động test/crop_text_motion_check.mp4 từ master video v3.
"""

import sys
import shutil
from pathlib import Path
import cv2

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

def export_gates():
    sbs_dir = Path("test/side_by_side")
    sbs_dir.mkdir(parents=True, exist_ok=True)
    
    mapping = {
        "cmp_01_f0030_01.00s.png": "gate_m2_1_f30.png",
        "cmp_02_f0150_05.00s.png": "gate_m2_1_f150.png",
        "cmp_03_f0350_11.67s.png": "gate_m2_1_f350.png",
        "cmp_04_f0700_23.35s.png": "gate_m2_1_f700.png",
        "cmp_05_f0900_30.02s.png": "gate_m2_1_f900.png",
    }
    
    for src_name, dst_name in mapping.items():
        src_path = sbs_dir / src_name
        dst_path = sbs_dir / dst_name
        if src_path.exists():
            shutil.copyfile(src_path, dst_path)
            print(f"Đã sao chép {src_name} -> {dst_name}")
        else:
            print(f"Chưa thấy {src_name}, cần chạy test_verify_metrics trước.")

def export_motion_clip():
    clean_video_path = Path("test/clean_tmpy8evxmno_m2_2.mp4")
    out_motion_path = Path("test/crop_text_motion_check.mp4")
    
    if not clean_video_path.exists():
        print(f"Chưa thấy {clean_video_path}")
        return

    cap = cv2.VideoCapture(str(clean_video_path))
    if not cap.isOpened():
        print("Không mở được clean video")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 29.985
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Vùng crop header text: x=40, y=130, w=490, h=160
    hx, hy, hw, hh = 40, 130, 490, 160
    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(out_motion_path), fourcc, fps, (hw, hh))
    
    print(f"Bắt đầu xuất motion clip ({hw}x{hh}) qua {total_frames} frames...")
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        crop = frame[hy:hy+hh, hx:hx+hw]
        out.write(crop)
        count += 1
        if count % 300 == 0:
            print(f"Đã xuất {count}/{total_frames} frames motion clip...")

    cap.release()
    out.release()
    print(f"Hoàn tất xuất {out_motion_path} ({count} frames, size: {out_motion_path.stat().st_size:,} bytes)")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gates":
        export_gates()
    elif len(sys.argv) > 1 and sys.argv[1] == "motion":
        export_motion_clip()
    else:
        export_gates()
        export_motion_clip()
