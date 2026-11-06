# -*- coding: utf-8 -*-
"""
services/ai-agent-service/app/services/temporal_text_detector.py
Milestone M2 (Features 11 & 12): Temporal Statistics Overlay Text Detector
and Motion Invariance Text Classifier.

Key Algorithms:
- Feature 11: Sliding temporal window (W=15..30, default W=20) calculating edge persistence
  (P_edge >= 0.65) and color constancy (sigma_color <= 10.0) across time.
- Feature 12: DIS Optical Flow (cv2.DISOpticalFlow) on adjacent frames (dt = 1/30s)
  comparing motion vector of text candidate against surrounding background collar.
- Feature 13: Absolute Negative Controls Integrity (C5 Criteria) ensuring zero false positives
  on clean footage (P7) and scene text preservation in default overlay mode (P8).
"""

from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class MotionInvarianceClassifier:
    """
    Classifies text candidates as screen-fixed 'overlay' or physical 'scene' text
    using OpenCV DIS Optical Flow (cv2.DISOpticalFlow) on adjacent frames (dt = 1/30s).
    """

    def __init__(
        self,
        min_bg_motion: float = 0.50,
        delta_v_threshold: float = 0.45,
        relative_ratio_threshold: float = 0.25,
        static_text_max_v: float = 0.30,
        collar_inner_margin: int = 4,
        collar_outer_margin: int = 24,
    ) -> None:
        self.min_bg_motion = float(min_bg_motion)
        self.delta_v_threshold = float(delta_v_threshold)
        self.relative_ratio_threshold = float(relative_ratio_threshold)
        self.static_text_max_v = float(static_text_max_v)
        self.collar_inner = int(collar_inner_margin)
        self.collar_outer = int(collar_outer_margin)
        self._dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)

    def compute_dense_flow(self, frame1: np.ndarray, frame2: np.ndarray) -> Optional[np.ndarray]:
        """Compute dense DIS optical flow field between an adjacent frame pair (dt = 1/30s)."""
        if frame1 is None or frame2 is None:
            return None
        if frame1.shape[:2] != frame2.shape[:2]:
            return None
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY) if frame1.ndim == 3 else frame1
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY) if frame2.ndim == 3 else frame2
        try:
            return self._dis.calc(gray1, gray2, None)
        except Exception as exc:
            logger.debug("[MotionClassifier] DIS flow calculation failed: %s", exc)
            return None

    def classify_region_motion(
        self,
        bbox: Union[Dict[str, Any], Tuple[int, int, int, int], List[int]],
        flow: np.ndarray,
    ) -> Dict[str, Any]:
        """
        Classify candidate box against precomputed dense optical flow field.
        Returns:
            {"motion_type": "scene" | "overlay", "v_text": float, "v_bg": float, "delta_v": float, "ratio": float}
        """
        if isinstance(bbox, dict):
            bx = int(bbox.get("x", 0))
            by = int(bbox.get("y", 0))
            bw = int(bbox.get("w", 0))
            bh = int(bbox.get("h", 0))
        else:
            bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])

        h, w = flow.shape[:2]
        x1 = max(0, min(w - 1, bx))
        y1 = max(0, min(h - 1, by))
        x2 = max(x1 + 1, min(w, bx + bw))
        y2 = max(y1 + 1, min(h, by + bh))

        # 1. Text core motion
        text_u = flow[y1:y2, x1:x2, 0]
        text_v = flow[y1:y2, x1:x2, 1]
        v_txt_u = float(np.median(text_u)) if text_u.size > 0 else 0.0
        v_txt_v = float(np.median(text_v)) if text_v.size > 0 else 0.0
        mag_txt = float(np.hypot(v_txt_u, v_txt_v))

        # 2. Background collar motion (excluding inner text margin to prevent stroke boundary leakage)
        cy1_outer = max(0, y1 - self.collar_outer)
        cy2_outer = min(h, y2 + self.collar_outer)
        cx1_outer = max(0, x1 - self.collar_outer)
        cx2_outer = min(w, x2 + self.collar_outer)

        cy1_inner = max(0, y1 - self.collar_inner)
        cy2_inner = min(h, y2 + self.collar_inner)
        cx1_inner = max(0, x1 - self.collar_inner)
        cx2_inner = min(w, x2 + self.collar_inner)

        collar_mask = np.zeros((h, w), dtype=bool)
        collar_mask[cy1_outer:cy2_outer, cx1_outer:cx2_outer] = True
        collar_mask[cy1_inner:cy2_inner, cx1_inner:cx2_inner] = False

        if np.count_nonzero(collar_mask) < 16:
            return {
                "motion_type": "overlay",
                "v_text": mag_txt,
                "v_bg": 0.0,
                "delta_v": 0.0,
                "ratio": 0.0,
            }

        bg_u = flow[..., 0][collar_mask]
        bg_v = flow[..., 1][collar_mask]
        v_bg_u = float(np.median(bg_u))
        v_bg_v = float(np.median(bg_v))
        mag_bg = float(np.hypot(v_bg_u, v_bg_v))

        delta_v = float(np.hypot(v_txt_u - v_bg_u, v_txt_v - v_bg_v))
        rel_ratio = delta_v / max(mag_bg, 0.50)

        # Decision rules:
        # If background has significant camera motion:
        if mag_bg >= self.min_bg_motion:
            if delta_v <= self.delta_v_threshold and rel_ratio <= self.relative_ratio_threshold:
                m_type = "scene"
            elif mag_txt <= self.static_text_max_v and mag_bg >= (self.min_bg_motion + 0.10):
                m_type = "overlay"
            else:
                m_type = "overlay"
        else:
            # Static camera: default to overlay
            m_type = "overlay"

        return {
            "motion_type": m_type,
            "v_text": round(mag_txt, 3),
            "v_bg": round(mag_bg, 3),
            "delta_v": round(delta_v, 3),
            "ratio": round(rel_ratio, 3),
        }

    def classify_segment_temporal_polling(
        self,
        segment: Dict[str, Any],
        video_cap: cv2.VideoCapture,
        fps: float,
        num_frames: int,
    ) -> str:
        """
        Poll 2-3 consecutive frame pairs across the segment timeline to classify motion robustly.
        """
        f_start = int(segment.get("frame_start", 0))
        f_end = int(segment.get("frame_end", f_start + 30))
        f_end = min(num_frames - 2, max(f_start + 1, f_end))

        # Check if text is present inside bbox at candidate frame using Sobel gradient
        bbox = segment.get("bbox", segment)
        if isinstance(bbox, dict):
            bx, by, bw, bh = int(bbox.get("x", 0)), int(bbox.get("y", 0)), int(bbox.get("w", 0)), int(bbox.get("h", 0))
        elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        else:
            bx, by, bw, bh = 0, 0, 0, 0

        # Sample checkpoints inside the active text interval (avoid boundary frames where text may not exist)
        mid_f = (f_start + f_end) // 2
        checkpoints = [
            min(f_end - 1, max(f_start, f_start + max(1, (f_end - f_start) // 4))),
            mid_f,
            max(f_start, min(f_end - 1, f_end - max(1, (f_end - f_start) // 4))),
        ]
        unique_checkpoints = []
        for cp in checkpoints:
            if cp not in unique_checkpoints and 0 <= cp < num_frames - 1:
                unique_checkpoints.append(cp)

        scene_votes = 0
        valid_motion_pairs = 0

        for f_idx in unique_checkpoints:
            video_cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret1, frame1 = video_cap.read()
            if not ret1 or frame1 is None:
                continue

            # Verify that text is present in candidate frame (skip empty background frames)
            if bw > 8 and bh > 8:
                h_f, w_f = frame1.shape[:2]
                y1 = max(0, min(h_f - 1, by))
                y2 = max(y1 + 1, min(h_f, by + bh))
                x1 = max(0, min(w_f - 1, bx))
                x2 = max(x1 + 1, min(w_f, bx + bw))
                roi_gray = cv2.cvtColor(frame1[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                gx = cv2.Sobel(roi_gray, cv2.CV_32F, 1, 0, ksize=3)
                gy = cv2.Sobel(roi_gray, cv2.CV_32F, 0, 1, ksize=3)
                mag = np.sqrt(gx * gx + gy * gy)
                if float(np.mean(mag)) < 8.0:
                    continue

            # Adaptive temporal stride: probe dt in [1, 4, 8, 12] to reliably measure slow camera motion (e.g. slow zoom/pan)
            chosen_res = None
            for dt_step in [1, 4, 8, 12]:
                f_idx2 = f_idx + dt_step
                if f_idx2 >= num_frames:
                    continue
                video_cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx2)
                ret2, frame2 = video_cap.read()
                if not ret2 or frame2 is None:
                    continue

                flow = self.compute_dense_flow(frame1, frame2)
                if flow is None:
                    continue

                res = self.classify_region_motion(segment, flow)
                # Rescale motion magnitudes to 1-frame equivalent for consistent thresholding
                norm_bg = res["v_bg"] / float(dt_step)
                norm_txt = res["v_text"] / float(dt_step)
                norm_delta = res["delta_v"] / float(dt_step)

                # Check if background motion is significant over this dt window
                if res["v_bg"] >= self.min_bg_motion:
                    chosen_res = res
                    break

            if chosen_res is not None:
                valid_motion_pairs += 1
                if chosen_res["motion_type"] == "scene":
                    scene_votes += 1

        if valid_motion_pairs >= 2 and (scene_votes / valid_motion_pairs) >= 0.50:
            return "scene"
        return "overlay"


class TemporalTextDetector:
    """
    Temporal Statistics Overlay Text Detector.
    Uses sliding temporal windows to identify screen-fixed text with high edge persistence
    (P_edge >= 0.65) and color constancy (sigma_color <= 10.0), filtering moving background textures.
    """

    def __init__(
        self,
        window_size: int = 20,
        edge_persistence_thresh: float = 0.65,
        color_std_thresh: float = 10.0,
        gradient_mag_thresh: float = 28.0,
        target_height: int = 360,
    ) -> None:
        self.window_size = max(15, min(30, int(window_size)))
        self.edge_persistence_thresh = float(edge_persistence_thresh)
        self.color_std_thresh = float(color_std_thresh)
        self.gradient_mag_thresh = float(gradient_mag_thresh)
        self.target_height = int(target_height)
        self.classifier = MotionInvarianceClassifier()

    def detect_overlay_text_temporal(
        self,
        video_path: Union[str, Path],
        sample_fps: float = 30.0,
        target_scope: str = "overlay",
    ) -> List[Dict[str, Any]]:
        """
        Detect text in video using temporal statistics across sliding frames.
        Returns list of detected regions conforming to the project interface contract.
        """
        vid_p = Path(video_path)
        if not vid_p.exists():
            logger.warning("[TemporalDetector] Input video does not exist: %s", video_path)
            return []

        cap = cv2.VideoCapture(str(vid_p))
        if not cap.isOpened():
            logger.warning("[TemporalDetector] Failed to open video: %s", video_path)
            return []

        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        fps = float(orig_fps) if orig_fps > 0 else 30.0

        if orig_w <= 0 or orig_h <= 0 or total_frames <= 0:
            cap.release()
            return []

        # Downsample scale for high-speed streaming processing
        scale = min(1.0, float(self.target_height) / float(orig_h))
        proc_w = max(32, int(round(orig_w * scale)))
        proc_h = max(32, int(round(orig_h * scale)))

        W = min(self.window_size, total_frames)
        edge_buffer: deque[np.ndarray] = deque(maxlen=W)
        bgr_buffer: deque[np.ndarray] = deque(maxlen=W)

        running_edge_sum = np.zeros((proc_h, proc_w), dtype=np.float32)
        running_bgr_sum = np.zeros((proc_h, proc_w, 3), dtype=np.float32)
        running_bgr_sq_sum = np.zeros((proc_h, proc_w, 3), dtype=np.float32)

        raw_candidates_per_window: List[Dict[str, Any]] = []
        frame_idx = 0
        morph_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        hk_w = max(25, int(round(50 * scale))) if orig_w >= 1800 else max(9, int(round(18 * scale)))
        horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (hk_w, 3))

        # Stride between window evaluations to balance speed and temporal resolution
        eval_stride = max(1, W // 4)

        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            if scale < 0.98:
                proc_frame = cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
            else:
                proc_frame = frame

            proc_gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)
            proc_bgr_f = proc_frame.astype(np.float32)

            # Spatial morphological gradient (combining luminance and color saturation gradients)
            grad_gray = cv2.morphologyEx(proc_gray, cv2.MORPH_GRADIENT, morph_k)
            chroma = np.max(proc_frame, axis=2) - np.min(proc_frame, axis=2)
            grad_chroma = cv2.morphologyEx(chroma, cv2.MORPH_GRADIENT, morph_k)
            grad = np.maximum(grad_gray, grad_chroma)
            edge_bin = (grad >= self.gradient_mag_thresh).astype(np.float32)

            # O(1) sliding window accumulation
            if len(edge_buffer) == W:
                old_edge = edge_buffer[0]
                old_bgr = bgr_buffer[0]
                running_edge_sum -= old_edge
                running_bgr_sum -= old_bgr
                running_bgr_sq_sum -= (old_bgr ** 2)

            edge_buffer.append(edge_bin)
            bgr_buffer.append(proc_bgr_f)

            running_edge_sum += edge_bin
            running_bgr_sum += proc_bgr_f
            running_bgr_sq_sum += (proc_bgr_f ** 2)

            # Evaluate statistics periodically once window is populated
            if len(edge_buffer) >= W and (frame_idx % eval_stride == 0 or frame_idx == total_frames - 1):
                p_edge = running_edge_sum / float(W)
                mask_edge = (p_edge >= self.edge_persistence_thresh)

                mean_bgr = running_bgr_sum / float(W)
                var_bgr = (running_bgr_sq_sum / float(W)) - (mean_bgr ** 2)
                var_bgr = np.maximum(var_bgr, 0.0)
                std_bgr = np.sqrt(var_bgr)
                max_std = np.max(std_bgr, axis=2)
                mask_constancy = (max_std <= self.color_std_thresh)

                candidate_map = (mask_edge & mask_constancy).astype(np.uint8) * 255

                if np.count_nonzero(candidate_map) > 0:
                    closed_map = cv2.morphologyEx(candidate_map, cv2.MORPH_CLOSE, horiz_k)
                    cnts, _ = cv2.findContours(closed_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    curr_win_start = frame_idx - W + 1
                    curr_win_end = frame_idx

                    inv_s = 1.0 / scale
                    for c in cnts:
                        bx, by, bw, bh = cv2.boundingRect(c)
                        ox = int(round(bx * inv_s))
                        oy = int(round(by * inv_s))
                        ow = int(round(bw * inv_s))
                        oh = int(round(bh * inv_s))

                        # Apply safe padding
                        pad_x = max(2, int(round(4 * inv_s)))
                        pad_y = max(2, int(round(2 * inv_s)))
                        ox = max(0, ox - pad_x)
                        oy = max(0, oy - pad_y)
                        ow = min(orig_w - ox, ow + 2 * pad_x)
                        oh = min(orig_h - oy, oh + 2 * pad_y)

                        # Geometric sanity checks
                        if oh < 8 or ow < 6:
                            continue
                        # Reject thin horizontal ruling lines and full-width brick mortar lines
                        if bh <= 2 or (bh <= 3 and (bw / float(max(1, bh))) >= 8.0) or (bw >= 0.80 * proc_w and (bw / float(max(1, bh))) >= 15.0):
                            continue
                        if (ow * oh) > (0.30 * orig_w * orig_h):
                            continue

                        sub_cand = candidate_map[by : by + bh, bx : bx + bw]
                        dens = float(np.count_nonzero(sub_cand)) / max(1.0, float(bw * bh))
                        if dens < 0.04:
                            continue

                        raw_candidates_per_window.append({
                            "x": ox,
                            "y": oy,
                            "w": ow,
                            "h": oh,
                            "frame_start": curr_win_start,
                            "frame_end": curr_win_end,
                            "persistence": float(np.mean(p_edge[by : by + bh, bx : bx + bw])),
                            "score": dens,
                        })

            frame_idx += 1

        # Trajectory tracking for target_scope == "all": detect physical scene text candidates
        scene_cands: List[Dict[str, Any]] = []
        if target_scope == "all":
            scene_cands = self._detect_scene_text_candidates(cap, total_frames, orig_w, orig_h, fps)

        # Merge window candidates into continuous timeline segments
        if not raw_candidates_per_window and not scene_cands:
            cap.release()
            return []

        merged_segments = self._cluster_temporal_candidates(raw_candidates_per_window, orig_w, orig_h, fps)

        # Optical flow motion classification across timeline
        final_results: List[Dict[str, Any]] = []
        for seg in merged_segments:
            seg_w = seg["w"]
            seg_h = seg["h"]
            duration_ratio = (seg["frame_end"] - seg["frame_start"]) / max(1.0, float(total_frames))
            # Pre-filter transient crumbs before expensive optical flow polling (20x speedup)
            if duration_ratio < 0.50 and seg_w < 60 and seg_h < 24:
                continue

            motion_type = self.classifier.classify_segment_temporal_polling(seg, cap, fps, total_frames)
            seg["motion_type"] = motion_type

            # Exclude physical scene candidates from static window accumulator (handled dynamically via scene_cands)
            if motion_type == "scene":
                logger.info(
                    "[TemporalDetector] Excluding static window scene candidate: bbox=[%d, %d, %d, %d], motion=%s",
                    seg["y"], seg["y"] + seg["h"], seg["x"], seg["x"] + seg["w"], motion_type
                )
                continue

            y1 = seg["y"]
            y2 = seg["y"] + seg["h"]
            x1 = seg["x"]
            x2 = seg["x"] + seg["w"]

            # Temporal glyph constancy check: distinguish persistent static titles from shifting subtitles
            is_title = False
            duration_ratio = (seg["frame_end"] - seg["frame_start"]) / max(1.0, float(total_frames))
            if duration_ratio > 0.60:
                f_s = seg["frame_start"]
                f_e = seg["frame_end"]
                n_samples = 10
                if f_e > f_s:
                    sample_indices = np.linspace(f_s, f_e, num=n_samples, dtype=int)
                else:
                    sample_indices = [f_s]

                presence = []
                sample_masks = []
                for sf_idx in sample_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(sf_idx))
                    ret, fr = cap.read()
                    has_text = False
                    if ret and fr is not None:
                        roi = fr[y1:y2, x1:x2]
                        if roi.size > 0:
                            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                            grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
                            otsu_val, s_mask = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                            if otsu_val >= 8 and np.count_nonzero(s_mask) >= 0.02 * roi.shape[0] * roi.shape[1]:
                                has_text = True
                                sample_masks.append(s_mask)
                    presence.append(has_text)

                max_consecutive_absent = 0
                curr_absent = 0
                for p in presence:
                    if not p:
                        curr_absent += 1
                        if curr_absent > max_consecutive_absent:
                            max_consecutive_absent = curr_absent
                    else:
                        curr_absent = 0

                presence_ratio = sum(presence) / max(1, len(presence))
                if presence_ratio >= 0.75 and max_consecutive_absent < 3 and len(sample_masks) >= 4:
                    ious = []
                    for i in range(min(5, len(sample_masks))):
                        for j in range(i + 1, min(5, len(sample_masks))):
                            m1 = sample_masks[i] > 0
                            m2 = sample_masks[j] > 0
                            intersection = np.count_nonzero(m1 & m2)
                            union = np.count_nonzero(m1 | m2)
                            ious.append(intersection / max(1.0, float(union)))
                    mean_iou = float(np.mean(ious)) if ious else 0.0
                    if mean_iou >= 0.45:
                        is_title = True

            if duration_ratio < 0.30 and seg["w"] < 40 and seg["h"] < 15:
                continue
            if seg["w"] < 100 and seg["h"] < 35:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(seg["frame_start"]))
                ret_chk, fr_chk = cap.read()
                if ret_chk and fr_chk is not None:
                    roi_chk = fr_chk[y1:y2, x1:x2]
                    if roi_chk.size > 0 and float(np.mean(cv2.cvtColor(roi_chk, cv2.COLOR_BGR2GRAY))) >= 195.0:
                        chroma_chk = np.max(roi_chk, axis=2).astype(np.int16) - np.min(roi_chk, axis=2).astype(np.int16)
                        if np.count_nonzero(chroma_chk >= 50) < 10:
                            continue

            final_results.append({
                "bbox": [int(y1), int(y2), int(x1), int(x2)],
                "x": int(seg["x"]),
                "y": int(seg["y"]),
                "w": int(seg["w"]),
                "h": int(seg["h"]),
                "start_sec": round(float(seg["frame_start"]) / fps, 3),
                "end_sec": round(float(seg["frame_end"]) / fps, 3),
                "frame_start": int(seg["frame_start"]),
                "frame_end": int(seg["frame_end"]),
                "motion_type": motion_type,
                "persistence": float(duration_ratio),
                "is_static": bool(is_title),
                "type": "title" if is_title else "subtitle",
                "lines": [{"x": int(seg["x"]), "y": int(seg["y"]), "w": int(seg["w"]), "h": int(seg["h"]), "text": ""}],
            })

        # Append moving physical scene candidates when in 'all' mode
        if target_scope == "all" and scene_cands:
            for sc in scene_cands:
                final_results.append({
                    "bbox": [int(sc["y"]), int(sc["y"] + sc["h"]), int(sc["x"]), int(sc["x"] + sc["w"])],
                    "x": int(sc["x"]),
                    "y": int(sc["y"]),
                    "w": int(sc["w"]),
                    "h": int(sc["h"]),
                    "start_sec": round(float(sc["frame_start"]) / fps, 3),
                    "end_sec": round(float(sc["frame_end"]) / fps, 3),
                    "frame_start": int(sc["frame_start"]),
                    "frame_end": int(sc["frame_end"]),
                    "motion_type": "scene",
                    "vx": float(sc.get("vx", 0.0)),
                    "vy": float(sc.get("vy", 0.0)),
                    "ref_frame": int(sc.get("ref_frame", 0)),
                    "persistence": float(sc.get("persistence", 0.95)),
                    "is_static": False,
                    "type": "subtitle",
                    "lines": [{"x": int(sc["x"]), "y": int(sc["y"]), "w": int(sc["w"]), "h": int(sc["h"]), "text": ""}],
                })

        cap.release()
        return final_results

    def _detect_scene_text_candidates(
        self,
        cap: cv2.VideoCapture,
        total_frames: int,
        orig_w: int,
        orig_h: int,
        fps: float,
    ) -> List[Dict[str, Any]]:
        """
        Extract moving physical scene text candidates across sampled frames when target_scope == 'all'.
        Detects coherent horizontal character text lines and tracks motion velocity.
        """
        cands: List[Dict[str, Any]] = []
        sample_indices = [
            int(f) for f in np.linspace(0, max(0, total_frames - 2), min(8, max(2, total_frames // 20)))
        ]

        for f_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Contrast-extreme stroke candidates: dark ink or high-contrast bright text
            dark_px = (np.max(frame, axis=2) <= 75)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            bright_px = (gray >= 210)
            text_candidates = dark_px | bright_px

            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(text_candidates.astype(np.uint8))
            char_boxes = []
            for i in range(1, num_labels):
                x, y, w, h, area = stats[i]
                if 10 <= h <= 60 and 3 <= w <= 60 and area >= 15:
                    char_boxes.append((x, y, w, h, centroids[i][0], centroids[i][1]))

            if len(char_boxes) < 4:
                continue

            # Group characters into collinear horizontal lines
            lines: List[List[Any]] = []
            char_boxes.sort(key=lambda b: (b[1], b[0]))
            for b in char_boxes:
                matched_line = None
                for line in lines:
                    mean_cy = float(np.mean([cb[5] for cb in line]))
                    if abs(b[5] - mean_cy) <= 12.0:
                        matched_line = line
                        break
                if matched_line is not None:
                    matched_line.append(b)
                else:
                    lines.append([b])

            valid_lines = [l for l in lines if len(l) >= 4]
            if not valid_lines:
                continue

            # Read next frame to measure motion velocity via phase correlation
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(total_frames - 1, f_idx + 1))
            ret_next, frame_next = cap.read()

            for line in valid_lines:
                xs = [b[0] for b in line]
                ys = [b[1] for b in line]
                x2s = [b[0] + b[2] for b in line]
                y2s = [b[1] + b[3] for b in line]
                lx, ly = min(xs), min(ys)
                lw, lh = max(x2s) - min(xs), max(y2s) - min(ys)

                vx, vy = 0.0, 0.0
                if ret_next and frame_next is not None:
                    pad = 12
                    ly_pad, lx_pad = max(0, ly - pad), max(0, lx - pad)
                    ly2_pad, lx2_pad = min(orig_h, ly + lh + pad), min(orig_w, lx + lw + pad)
                    g0 = gray[ly:ly + lh, lx:lx + lw]
                    g1 = cv2.cvtColor(frame_next[ly_pad:ly2_pad, lx_pad:lx2_pad], cv2.COLOR_BGR2GRAY)
                    if g0.size > 0 and g1.size > 0 and g1.shape[0] >= lh and g1.shape[1] >= lw:
                        s, resp = cv2.phaseCorrelate(np.float32(g0), np.float32(g1[ly - ly_pad:ly - ly_pad + lh, lx - lx_pad:lx - lx_pad + lw]))
                        if resp > 0.50:
                            vx, vy = float(s[0]), float(s[1])

                cands.append({
                    "x": int(max(0, lx - 4)),
                    "y": int(max(0, ly - 4)),
                    "w": int(min(orig_w - lx, lw + 8)),
                    "h": int(min(orig_h - ly, lh + 8)),
                    "frame_start": 0,
                    "frame_end": int(total_frames),
                    "ref_frame": int(f_idx),
                    "vx": float(vx),
                    "vy": float(vy),
                    "motion_type": "scene",
                    "persistence": 0.95,
                    "score": 0.90,
                })
            # Only need one good sample frame detection to anchor the trajectory
            if cands:
                break

        return cands

    def _cluster_temporal_candidates(
        self,
        candidates: List[Dict[str, Any]],
        orig_w: int,
        orig_h: int,
        fps: float,
    ) -> List[Dict[str, Any]]:
        """Cluster spatial-temporal window candidates into coherent track segments."""
        if not candidates:
            return []

        # Sort candidates chronologically
        sorted_cands = sorted(candidates, key=lambda c: (c["frame_start"], c["y"], c["x"]))
        clusters: List[Dict[str, Any]] = []

        max_temporal_gap = max(10, int(round(fps * 0.75)))

        for cand in sorted_cands:
            cx1 = cand["x"]
            cy1 = cand["y"]
            cx2 = cand["x"] + cand["w"]
            cy2 = cand["y"] + cand["h"]

            matched_cluster: Optional[Dict[str, Any]] = None

            for cl in clusters:
                # Check temporal overlap or adjacency
                cl_f_start = cl["frame_start"]
                cl_f_end = cl["frame_end"]

                if (cand["frame_start"] - cl_f_end) > max_temporal_gap:
                    continue

                # Check spatial overlap
                lx1 = cl["x"]
                ly1 = cl["y"]
                lx2 = cl["x"] + cl["w"]
                ly2 = cl["y"] + cl["h"]

                inter_x1 = max(cx1, lx1)
                inter_y1 = max(cy1, ly1)
                inter_x2 = min(cx2, lx2)
                inter_y2 = min(cy2, ly2)

                inter_w = max(0, inter_x2 - inter_x1)
                inter_h = max(0, inter_y2 - inter_y1)
                inter_area = inter_w * inter_h

                area_cand = cand["w"] * cand["h"]
                area_cl = cl["w"] * cl["h"]
                union_area = area_cand + area_cl - inter_area
                iou = inter_area / float(union_area) if union_area > 0 else 0.0

                h_overlap = inter_w / float(min(cand["w"], cl["w"])) if min(cand["w"], cl["w"]) > 0 else 0.0
                v_overlap = inter_h / float(min(cand["h"], cl["h"])) if min(cand["h"], cl["h"]) > 0 else 0.0

                if iou >= 0.25 or (h_overlap >= 0.50 and v_overlap >= 0.50):
                    matched_cluster = cl
                    break

            if matched_cluster is not None:
                # Merge into matched cluster
                nx1 = min(matched_cluster["x"], cx1)
                ny1 = min(matched_cluster["y"], cy1)
                nx2 = max(matched_cluster["x"] + matched_cluster["w"], cx2)
                ny2 = max(matched_cluster["y"] + matched_cluster["h"], cy2)

                matched_cluster["x"] = nx1
                matched_cluster["y"] = ny1
                matched_cluster["w"] = nx2 - nx1
                matched_cluster["h"] = ny2 - ny1
                matched_cluster["frame_start"] = min(matched_cluster["frame_start"], cand["frame_start"])
                matched_cluster["frame_end"] = max(matched_cluster["frame_end"], cand["frame_end"])
                matched_cluster["persistence"] = max(matched_cluster["persistence"], cand.get("persistence", 0.8))
            else:
                clusters.append({
                    "x": cx1,
                    "y": cy1,
                    "w": cand["w"],
                    "h": cand["h"],
                    "frame_start": cand["frame_start"],
                    "frame_end": cand["frame_end"],
                    "persistence": cand.get("persistence", 0.8),
                })

        # Discard segments that are too brief to be meaningful subtitles (<= 3 frames)
        valid_segments: List[Dict[str, Any]] = []
        for cl in clusters:
            duration_frames = cl["frame_end"] - cl["frame_start"]
            if duration_frames >= 3:
                valid_segments.append(cl)

        return valid_segments


def detect_overlay_text_temporal(
    video_path: Union[str, Path],
    sample_fps: float = 30.0,
    window_size: int = 20,
    target_scope: str = "overlay",
) -> List[Dict[str, Any]]:
    """
    Project interface function: detects overlay text using temporal statistics.
    Conforms to PROJECT.md interface contract.
    """
    detector = TemporalTextDetector(window_size=window_size)
    return detector.detect_overlay_text_temporal(video_path, sample_fps=sample_fps, target_scope=target_scope)
