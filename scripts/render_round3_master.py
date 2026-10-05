#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_round3_master.py
Studio-Grade Video Inpainting Engine for Mission Round 3 (Master Release).

Key Design:
1. Zero Local AI: 100% Hosted IOPaint LaMa REST API (https://sanster-iopaint-lama.hf.space/api/v1/inpaint).
2. Pure Temporal Consistency via Dynamic Direct Inpaint + Shot-Aware Optical Flow:
   - Truly Static Shots: Single pristine Hosted LaMa inpaint replicated across shot (0% flicker, bit-identical outside mask).
   - Dynamic Perspective & Non-Rigid Shots (Shots 3, 4, 11, 13, 14): Direct frame-by-frame Hosted LaMa inpaint (step=1).
     Eliminates ALL optical flow warping errors, perspective tearing, and door/sidewalk misalignment!
   - Smooth Moving Shots (Shots 5, 6, 7, 8, 9, 10, 12, 16, 17, 19): Keyframe inpainting + Optical Flow Farneback propagation.
   - Zero match_luminance artifacts: Removed scalar color shifts; LaMa naturally matches surrounding frame boundary.
3. Complete Subtitle Tracking (8 Subtitles):
   - All subtitle masks dilated with complete drop-shadow and stroke engulfment.
   - Dark theme IDE subtitle (Sub 6) fully covered.
4. Lossless Copied Audio (-c:a copy), H.264 CRF 18 single final encode.
"""

import os
import sys
import time
import json
import base64
import urllib.request
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np

LAMA_ENDPOINT = "https://sanster-iopaint-lama.hf.space/api/v1/inpaint"

TITLE_ROI_Y1, TITLE_ROI_Y2 = 135, 285
TITLE_ROI_X1, TITLE_ROI_X2 = 50, 525

# 19 Exact Shots Definition: (id, start_f, end_f, is_title_static, kf_step, description)
SHOTS = [
    (1,    0,  109, True,  100, "Bedroom ceiling"),
    (2,  110,  217, True,  100, "Desk monitor & paper signing"),
    (3,  218,  272, False,   1, "Holding paper document high"), # step 1: direct LaMa
    (4,  273,  462, False,   1, "Hallway walking"),             # step 1: direct LaMa
    (5,  463,  586, False,   4, "Porsche car exterior rainy street"),
    (6,  587,  618, False,   3, "Car door opening"),
    (7,  619,  712, False,   4, "Entering car seat"),
    (8,  713,  744, False,   4, "Steering wheel & taplo POV"),
    (9,  745,  804, False,   4, "Forehead talking closeup"),
    (10, 805,  977, False,   4, "Driving daytime POV"),
    (11, 978, 1093, False,   1, "Sidewalk brick pavement walking"), # step 1: direct LaMa
    (12, 1094, 1206, False,  4, "Rainy street driving POV"),
    (13, 1207, 1315, False,  1, "Breakfast sandwich walking"),      # step 1: direct LaMa
    (14, 1316, 1394, False,  1, "Restaurant dining table"),         # step 1: direct LaMa
    (15, 1395, 1455, True, 100, "Laptop IDE code screen"),
    (16, 1456, 1578, False,  4, "Laptop balcony window view"),
    (17, 1579, 1745, False,  3, "Night rain driving windshield"),
    (18, 1746, 1848, True, 100, "Night desk monitor working"),
    (19, 1849, 1944, False,  4, "Contract document with red stamp"),
]

# Exact Subtitles Definition: (id, start_f, end_f, y1, y2, x1, x2, is_static, kf_step, mask_sub_id, name)
SUBTITLES = [
    (1,   56,  109, 440, 600, 110, 460, True,  100, 1, "an_sang"),
    (2,  110,  217, 510, 640, 100, 470, True,  100, 2, "soan_hop_dong_static"),
    (22, 218,  272, 510, 640, 100, 470, False,   1, 2, "soan_hop_dong_lift"),
    (3,  273,  462, 440, 650,  90, 490, False,   1, 3, "di_gap_khach"),
    (4,  978, 1093, 470, 570,  90, 480, False,   1, 4, "mua_them_do_an"),
    (5, 1316, 1394, 450, 630,  80, 500, False,   1, 5, "tu_van_khach_xong"),
    (6, 1395, 1455, 470, 570, 100, 470, True,  100, 6, "kiem_tra_du_an"),
    (7, 1456, 1578, 460, 570,  40, 535, False,   3, 7, "tiep_tuc_di_gap_khach"),
    (8, 1579, 1745, 470, 570, 110, 440, False,   2, 8, "xong_viec_di_ve"),
]

def call_lama_inpaint(roi_bgr: np.ndarray, roi_mask_gray: np.ndarray, max_retries: int = 6) -> np.ndarray:
    """Call Hosted IOPaint LaMa REST API with exponential backoff and zero local fallback."""
    _, img_enc = cv2.imencode('.png', roi_bgr)
    _, mask_enc = cv2.imencode('.png', roi_mask_gray)
    img_b64 = 'data:image/png;base64,' + base64.b64encode(img_enc).decode()
    mask_b64 = 'data:image/png;base64,' + base64.b64encode(mask_enc).decode()
    
    payload = json.dumps({'image': img_b64, 'mask': mask_b64, 'hd_strategy': 'Original'}).encode()
    req = urllib.request.Request(
        LAMA_ENDPOINT,
        data=payload,
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                res_bytes = resp.read()
            arr = np.frombuffer(res_bytes, dtype=np.uint8)
            res_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if res_bgr is not None and res_bgr.shape == roi_bgr.shape:
                return res_bgr
        except Exception as e:
            wait_sec = 2.0 * (1.5 ** attempt)
            if attempt == max_retries - 1:
                print(f"[HostedLaMa] Attempt {attempt+1} failed: {e}. Retrying with extra wait...")
                time.sleep(5.0)
            else:
                time.sleep(wait_sec)
                
    # Final retry with clean connection
    with urllib.request.urlopen(req, timeout=50) as resp:
        res_bytes = resp.read()
    arr = np.frombuffer(res_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def warp_with_flow(clean_ref_roi: np.ndarray, ref_frame: np.ndarray, cur_frame: np.ndarray, y1: int, y2: int, x1: int, x2: int, pad: int = 15) -> np.ndarray:
    """Warp clean reference ROI to current frame using optical flow with padding."""
    h_f, w_f = ref_frame.shape[:2]
    py1 = max(0, y1 - pad)
    py2 = min(h_f, y2 + pad)
    px1 = max(0, x1 - pad)
    px2 = min(w_f, x2 + pad)
    
    g_ref = cv2.cvtColor(ref_frame[py1:py2, px1:px2], cv2.COLOR_BGR2GRAY)
    g_cur = cv2.cvtColor(cur_frame[py1:py2, px1:px2], cv2.COLOR_BGR2GRAY)
    
    flow = cv2.calcOpticalFlowFarneback(g_ref, g_cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    
    oy1 = y1 - py1
    oy2 = oy1 + (y2 - y1)
    ox1 = x1 - px1
    ox2 = ox1 + (x2 - x1)
    flow_roi = flow[oy1:oy2, ox1:ox2]
    
    rh, rw = clean_ref_roi.shape[:2]
    gy, gx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    map_x = gx - flow_roi[..., 0]
    map_y = gy - flow_roi[..., 1]
    
    return cv2.remap(clean_ref_roi, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

def get_active_subtitle_def(frame_idx: int):
    for sub in SUBTITLES:
        if sub[1] <= frame_idx <= sub[2]:
            return sub
    return None

def main():
    input_video = "test/tmpy8evxmno.mp4"
    output_dir = Path("test/round3")
    final_output = output_dir / "final_output.mp4"
    cache_dir = output_dir / "cache_master"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mask_dir = output_dir / "sub_masks"
    
    # Load dilated title mask
    title_mask = cv2.imread(str(output_dir / "hosted_inpaint_tests" / "mask_k19_dilated.png"), 0)
    alpha_title = cv2.GaussianBlur(title_mask.astype(np.float32)/255.0, (5, 5), 1.5)[:, :, None]
    
    # Load all subtitle masks and alphas
    sub_masks = {}
    sub_alphas = {}
    for sub in SUBTITLES:
        sub_id = sub[0]
        mask_file_id = sub[9]
        m_path = mask_dir / f"mask_sub_{mask_file_id:02d}.png"
        m = cv2.imread(str(m_path), 0)
        sub_masks[sub_id] = m
        sub_alphas[sub_id] = cv2.GaussianBlur(m.astype(np.float32)/255.0, (5, 5), 1.5)[:, :, None]
        
    cap = cv2.VideoCapture(input_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.98
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    print("=== MISSION ROUND 3 MASTER INPAINTING ENGINE ===")
    print(f"Input: {input_video} ({width}x{height}, {total_frames} frames, {fps:.2f} fps)")
    print(f"Output: {final_output}")
    print(f"Zero Local AI: 100% Hosted LaMa REST API at {LAMA_ENDPOINT}")
    
    # Build list of keyframes for Title per shot
    title_shot_kfs = {}
    all_title_kfs = set()
    for sid, s_start, s_end, is_static, step, _ in SHOTS:
        if is_static:
            k = (s_start + s_end) // 2
            title_shot_kfs[sid] = [k]
            all_title_kfs.add(k)
        elif step == 1:
            kfs = list(range(s_start, s_end + 1))
            title_shot_kfs[sid] = kfs
            for k in kfs:
                all_title_kfs.add(k)
        else:
            kfs = list(range(s_start, s_end + 1, step))
            if kfs[-1] != s_end:
                kfs.append(s_end)
            title_shot_kfs[sid] = kfs
            for k in kfs:
                all_title_kfs.add(k)
    sorted_title_kfs = sorted(list(all_title_kfs))
    print(f"Total Title keyframes to inpaint: {len(sorted_title_kfs)}")
    
    # Build list of keyframes for Subtitles
    sub_kfs_dict = {}
    all_sub_tasks = [] # (sub_id, frame_idx)
    for sub in SUBTITLES:
        sub_id, s_start, s_end, y1, y2, x1, x2, is_static, step, mask_file_id, name = sub
        if is_static:
            k = (s_start + s_end) // 2
            sub_kfs_dict[sub_id] = [k]
            all_sub_tasks.append((sub_id, k))
        elif step == 1:
            kfs = list(range(s_start, s_end + 1))
            sub_kfs_dict[sub_id] = kfs
            for k in kfs:
                all_sub_tasks.append((sub_id, k))
        else:
            kfs = list(range(s_start, s_end + 1, step))
            if kfs[-1] != s_end:
                kfs.append(s_end)
            sub_kfs_dict[sub_id] = kfs
            for k in kfs:
                all_sub_tasks.append((sub_id, k))
    print(f"Total Subtitle keyframe tasks to inpaint: {len(all_sub_tasks)}")
    
    # Filter tasks that are already cached
    pending_title_kfs = [k for k in sorted_title_kfs if not (cache_dir / f"title_kf_{k:04d}.png").exists()]
    pending_sub_tasks = [t for t in all_sub_tasks if not (cache_dir / f"sub_{t[0]:02d}_kf_{t[1]:04d}.png").exists()]
    print(f"Pending Title keyframes to fetch from Hosted LaMa: {len(pending_title_kfs)} (Cached: {len(sorted_title_kfs) - len(pending_title_kfs)})")
    print(f"Pending Subtitle tasks to fetch from Hosted LaMa:   {len(pending_sub_tasks)} (Cached: {len(all_sub_tasks) - len(pending_sub_tasks)})")
    
    # ─── PHASE 1: INPAINT TITLE KEYFRAMES ──────────────────────────────────────
    def process_title_kf(kidx):
        cache_file = cache_dir / f"title_kf_{kidx:04d}.png"
        if not cache_file.exists():
            c = cv2.VideoCapture(input_video)
            c.set(cv2.CAP_PROP_POS_FRAMES, kidx)
            ret, frame = c.read()
            c.release()
            if ret:
                t_roi = frame[TITLE_ROI_Y1:TITLE_ROI_Y2, TITLE_ROI_X1:TITLE_ROI_X2]
                clean = call_lama_inpaint(t_roi, title_mask)
                cv2.imwrite(str(cache_file), clean)
        return kidx
        
    if pending_title_kfs:
        print(f"\n[Phase 1] Inpainting {len(pending_title_kfs)} Title keyframes with 5 concurrent workers...")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_title_kf, k) for k in pending_title_kfs]
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if done % 25 == 0 or done == len(pending_title_kfs):
                    el = time.time() - t0
                    pct = (done / len(pending_title_kfs)) * 100.0
                    print(f"  [Title {pct:5.1f}%] {done}/{len(pending_title_kfs)} in {el:.1f}s ({el/max(1,done):.2f}s/kf)")
    else:
        print("\n[Phase 1] All Title keyframes already cached!")
                
    # ─── PHASE 2: INPAINT SUBTITLE KEYFRAMES ───────────────────────────────────
    def process_sub_kf(task):
        sub_id, kidx = task
        sub = [s for s in SUBTITLES if s[0] == sub_id][0]
        _, _, _, y1, y2, x1, x2, _, _, _, name = sub
        cache_file = cache_dir / f"sub_{sub_id:02d}_kf_{kidx:04d}.png"
        if not cache_file.exists():
            c = cv2.VideoCapture(input_video)
            c.set(cv2.CAP_PROP_POS_FRAMES, kidx)
            ret, frame = c.read()
            c.release()
            if ret:
                s_roi = frame[y1:y2, x1:x2]
                s_mask = sub_masks[sub_id]
                clean = call_lama_inpaint(s_roi, s_mask)
                cv2.imwrite(str(cache_file), clean)
        return task
        
    if pending_sub_tasks:
        print(f"\n[Phase 2] Inpainting {len(pending_sub_tasks)} Subtitle keyframes with 5 concurrent workers...")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_sub_kf, t) for t in pending_sub_tasks]
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if done % 25 == 0 or done == len(pending_sub_tasks):
                    el = time.time() - t0
                    pct = (done / len(pending_sub_tasks)) * 100.0
                    print(f"  [Subtitle {pct:5.1f}%] {done}/{len(pending_sub_tasks)} in {el:.1f}s ({el/max(1,done):.2f}s/kf)")
    else:
        print("\n[Phase 2] All Subtitle keyframes already cached!")
                
    print("\nAll Title & Subtitle keyframes 100% ready in cache!")
    
    # ─── PHASE 3: STREAMING COMPOSITING & FFMPEG ENCODE ─────────────────────────
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps:.5f}",
        "-i", "-",
        "-i", input_video,
        "-map", "0:v:0",
        "-map", "1:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-shortest",
        "-movflags", "+faststart",
        str(final_output)
    ]
    
    print("\nStarting streaming compositing & H.264 CRF 18 encoding...")
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(input_video)
    
    # Cache title keyframes in memory
    print(f"Loading {len(sorted_title_kfs)} title keyframes into memory...")
    title_cache_mem = {}
    for k in sorted_title_kfs:
        title_cache_mem[k] = cv2.imread(str(cache_dir / f"title_kf_{k:04d}.png"))
        
    # Cache sub keyframes in memory
    print(f"Loading {len(all_sub_tasks)} subtitle keyframes into memory...")
    sub_cache_mem = {}
    for sub_id, kidx in all_sub_tasks:
        sub_cache_mem[(sub_id, kidx)] = cv2.imread(str(cache_dir / f"sub_{sub_id:02d}_kf_{kidx:04d}.png"))
        
    # Pre-read keyframe original full frames for fast optical flow reference
    flow_kfs = set()
    for sid, s_start, s_end, is_static, step, _ in SHOTS:
        if not is_static and step > 1:
            flow_kfs.update(title_shot_kfs[sid])
    for sub in SUBTITLES:
        if not sub[7] and sub[8] > 1: # not is_static and step > 1
            flow_kfs.update(sub_kfs_dict[sub[0]])
            
    print(f"Pre-caching {len(flow_kfs)} optical flow reference frames in memory...")
    keyframe_orig_cache = {}
    for k in flow_kfs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ret, k_fr = cap.read()
        if ret:
            keyframe_orig_cache[k] = k_fr
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    t_start_stream = time.time()
    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break
            
        out_frame = frame.copy()
        
        # 1. Process Title
        curr_shot = [s for s in SHOTS if s[1] <= frame_idx <= s[2]][0]
        shot_id, s_start, s_end, is_title_static, step, _ = curr_shot
        
        curr_t_roi = frame[TITLE_ROI_Y1:TITLE_ROI_Y2, TITLE_ROI_X1:TITLE_ROI_X2]
        if is_title_static:
            kf = (s_start + s_end) // 2
            clean_title = title_cache_mem[kf]
        elif step == 1:
            clean_title = title_cache_mem[frame_idx]
        else:
            kfs = title_shot_kfs[shot_id]
            nearest_k = min(kfs, key=lambda k: abs(k - frame_idx))
            if nearest_k == frame_idx:
                clean_title = title_cache_mem[nearest_k]
            else:
                ref_orig = keyframe_orig_cache[nearest_k]
                clean_ref_roi = title_cache_mem[nearest_k]
                clean_title = warp_with_flow(
                    clean_ref_roi, ref_orig, frame,
                    TITLE_ROI_Y1, TITLE_ROI_Y2, TITLE_ROI_X1, TITLE_ROI_X2
                )
                
        # Composite title directly (clean LaMa boundary)
        out_frame[TITLE_ROI_Y1:TITLE_ROI_Y2, TITLE_ROI_X1:TITLE_ROI_X2] = np.clip(
            alpha_title * clean_title + (1.0 - alpha_title) * curr_t_roi, 0, 255
        ).astype(np.uint8)
        
        # 2. Process Dynamic Subtitle if active
        sub_def = get_active_subtitle_def(frame_idx)
        if sub_def is not None:
            sub_id, s_start, s_end, y1, y2, x1, x2, is_sub_static, sub_step, _, _ = sub_def
            curr_s_roi = frame[y1:y2, x1:x2]
            alpha_s = sub_alphas[sub_id]
            
            if is_sub_static:
                kf = (s_start + s_end) // 2
                clean_sub = sub_cache_mem[(sub_id, kf)]
            elif sub_step == 1:
                clean_sub = sub_cache_mem[(sub_id, frame_idx)]
            else:
                kfs = sub_kfs_dict[sub_id]
                nearest_k = min(kfs, key=lambda k: abs(k - frame_idx))
                if nearest_k == frame_idx:
                    clean_sub = sub_cache_mem[(sub_id, nearest_k)]
                else:
                    ref_orig = keyframe_orig_cache[nearest_k]
                    clean_ref_roi = sub_cache_mem[(sub_id, nearest_k)]
                    clean_sub = warp_with_flow(
                        clean_ref_roi, ref_orig, frame,
                        y1, y2, x1, x2
                    )
                    
            out_frame[y1:y2, x1:x2] = np.clip(
                alpha_s * clean_sub + (1.0 - alpha_s) * curr_s_roi, 0, 255
            ).astype(np.uint8)
            
        proc.stdin.write(out_frame.tobytes())
        
        if frame_idx % 250 == 0 or frame_idx == total_frames - 1:
            dur = time.time() - t_start_stream
            fps_proc = (frame_idx + 1) / max(0.1, dur)
            pct = ((frame_idx + 1) / total_frames) * 100.0
            print(f"[Streaming {pct:5.1f}%] Frame {frame_idx+1}/{total_frames} ({fps_proc:.1f} fps)")
            
    cap.release()
    proc.stdin.close()
    proc.wait()
    
    if final_output.exists() and final_output.stat().st_size > 1000000:
        print(f"\nSUCCESS! Rendered final clean video: {final_output} ({final_output.stat().st_size / (1024*1024):.2f} MB)")
    else:
        raise RuntimeError("FFmpeg encoding failed!")

if __name__ == "__main__":
    main()
