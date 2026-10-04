import sys, os, time, cv2, json
import numpy as np
import pytesseract

def main():
    video_path = "/tmp/cleaned_tmpy8evxmno.mp4"
    if not os.path.exists(video_path):
        print(f"Error: {video_path} does not exist!")
        sys.exit(1)
        
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.98
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    print(f"Video Info: {total_frames} frames, {width}x{height}, {fps:.2f} fps")
    
    # 1. Trích xuất 5 frame trọng điểm
    target_frames = {
        146: "test/clean_f146.png",
        1271: "test/clean_f1271.png",
        1383: "test/clean_f1383.png",
        1496: "test/clean_f1496.png",
        1608: "test/clean_f1608.png"
    }
    
    ocr_results = {}
    
    for f_idx, out_name in target_frames.items():
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(f_idx, total_frames - 1))
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"Error reading frame {f_idx}")
            continue
            
        out_path = os.path.join("/home/kirito/quan_ly_server", out_name)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cv2.imwrite(out_path, frame)
        
        # OCR Full frame
        txt_full = pytesseract.image_to_string(frame, lang='vie+eng').strip()
        # OCR Subtitle ROI (nửa dưới)
        sub_roi = frame[int(height*0.5):, :]
        txt_sub = pytesseract.image_to_string(sub_roi, lang='vie+eng').strip()
        # OCR Title ROI (y: 19..295)
        title_roi = frame[19:min(295, height), :]
        txt_title = pytesseract.image_to_string(title_roi, lang='vie+eng').strip()
        
        ocr_results[f"frame_{f_idx}"] = {
            "file": out_name,
            "ocr_full": txt_full,
            "ocr_sub": txt_sub,
            "ocr_title": txt_title
        }
        print(f"Frame {f_idx} OCR: full='{txt_full}' | sub='{txt_sub}' | title='{txt_title}'")
        
    cap.release()
    
    metrics_path = "/home/kirito/quan_ly_server/test/it5_ocr_verification.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(ocr_results, f, ensure_ascii=False, indent=2)
    print(f"OCR verification saved to {metrics_path}")

if __name__ == "__main__":
    main()
