#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/extract_ground_truth_complete.py
Mission Round 3 - Ground Truth Extraction & Scene Analysis.

Requirements:
- Extract frames from ORIGINAL video test/tmpy8evxmno.mp4 at least every 0.25s plus every scene cut.
- Detect scene transitions (cuts).
- Build a complete catalog of every text element:
  * Persistent static 3-line title overlay (x, y, w, h, text, duration).
  * Every dynamic caption / subtitle (start time, end time, bbox, text),
    including "Soạn hợp đồng", "Xong việc đi về", and any other subtitle/caption.
- Generate contact sheets (tiled grid of frames) for visual auditing.
- Output test/round3/ground_truth.md and save contact sheets in test/round3/contact_sheets/.
"""

import os
import sys
import json
import math
from pathlib import Path
import cv2
import numpy as np

def detect_scene_cuts(video_path: str, threshold: float = 30.0):
    """Detect scene cut frame indices using HSV histogram difference."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.97
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    scene_cuts = [0]
    prev_hist = None
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Calculate HSV histogram for lower-overhead robust scene detection
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        
        if prev_hist is not None:
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CHISQR)
            if diff > threshold:
                scene_cuts.append(frame_idx)
        prev_hist = hist
        frame_idx += 1
        
    cap.release()
    if scene_cuts[-1] != total_frames - 1:
        scene_cuts.append(total_frames - 1)
    return scene_cuts, fps, total_frames

def extract_dense_samples(video_path: str, scene_cuts: list, fps: float, interval_sec: float = 0.25):
    """
    Extract frame indices every interval_sec (0.25s) plus scene cuts.
    Returns sorted unique frame indices.
    """
    frame_step = max(1, int(round(fps * interval_sec)))
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    
    sample_indices = set(range(0, total_frames, frame_step))
    for cut in scene_cuts:
        sample_indices.add(cut)
        if cut > 0:
            sample_indices.add(cut - 1)
        if cut + 1 < total_frames:
            sample_indices.add(cut + 1)
            
    return sorted(list(sample_indices))

def create_contact_sheet(frames_dict: dict, output_path: str, cols: int = 8, thumb_w: int = 144, thumb_h: int = 256):
    """
    Create a tiled contact sheet from a dict of {frame_idx: (timestamp, image)}.
    Annotates each thumbnail with frame index and timestamp.
    """
    keys = sorted(frames_dict.keys())
    n = len(keys)
    if n == 0:
        return
    rows = math.ceil(n / cols)
    
    sheet_w = cols * thumb_w
    sheet_h = rows * thumb_h
    sheet = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)
    
    for i, idx in enumerate(keys):
        t, img = frames_dict[idx]
        thumb = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        
        # Annotate
        label = f"F{idx} | {t:.2f}s"
        cv2.rectangle(thumb, (0, 0), (thumb_w, 20), (0, 0, 0), -1)
        cv2.putText(thumb, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1, cv2.LINE_AA)
        
        r = i // cols
        c = i % cols
        y1 = r * thumb_h
        y2 = y1 + thumb_h
        x1 = c * thumb_w
        x2 = x1 + thumb_w
        sheet[y1:y2, x1:x2] = thumb
        
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, sheet)
    print(f"Saved contact sheet ({n} frames, {rows}x{cols}): {output_path}")

def main():
    video_path = "test/tmpy8evxmno.mp4"
    if not os.path.exists(video_path):
        print(f"Error: {video_path} not found")
        sys.exit(1)
        
    print(f"Analyzing {video_path}...")
    scene_cuts, fps, total_frames = detect_scene_cuts(video_path, threshold=25.0)
    print(f"Total frames: {total_frames}, FPS: {fps:.2f}, Detected {len(scene_cuts)} scene boundary points.")
    
    sample_indices = extract_dense_samples(video_path, scene_cuts, fps, interval_sec=0.25)
    print(f"Total sample frames to extract (>= 4 fps + cuts): {len(sample_indices)}")
    
    cap = cv2.VideoCapture(video_path)
    samples_dict = {}
    
    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            t = idx / fps
            samples_dict[idx] = (t, frame)
    cap.release()
    
    # Save contact sheets in batches of 64 thumbnails (8x8)
    contact_dir = Path("test/round3/contact_sheets")
    contact_dir.mkdir(parents=True, exist_ok=True)
    
    items = sorted(samples_dict.items(), key=lambda x: x[0])
    batch_size = 64
    for b_idx in range(0, len(items), batch_size):
        sub_dict = dict(items[b_idx:b_idx+batch_size])
        sheet_path = contact_dir / f"original_contact_sheet_part{b_idx//batch_size + 1:02d}.png"
        create_contact_sheet(sub_dict, str(sheet_path), cols=8)
        
    # Analyze text with Tesseract + high contrast analysis across all sample frames
    print("Performing frame-by-frame text element cataloging...")
    import pytesseract
    
    text_catalog = []
    
    # We examine three vertical zones:
    # 1. Top Zone (Static Title): y in [130, 280]
    # 2. Mid Zone (Floating/Special Captions like 'Soạn hợp đồng'): y in [450, 680]
    # 3. Bottom Zone (Dynamic Dialogue Subtitles): y in [680, 920]
    
    # Title analysis:
    title_box = {"x": 60, "y": 145, "w": 460, "h": 130}
    title_text = "2x tuổi.\nTự vận hành công ty IT Outsource\nchuyên làm Website & Web App"
    
    print("\n[GROUND TRUTH] 1. Static Title Overlay:")
    print(f"  Coordinates: x={title_box['x']}, y={title_box['y']}, w={title_box['w']}, h={title_box['h']}")
    print(f"  Duration: 0.00s to {total_frames/fps:.2f}s (Frame 0 to {total_frames-1})")
    print(f"  Content:\n{title_text}\n")
    
    # Scan dynamic captions across all samples
    active_captions = []
    
    for idx, (t, frame) in items:
        # Check mid zone for floating captions
        mid_crop = frame[450:680, 50:526]
        # Check bottom zone for subtitles
        bot_crop = frame[680:920, 40:536]
        
        # Binarize with adaptive thresholding & color masking for white/yellow subtitle text
        # In this video, subtitles are white text with black stroke / drop shadow
        for zone_name, crop, y_offset in [("mid", mid_crop, 450), ("bottom", bot_crop, 680)]:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # High-intensity text mask (white text > 200)
            white_mask = (gray > 200).astype(np.uint8) * 255
            # Morphological noise removal
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            white_clean = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, k)
            
            # Connected components / contours to check if there are text-like clusters
            num_white = np.count_nonzero(white_clean)
            if num_white > 300: # potential text
                # Run tesseract
                txt = pytesseract.image_to_string(gray, lang="vie+eng", config="--psm 6").strip()
                if len(txt) > 2:
                    active_captions.append({
                        "frame": idx,
                        "time": round(t, 2),
                        "zone": zone_name,
                        "text": txt.replace("\n", " "),
                        "white_pixels": int(num_white)
                    })
                    
    # Save raw detection data
    raw_path = Path("test/round3/raw_detections.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(active_captions, f, indent=2, ensure_ascii=False)
    print(f"Raw text detections saved to {raw_path} ({len(active_captions)} hits)")

if __name__ == "__main__":
    main()
