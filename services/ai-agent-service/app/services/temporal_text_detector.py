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

        checkpoints = [
            max(0, f_start),
            max(0, (f_start + f_end) // 2),
            max(0, f_end - 1),
        ]

        scene_votes = 0
        valid_motion_pairs = 0

        for f_idx in checkpoints:
            if f_idx < 0 or f_idx >= num_frames - 1:
                continue
            video_cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret1, frame1 = video_cap.read()
            ret2, frame2 = video_cap.read()
            if not ret1 or not ret2 or frame1 is None or frame2 is None:
                continue

            flow = self.compute_dense_flow(frame1, frame2)
            if flow is None:
                continue

            res = self.classify_region_motion(segment, flow)
            if res["v_bg"] >= self.min_bg_motion:
                valid_motion_pairs += 1
                if res["motion_type"] == "scene":
                    scene_votes += 1

        if valid_motion_pairs > 0 and scene_votes >= 1:
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
        horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, int(round(18 * scale))), 3))

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

            # Spatial morphological gradient
            grad = cv2.morphologyEx(proc_gray, cv2.MORPH_GRADIENT, morph_k)
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

        # Fallback for target_scope == "all": also detect physical scene text candidates
        if target_scope == "all":
            scene_cands = self._detect_scene_text_candidates(cap, total_frames, orig_w, orig_h, fps)
            raw_candidates_per_window.extend(scene_cands)

        # Merge window candidates into continuous timeline segments
        if not raw_candidates_per_window:
            cap.release()
            return []

        merged_segments = self._cluster_temporal_candidates(raw_candidates_per_window, orig_w, orig_h, fps)

        # Optical flow motion classification across timeline
        final_results: List[Dict[str, Any]] = []
        for seg in merged_segments:
            motion_type = self.classifier.classify_segment_temporal_polling(seg, cap, fps, total_frames)
            seg["motion_type"] = motion_type

            # If default overlay mode: exclude physical scene text candidates
            if target_scope in ("overlay", "overlay_only") and motion_type == "scene":
                logger.info(
                    "[TemporalDetector] Preserving scene text candidate: bbox=[%d, %d, %d, %d], motion=%s",
                    seg["y"], seg["y"] + seg["h"], seg["x"], seg["x"] + seg["w"], motion_type
                )
                continue

            y1 = seg["y"]
            y2 = seg["y"] + seg["h"]
            x1 = seg["x"]
            x2 = seg["x"] + seg["w"]

            is_title = (seg["frame_end"] - seg["frame_start"]) > (0.60 * total_frames)

            final_results.append({
                "bbox": [y1, y2, x1, x2],
                "x": seg["x"],
                "y": seg["y"],
                "w": seg["w"],
                "h": seg["h"],
                "start_sec": round(seg["frame_start"] / fps, 3),
                "end_sec": round(seg["frame_end"] / fps, 3),
                "frame_start": seg["frame_start"],
                "frame_end": seg["frame_end"],
                "motion_type": motion_type,
                "persistence": seg.get("persistence", 0.85),
                "type": "title" if is_title else "subtitle",
                "lines": [{"x": seg["x"], "y": seg["y"], "w": seg["w"], "h": seg["h"], "text": ""}],
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
        Extract scene text candidates across sampled frames when target_scope == 'all'.
        Uses high-contrast stroke gradient clustering.
        """
        cands: List[Dict[str, Any]] = []
        sample_indices = [
            int(f) for f in np.linspace(0, max(0, total_frames - 2), min(10, max(2, total_frames // 15)))
        ]

        morph_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))

        for f_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, morph_k)
            _, thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, horiz_k)
            cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for c in cnts:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bh < 12 or bw < 20 or (bw * bh) > (0.30 * orig_w * orig_h):
                    continue
                # Aspect ratio and stroke density
                if (bw / float(bh)) < 0.6:
                    continue

                sub_grad = grad[by : by + bh, bx : bx + bw]
                if float(np.mean(sub_grad)) < 25.0:
                    continue

                cands.append({
                    "x": max(0, bx - 4),
                    "y": max(0, by - 4),
                    "w": min(orig_w - bx, bw + 8),
                    "h": min(orig_h - by, bh + 8),
                    "frame_start": max(0, f_idx - 10),
                    "frame_end": min(total_frames, f_idx + 15),
                    "persistence": 0.50,
                    "score": 0.60,
                })

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
