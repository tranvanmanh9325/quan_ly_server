"""
Module VideoCritiqueEngine: Autonomous Self-Critique Loop inside Tiểu Bảo Bảo (Milestone 3).
Triển khai:
- Feature F9: 5 Streaming CPU Quality Metrics (Residual OCR, Laplacian Texture, Temporal Flicker, Edge Seam, dHash Drift).
- Feature F10: Vision-LLM Critic & Strategy Ladder Refinement (Worst-K temporal NMS, Contact Sheet, Groq/OpenRouter pool, Graceful CPU Fallback, Bounded Strategy Ladder).
"""

import asyncio
import base64
import heapq
import json
import logging
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:
    pytesseract = None

from app.config import settings
from app.core.groq_pool import GroqKeyPool

logger = logging.getLogger(__name__)


# ─── DATA MODELS ─────────────────────────────────────────────────────────────

@dataclass
class FrameQualityRecord:
    frame_idx: int
    timestamp_sec: float
    residual_words: int
    residual_max_conf: float
    residual_text: str
    texture_ratio: float
    temporal_flicker_mse: float
    edge_seam_ratio: float
    dhash_drift: int
    is_shot_cut: bool
    penalty_score: float
    roi_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    orig_crop: Optional[np.ndarray] = None
    clean_crop: Optional[np.ndarray] = None
    mask_crop: Optional[np.ndarray] = None


@dataclass
class WorstCandidateRecord:
    frame_idx: int
    timestamp_sec: float
    penalty_score: float
    roi_rect: Tuple[int, int, int, int]
    orig_crop: np.ndarray
    clean_crop: np.ndarray
    mask_crop: np.ndarray
    violated_metrics: List[str] = field(default_factory=list)


@dataclass
class CritiqueJudgeResult:
    score: int  # 1 to 5
    artifacts: List[str]  # ["text_residue", "blur_smear", "seam_edge_artifact", "patch_misalignment"]
    is_pass: bool  # True if score >= 4
    suggested_action: str  # "expand_mask_dilation" | "borrow_flow_keyframe" | "emergency_ns_feather" | "pass_no_action"
    reason: str
    source_judge: str  # "groq_vision" | "openrouter_vision" | "pure_cpu_fallback"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── OPENROUTER KEY POOL (MIN-HEAP PRIORITY QUEUE) ───────────────────────────

class _OpenRouterKeyEntry:
    __slots__ = ("available_at", "usage_count", "fail_count", "key_id", "api_key")

    def __init__(self, key_id: int, api_key: str):
        self.available_at: float = 0.0
        self.usage_count: int = 0
        self.fail_count: int = 0
        self.key_id: int = key_id
        self.api_key: str = api_key

    def __lt__(self, other: "_OpenRouterKeyEntry") -> bool:
        if self.available_at != other.available_at:
            return self.available_at < other.available_at
        if self.usage_count != other.usage_count:
            return self.usage_count < other.usage_count
        return self.key_id < other.key_id


class OpenRouterKeyPool:
    """
    Min-Heap Priority Queue OpenRouter API Key Pool.
    Thread-safe and memory-efficient with adaptive backoff for HTTP 429.
    """

    def __init__(self, api_keys: List[str]):
        self._entries_map: Dict[str, _OpenRouterKeyEntry] = {}
        self._heap: List[_OpenRouterKeyEntry] = []
        for k in api_keys:
            clean_key = k.strip() if k else ""
            if clean_key and clean_key not in self._entries_map:
                entry = _OpenRouterKeyEntry(len(self._heap), clean_key)
                self._entries_map[clean_key] = entry
                self._heap.append(entry)
        heapq.heapify(self._heap)
        self._lock = asyncio.Lock()
        logger.info("[OpenRouterKeyPool] Initialized with %d API key(s).", len(self._heap))

    @property
    def key_count(self) -> int:
        return len(self._heap)

    def has_keys(self) -> bool:
        return len(self._heap) > 0

    async def get_next_key(self) -> Optional[str]:
        if not self._heap:
            return None

        async with self._lock:
            now = time.monotonic()
            available = [e for e in self._heap if e.available_at <= now]
            if available:
                best = min(available, key=lambda e: (e.usage_count, e.key_id))
            else:
                best = min(self._heap, key=lambda e: (e.available_at, e.usage_count, e.key_id))
            best.usage_count += 1
            return best.api_key

    async def mark_rate_limited(self, key: str) -> None:
        clean = key.strip() if key else ""
        async with self._lock:
            entry = self._entries_map.get(clean)
            if not entry:
                return
            entry.fail_count += 1
            base_backoff = min(90.0, 8.0 * (2 ** min(entry.fail_count - 1, 4)))
            jitter = random.uniform(0.5, 3.0)
            cooldown_time = base_backoff + jitter
            entry.available_at = time.monotonic() + cooldown_time
            logger.warning(
                "[OpenRouterKeyPool] Key #%d rate-limited (fail_count=%d, cooldown=%.1fs).",
                entry.key_id, entry.fail_count, cooldown_time
            )

    async def mark_success(self, key: str) -> None:
        clean = key.strip() if key else ""
        async with self._lock:
            entry = self._entries_map.get(clean)
            if entry:
                if entry.fail_count > 0:
                    entry.fail_count = 0
                if entry.available_at > 0.0:
                    entry.available_at = 0.0


# ─── VIDEO CRITIQUE ENGINE ───────────────────────────────────────────────────

class VideoCritiqueEngine:
    """
    Autonomous Self-Critique Loop Engine (Milestone 3, Features F9 & F10).
    Combines 5 Streaming CPU Quality Metrics with Vision-LLM Critic & Strategy Ladder.
    """

    def __init__(
        self,
        groq_pool: Optional[GroqKeyPool] = None,
        openrouter_pool: Optional[OpenRouterKeyPool] = None,
        max_refinement_rounds: int = 2,
    ):
        if groq_pool is not None:
            self._groq_pool = groq_pool
        else:
            self._groq_pool = GroqKeyPool(settings.groq_keys)

        if openrouter_pool is not None:
            self._openrouter_pool = openrouter_pool
        else:
            self._openrouter_pool = OpenRouterKeyPool(settings.openrouter_keys)

        self.max_refinement_rounds = max_refinement_rounds

    # ─── FEATURE F9: 5 STREAMING CPU METRICS ─────────────────────────────────

    @staticmethod
    def compute_residual_ocr(clean_roi: np.ndarray, padding: int = 16) -> Tuple[int, float, str]:
        """
        Metric 1: Residual OCR Confidence via Tesseract (vie+eng).
        Applies 2x zoom and CLAHE local contrast enhancement to expose faint ghosting text.
        Returns: (word_count, max_confidence, detected_text)
        """
        if clean_roi is None or clean_roi.size == 0 or pytesseract is None:
            return 0, 0.0, ""

        h, w = clean_roi.shape[:2]
        if h < 4 or w < 4:
            return 0, 0.0, ""

        try:
            # 2x Bilinear Interpolation zoom to enlarge small glyphs
            scaled = cv2.resize(clean_roi, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY) if scaled.ndim == 3 else scaled

            # CLAHE contrast enhancement
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            # OCR with Tesseract
            # First try sparse text mode (--psm 11), fallback to block mode (--psm 6)
            data = pytesseract.image_to_data(
                enhanced,
                lang="vie+eng",
                config="--psm 11 --oem 1",
                output_type=pytesseract.Output.DICT,
            )

            words: List[str] = []
            confs: List[float] = []

            VOWELS_VN = set("aeiouyáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữự")

            for text, conf in zip(data.get("text", []), data.get("conf", [])):
                raw_word = text.strip().lower()
                try:
                    conf_float = float(conf)
                except (ValueError, TypeError):
                    conf_float = -1.0

                # Extract alphabetic characters
                alpha_word = "".join(c for c in raw_word if c.isalpha())

                # Objective natural OCR verification: valid syllables require length >= 2, at least one vowel, and conf >= 40.0
                if conf_float >= 40.0 and len(alpha_word) >= 2:
                    if any(c in VOWELS_VN for c in alpha_word):
                        words.append(alpha_word)
                        confs.append(conf_float)

            word_count = len(words)
            max_conf = max(confs) if confs else 0.0
            return word_count, max_conf, " ".join(words)
        except Exception as ocr_err:
            logger.debug("[VideoCritiqueEngine] Residual OCR execution failed: %s", ocr_err)
            return 0, 0.0, ""

    @staticmethod
    def compute_texture_ratio(cleaned_frame: np.ndarray, mask: np.ndarray) -> Tuple[float, float, float]:
        """
        Metric 2: Inpainted ROI Texture Ratio.
        Compares Laplacian variance inside inpaint mask vs surrounding context ring.
        Returns: (texture_ratio, inpaint_var, context_var)
        Pass condition: ratio >= 0.70 (or context is smooth background).
        """
        if cleaned_frame is None or mask is None or cleaned_frame.size == 0 or mask.size == 0:
            return 1.0, 0.0, 0.0

        m_inpaint = mask > 0
        if not np.any(m_inpaint):
            return 1.0, 0.0, 0.0

        # Crop to local inpaint bounding box with 20px padding to minimize memory footprint
        y_indices, x_indices = np.where(m_inpaint)
        y1, y2 = max(0, int(np.min(y_indices)) - 20), min(cleaned_frame.shape[0], int(np.max(y_indices)) + 20)
        x1, x2 = max(0, int(np.min(x_indices)) - 20), min(cleaned_frame.shape[1], int(np.max(x_indices)) + 20)
        cleaned_sub = cleaned_frame[y1:y2, x1:x2]
        mask_sub = mask[y1:y2, x1:x2]

        gray = cv2.cvtColor(cleaned_sub, cv2.COLOR_BGR2GRAY) if cleaned_sub.ndim == 3 else cleaned_sub
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        m_sub_inpaint = mask_sub > 0

        # Construct context ring: dilate 15x15 minus inpaint mask
        k_context = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        dilated = cv2.dilate(mask_sub, k_context)
        m_context = (dilated > 0) & (~m_sub_inpaint)

        if not np.any(m_context):
            return 1.0, float(np.var(lap[m_sub_inpaint])), 0.0

        var_inpaint = float(np.var(lap[m_sub_inpaint]))
        var_context = float(np.var(lap[m_context]))

        # Smooth background exception: clear sky, solid white paper
        if var_context < 15.0:
            if abs(var_inpaint - var_context) <= 10.0:
                return 1.0, var_inpaint, var_context

        ratio = float(var_inpaint / (var_context + 1e-6))
        return ratio, var_inpaint, var_context

    @staticmethod
    def compute_temporal_flicker(
        curr_clean: np.ndarray,
        prev_clean: Optional[np.ndarray],
        mask: np.ndarray,
    ) -> Tuple[float, bool]:
        """
        Metric 3: Flow-Warped Temporal Flicker via DIS Optical Flow.
        Compensates camera motion before measuring MSE inside inpainted region.
        Returns: (flicker_mse, is_shot_cut)
        Pass condition: flicker_mse <= 45.0 (shot cut is exempted).
        """
        if prev_clean is None or curr_clean is None or curr_clean.size == 0:
            return 0.0, False

        curr_gray = cv2.cvtColor(curr_clean, cv2.COLOR_BGR2GRAY) if curr_clean.ndim == 3 else curr_clean
        prev_gray = cv2.cvtColor(prev_clean, cv2.COLOR_BGR2GRAY) if prev_clean.ndim == 3 else prev_clean

        # Shot cut check on whole frame
        diff_all = cv2.absdiff(curr_gray, prev_gray)
        if float(np.mean(diff_all)) > 35.0:
            return 0.0, True

        m_idx = mask > 0
        if not np.any(m_idx):
            return 0.0, False

        try:
            dis = cv2.DISOpticalFlow.create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
            flow = dis.calc(curr_gray, prev_gray, None)

            h, w = curr_gray.shape[:2]
            grid_x, grid_y = np.meshgrid(np.arange(w), np.arange(h))
            map_x = (grid_x + flow[..., 0]).astype(np.float32)
            map_y = (grid_y + flow[..., 1]).astype(np.float32)

            warped_prev = cv2.remap(
                prev_clean, map_x, map_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE
            )
            diff = curr_clean.astype(np.float32) - warped_prev.astype(np.float32)
            mse = float(np.mean(diff[m_idx] ** 2))
            return mse, False
        except Exception as flow_err:
            logger.debug("[VideoCritiqueEngine] Optical flow computation failed: %s", flow_err)
            diff = curr_clean.astype(np.float32) - prev_clean.astype(np.float32)
            mse = float(np.mean(diff[m_idx] ** 2))
            return mse, False

    @staticmethod
    def compute_edge_seam_ratio(cleaned_frame: np.ndarray, mask: np.ndarray) -> Tuple[float, float, float]:
        """
        Metric 4: Edge Seam Discontinuity.
        Computes Sobel gradient ratio between boundary band and natural reference ring.
        Returns: (seam_ratio, seam_grad, ref_grad)
        Pass condition: seam_ratio <= 1.25.
        """
        if cleaned_frame is None or mask is None or cleaned_frame.size == 0 or mask.size == 0:
            return 1.0, 0.0, 0.0

        m_idx = mask > 0
        if not np.any(m_idx):
            return 1.0, 0.0, 0.0

        # Crop to local inpaint bounding box with 15px padding to minimize memory footprint
        y_indices, x_indices = np.where(m_idx)
        y1, y2 = max(0, int(np.min(y_indices)) - 15), min(cleaned_frame.shape[0], int(np.max(y_indices)) + 15)
        x1, x2 = max(0, int(np.min(x_indices)) - 15), min(cleaned_frame.shape[1], int(np.max(x_indices)) + 15)
        cleaned_sub = cleaned_frame[y1:y2, x1:x2]
        mask_sub = mask[y1:y2, x1:x2]

        gray = cv2.cvtColor(cleaned_sub, cv2.COLOR_BGR2GRAY) if cleaned_sub.ndim == 3 else cleaned_sub
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        grad = np.sqrt(sobel_x ** 2 + sobel_y ** 2)

        # Seam band: dilate 3x3 minus erode 3x3
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dil3 = cv2.dilate(mask_sub, k3)
        erd3 = cv2.erode(mask_sub, k3)
        b_seam = (dil3 > 0) & (erd3 == 0)

        # Reference ring: dilate 9x9 minus dilate 3x3
        k9 = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        dil9 = cv2.dilate(mask_sub, k9)
        b_ref = (dil9 > 0) & (dil3 == 0)

        if not np.any(b_seam) or not np.any(b_ref):
            return 1.0, 0.0, 0.0

        mean_seam = float(np.mean(grad[b_seam]))
        mean_ref = float(np.mean(grad[b_ref]))

        # Smooth background exception: when reference background is nearly uniform
        if mean_ref < 5.0:
            if mean_seam < 12.0:
                return 1.0, mean_seam, mean_ref
            else:
                return float(mean_seam / 5.0), mean_seam, mean_ref

        ratio = float(mean_seam / (mean_ref + 1e-6))
        return ratio, mean_seam, mean_ref

    @staticmethod
    def compute_dhash_drift(curr_frame: np.ndarray, prev_frame: Optional[np.ndarray]) -> Tuple[int, bool]:
        """
        Metric 5: Frame Perceptual Hash Drift (64-bit dHash purely via NumPy/OpenCV).
        Compares horizontal gradients on 9x8 grayscale image.
        Returns: (drift, is_shot_cut)
        Pass condition: drift <= 6 (drift > 20 is marked as shot cut).
        """
        if prev_frame is None or curr_frame is None or curr_frame.size == 0:
            return 0, False

        def _calc_dhash(img: np.ndarray) -> np.ndarray:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
            resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
            return resized[:, 1:] > resized[:, :-1]  # 8x8 boolean matrix

        h1 = _calc_dhash(curr_frame)
        h2 = _calc_dhash(prev_frame)
        drift = int(np.count_nonzero(h1 != h2))
        is_shot_cut = drift > 20
        return drift, is_shot_cut

    @staticmethod
    def derive_inpaint_mask(orig_frame: np.ndarray, clean_frame: np.ndarray, thresh: int = 12) -> np.ndarray:
        """
        Derives inpaint binary mask from pixel difference between original and cleaned frames.
        Filters codec compression artifacts using morphology open.
        """
        if orig_frame is None or clean_frame is None or orig_frame.shape != clean_frame.shape:
            return np.zeros((10, 10), dtype=np.uint8)

        diff = cv2.absdiff(orig_frame, clean_frame)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) if diff.ndim == 3 else diff
        _, binary = cv2.threshold(gray_diff, thresh, 255, cv2.THRESH_BINARY)
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        cleaned_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k3)
        return cleaned_mask

    # ─── FEATURE F10: WORST-K HARVESTER & TEMPORAL NMS ───────────────────────

    @classmethod
    def calculate_composite_penalty(cls, record: FrameQualityRecord) -> float:
        """
        Calculates multi-objective composite penalty score.
        High penalty indicates severe visual flaw.
        """
        p_ocr = record.residual_words * 35.0 + record.residual_max_conf * 0.5
        p_tex = max(0.0, 0.70 - record.texture_ratio) * 50.0
        p_flicker = 0.0 if record.is_shot_cut else max(0.0, record.temporal_flicker_mse - 45.0) * 0.5
        p_seam = max(0.0, record.edge_seam_ratio - 1.25) * 40.0
        p_drift = 0.0 if record.is_shot_cut else max(0, record.dhash_drift - 6) * 5.0

        return float(p_ocr + p_tex + p_flicker + p_seam + p_drift)

    def select_worst_k_candidates(
        self,
        records: List[FrameQualityRecord],
        k: int = 3,
        min_gap_sec: float = 1.0,
    ) -> List[WorstCandidateRecord]:
        """
        Harvester with Temporal Non-Maximum Suppression (Temporal NMS).
        Picks top K worst frame pairs with at least min_gap_sec separation to avoid clustering on a single subtitle.
        """
        if not records:
            return []

        # Update composite penalty
        for r in records:
            r.penalty_score = self.calculate_composite_penalty(r)

        # Sort descending by penalty
        sorted_records = sorted(records, key=lambda x: x.penalty_score, reverse=True)

        selected: List[WorstCandidateRecord] = []
        selected_times: List[float] = []

        for r in sorted_records:
            # Check Temporal NMS separation
            if all(abs(r.timestamp_sec - t) >= min_gap_sec for t in selected_times):
                violated = []
                if r.residual_words > 0 or r.residual_max_conf >= 20.0:
                    violated.append("residual_text")
                if r.texture_ratio < 0.70:
                    violated.append("blur_smear")
                if r.temporal_flicker_mse > 45.0 and not r.is_shot_cut:
                    violated.append("temporal_flicker")
                if r.edge_seam_ratio > 1.25:
                    violated.append("seam_edge_artifact")
                if r.dhash_drift > 6 and not r.is_shot_cut:
                    violated.append("visual_drift")

                selected.append(
                    WorstCandidateRecord(
                        frame_idx=r.frame_idx,
                        timestamp_sec=r.timestamp_sec,
                        penalty_score=r.penalty_score,
                        roi_rect=r.roi_rect,
                        orig_crop=r.orig_crop if r.orig_crop is not None else np.zeros((10, 10, 3), dtype=np.uint8),
                        clean_crop=r.clean_crop if r.clean_crop is not None else np.zeros((10, 10, 3), dtype=np.uint8),
                        mask_crop=r.mask_crop if r.mask_crop is not None else np.zeros((10, 10), dtype=np.uint8),
                        violated_metrics=violated,
                    )
                )
                selected_times.append(r.timestamp_sec)

                if len(selected) >= k:
                    break

        # If video is 100% clean, pick uniformly sampled candidate checkpoints
        if not selected and records:
            step = max(1, len(records) // k)
            for i in range(0, min(len(records), k * step), step):
                r = records[i]
                selected.append(
                    WorstCandidateRecord(
                        frame_idx=r.frame_idx,
                        timestamp_sec=r.timestamp_sec,
                        penalty_score=r.penalty_score,
                        roi_rect=r.roi_rect,
                        orig_crop=r.orig_crop if r.orig_crop is not None else np.zeros((10, 10, 3), dtype=np.uint8),
                        clean_crop=r.clean_crop if r.clean_crop is not None else np.zeros((10, 10, 3), dtype=np.uint8),
                        mask_crop=r.mask_crop if r.mask_crop is not None else np.zeros((10, 10), dtype=np.uint8),
                        violated_metrics=[],
                    )
                )
                if len(selected) >= k:
                    break

        return selected

    # ─── FEATURE F10: CONTACT SHEET GENERATION ───────────────────────────────

    def build_contact_sheet(
        self,
        candidates: List[WorstCandidateRecord],
        target_dim: int = 1024,
    ) -> Tuple[np.ndarray, str]:
        """
        Synthesizes a Dual-Column Contact Sheet (Before vs After) normalized to <= target_dim x target_dim.
        Returns: (contact_sheet_bgr, base64_jpeg)
        """
        if not candidates:
            # Fallback 1x1 image
            blank = np.zeros((100, 100, 3), dtype=np.uint8)
            _, buf = cv2.imencode(".jpg", blank, [cv2.IMWRITE_JPEG_QUALITY, 85])
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            return blank, f"data:image/jpeg;base64,{b64}"

        rows = len(candidates)
        # Allocate cell dimensions
        cell_h = 240
        cell_w = 480
        header_h = 36
        sheet_w = cell_w * 2 + 30  # Left crop + Right crop + padding
        sheet_h = rows * (cell_h + header_h + 15) + 20

        canvas = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)
        # Neutral dark background
        canvas[:] = (30, 30, 30)

        for i, c in enumerate(candidates):
            y_start = 20 + i * (cell_h + header_h + 15)

            # Draw header bar
            header_rect = (10, y_start, sheet_w - 20, header_h)
            cv2.rectangle(
                canvas,
                (header_rect[0], header_rect[1]),
                (header_rect[0] + header_rect[2], header_rect[1] + header_rect[3]),
                (45, 45, 45),
                -1,
            )
            v_str = ", ".join(c.violated_metrics) if c.violated_metrics else "Clean"
            header_text = f"Frame #{c.frame_idx} | {c.timestamp_sec:.2f}s | Penalty={c.penalty_score:.1f} | Issues: {v_str}"
            cv2.putText(
                canvas, header_text, (header_rect[0] + 10, header_rect[1] + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1, cv2.LINE_AA
            )

            # Prepare Left (Original) & Right (Cleaned) crops
            orig = c.orig_crop if c.orig_crop is not None and c.orig_crop.size > 0 else np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
            clean = c.clean_crop if c.clean_crop is not None and c.clean_crop.size > 0 else np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

            orig_fitted = self._letterbox_image(orig, cell_w, cell_h)
            clean_fitted = self._letterbox_image(clean, cell_w, cell_h)

            # Add labels
            cv2.putText(orig_fitted, "ORIGINAL (BEFORE)", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2, cv2.LINE_AA)
            cv2.putText(clean_fitted, "CLEANED (AFTER)", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

            # Paste into canvas
            y_cell = y_start + header_h + 5
            canvas[y_cell:y_cell + cell_h, 10:10 + cell_w] = orig_fitted
            canvas[y_cell:y_cell + cell_h, 20 + cell_w:20 + cell_w * 2] = clean_fitted

        # Scale canvas to fit within target_dim x target_dim
        scale = min(1.0, float(target_dim) / max(sheet_w, sheet_h))
        if scale < 1.0:
            new_w = int(sheet_w * scale)
            new_h = int(sheet_h * scale)
            canvas = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_AREA)

        _, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64_str = base64.b64encode(buf.tobytes()).decode("ascii")
        return canvas, f"data:image/jpeg;base64,{b64_str}"

    @staticmethod
    def _letterbox_image(img: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """Resizes image maintaining aspect ratio with black letterbox padding."""
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return np.zeros((target_h, target_w, 3), dtype=np.uint8)

        scale = min(float(target_w) / w, float(target_h) / h)
        nw = int(w * scale)
        nh = int(h * scale)
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)

        boxed = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        y_off = (target_h - nh) // 2
        x_off = (target_w - nw) // 2
        boxed[y_off:y_off + nh, x_off:x_off + nw] = resized
        return boxed

    # ─── FEATURE F10: VISION-LLM JUDGE & CPU FALLBACK ────────────────────────

    async def judge_with_vision_llm(
        self,
        candidates: List[WorstCandidateRecord],
        aggregated_cpu_metrics: Optional[Dict[str, Any]] = None,
    ) -> CritiqueJudgeResult:
        """
        Vision-LLM Judge (Groq Vision pool -> OpenRouter Vision pool -> Pure CPU Fallback).
        Evaluates visual inpainting quality and returns strict CritiqueJudgeResult.
        """
        _, b64_contact_sheet = self.build_contact_sheet(candidates)

        system_prompt = (
            "You are a Senior VFX Inpainting Quality Auditor for video text removal.\n"
            "Analyze the provided Contact Sheet comparing BEFORE (left) and AFTER (right) crops.\n"
            "Identify visual artifacts:\n"
            "- 'text_residue': residual characters, diacritics, Vietnamese accents, ghost strokes.\n"
            "- 'blur_smear': gray smeared patch, loss of texture/pores/mesh.\n"
            "- 'seam_edge_artifact': sharp boundary step, halo around former text box.\n"
            "- 'patch_misalignment': perspective warping defect or misaligned edges.\n\n"
            "Score on a 1-5 scale:\n"
            "5 = Flawless studio finish, seamless background reconstruction.\n"
            "4 = Good (PASS). Clean text removal, subtle imperceptible optical changes.\n"
            "3 = Mediocre (FAIL). Noticeable residual blur or faint ghost strokes.\n"
            "2 = Poor (FAIL). Legible partial characters or heavy gray smear.\n"
            "1 = Severe defect (FAIL). Black holes, corrupt frames or unmasked text.\n\n"
            "Output strictly valid JSON with no markdown:\n"
            "{\"score\": 4, \"artifacts\": [], \"pass\": true, \"suggested_action\": \"pass_no_action\", \"reason\": \"clean background\"}\n"
            "Suggested actions when failing:\n"
            "- 'expand_mask_dilation': when text_residue or seam_edge_artifact is present.\n"
            "- 'borrow_flow_keyframe': when blur_smear or patch_misalignment on textured background.\n"
            "- 'emergency_ns_feather': when flickering edges or boundary halos persist."
        )

        user_content = [
            {"type": "text", "text": "Examine the contact sheet crops and provide your VFX quality verdict in strict JSON."},
            {"type": "image_url", "image_url": {"url": b64_contact_sheet}},
        ]

        # Tier 1: Groq Vision Models
        groq_models = [
            getattr(settings, "GROQ_VISION_MODEL", "qwen/qwen3.8-27b"),
            getattr(settings, "GROQ_VISION_MODEL_FALLBACK", "qwen/qwen3.6-27b"),
        ]

        for model_name in groq_models:
            if not self._groq_pool.has_keys():
                break

            key = await self._groq_pool.get_next_key()
            if not key:
                break

            try:
                raw_resp = await self._call_vision_http(
                    endpoint="https://api.groq.com/openai/v1/chat/completions",
                    api_key=key,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    timeout_sec=25.0,
                )
                parsed = self._extract_critique_json(raw_resp)
                if parsed:
                    await self._groq_pool.mark_success(key)
                    score = int(parsed.get("score", 3))
                    is_pass = bool(parsed.get("pass", score >= 4))
                    return CritiqueJudgeResult(
                        score=score,
                        artifacts=list(parsed.get("artifacts", [])),
                        is_pass=is_pass,
                        suggested_action=str(parsed.get("suggested_action", "pass_no_action" if is_pass else "expand_mask_dilation")),
                        reason=str(parsed.get("reason", "Groq Vision evaluation")),
                        source_judge="groq_vision",
                    )
            except Exception as g_err:
                if "429" in str(g_err):
                    await self._groq_pool.mark_rate_limited(key)
                logger.debug("[VideoCritiqueEngine] Groq Vision (%s) call failed: %s", model_name, g_err)

        # Tier 2: OpenRouter Vision Models
        openrouter_models = [
            getattr(settings, "OPENROUTER_VISION_MODEL", "google/gemma-4-31b-it:free"),
            getattr(settings, "OPENROUTER_VISION_MODEL_FALLBACK", "google/gemma-4-26b-a4b-it:free"),
            "openrouter/free",
        ]

        for model_name in openrouter_models:
            if not self._openrouter_pool.has_keys():
                break

            key = await self._openrouter_pool.get_next_key()
            if not key:
                break

            try:
                raw_resp = await self._call_vision_http(
                    endpoint="https://openrouter.ai/api/v1/chat/completions",
                    api_key=key,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    timeout_sec=25.0,
                )
                parsed = self._extract_critique_json(raw_resp)
                if parsed:
                    await self._openrouter_pool.mark_success(key)
                    score = int(parsed.get("score", 3))
                    is_pass = bool(parsed.get("pass", score >= 4))
                    return CritiqueJudgeResult(
                        score=score,
                        artifacts=list(parsed.get("artifacts", [])),
                        is_pass=is_pass,
                        suggested_action=str(parsed.get("suggested_action", "pass_no_action" if is_pass else "expand_mask_dilation")),
                        reason=str(parsed.get("reason", "OpenRouter Vision evaluation")),
                        source_judge="openrouter_vision",
                    )
            except Exception as o_err:
                if "429" in str(o_err):
                    await self._openrouter_pool.mark_rate_limited(key)
                logger.debug("[VideoCritiqueEngine] OpenRouter Vision (%s) call failed: %s", model_name, o_err)

        # Tier 3: Pure CPU Fallback Judge (Zero Crash Guarantee)
        logger.info("[VideoCritiqueEngine] All Vision-LLM calls exhausted or offline. Gracefully falling back to Pure CPU Judge.")
        return self.pure_cpu_fallback_judge(candidates, aggregated_cpu_metrics)

    @classmethod
    def pure_cpu_fallback_judge(
        cls,
        candidates: List[WorstCandidateRecord],
        aggregated_cpu_metrics: Optional[Dict[str, Any]] = None,
    ) -> CritiqueJudgeResult:
        """
        Pure CPU Decision Logic based on 5 objective metrics when all remote Vision APIs are unavailable.
        """
        metrics = aggregated_cpu_metrics or {}
        res_ocr = metrics.get("residual_ocr_words", 0)
        tex_ratio = metrics.get("laplacian_texture_ratio", 1.0)
        flicker_mse = metrics.get("temporal_flicker_mse", 0.0)
        seam_ratio = metrics.get("seam_discontinuity", 1.0)

        # Check candidate penalties as well
        worst_penalty = max([c.penalty_score for c in candidates], default=0.0)

        artifacts = []
        if res_ocr > 0:
            artifacts.append("text_residue")
        if tex_ratio < 0.70:
            artifacts.append("blur_smear")
        if seam_ratio > 1.25:
            artifacts.append("seam_edge_artifact")
        if flicker_mse > 45.0:
            artifacts.append("patch_misalignment")

        is_pass = (res_ocr == 0) and (tex_ratio >= 0.70) and (seam_ratio <= 1.25) and (worst_penalty <= 15.0)

        if is_pass:
            score = 4
            suggested_action = "pass_no_action"
            reason = "Pure CPU metrics all satisfy acceptable thresholds (0 residual text, texture ratio >= 0.70)."
        else:
            score = 2
            if "text_residue" in artifacts or "seam_edge_artifact" in artifacts:
                suggested_action = "expand_mask_dilation"
            elif "blur_smear" in artifacts:
                suggested_action = "borrow_flow_keyframe"
            else:
                suggested_action = "emergency_ns_feather"
            reason = f"Pure CPU metrics detected artifacts: {', '.join(artifacts)} (penalty={worst_penalty:.1f})."

        return CritiqueJudgeResult(
            score=score,
            artifacts=artifacts,
            is_pass=is_pass,
            suggested_action=suggested_action,
            reason=reason,
            source_judge="pure_cpu_fallback",
        )

    @staticmethod
    async def _call_vision_http(
        endpoint: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_content: List[Dict[str, Any]],
        timeout_sec: float = 25.0,
    ) -> str:
        """Asynchronous HTTP POST request via urllib/asyncio.to_thread with zero external dependency."""
        import json
        import urllib.request

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "TieuBaoBao-Critic/1.0",
        }
        req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method="POST")

        def _fetch() -> str:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read().decode("utf-8", errors="replace")

        resp_text = await asyncio.to_thread(_fetch)
        data = json.loads(resp_text)
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_critique_json(raw_text: str) -> Optional[Dict[str, Any]]:
        """Extracts JSON block safely, handling <think> tags and markdown backticks."""
        if not raw_text:
            return None

        # Remove thinking blocks from reasoning models
        cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)

        # Match markdown ```json ... ``` or raw {...}
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if json_match:
            candidate = json_match.group(1)
        else:
            brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            candidate = brace_match.group(1) if brace_match else cleaned

        try:
            return json.loads(candidate.strip())
        except Exception:
            # Fallback regex extraction
            try:
                score_match = re.search(r'"score"\s*:\s*(\d+)', cleaned)
                pass_match = re.search(r'"pass"\s*:\s*(true|false)', cleaned, re.IGNORECASE)
                action_match = re.search(r'"suggested_action"\s*:\s*"([^"]+)"', cleaned)
                reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', cleaned)

                if score_match:
                    score = int(score_match.group(1))
                    is_pass = pass_match.group(1).lower() == "true" if pass_match else (score >= 4)
                    action = action_match.group(1) if action_match else ("pass_no_action" if is_pass else "expand_mask_dilation")
                    reason = reason_match.group(1) if reason_match else "Extracted regex"
                    return {
                        "score": score,
                        "artifacts": [],
                        "pass": is_pass,
                        "suggested_action": action,
                        "reason": reason,
                    }
            except Exception:
                pass
        return None

    # ─── FEATURE F10: STRATEGY LADDER REFINEMENT DISPATCHER ──────────────────

    def recommend_refinement_strategy(
        self,
        critique_result: Union[CritiqueJudgeResult, Dict[str, Any]],
        round_num: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Strategy Ladder Refinement Dispatcher.
        Bounded iteration: max 2 refinement rounds.
        Returns: configuration dictionary for targeted refinement, or None if passed/exhausted.
        """
        if isinstance(critique_result, CritiqueJudgeResult):
            is_pass = critique_result.is_pass
            action = critique_result.suggested_action
            artifacts = critique_result.artifacts
        elif isinstance(critique_result, dict):
            # Check judge result embedded in critique report
            judge = critique_result.get("judge", {})
            is_pass = critique_result.get("is_pass", judge.get("is_pass", False))
            action = judge.get("suggested_action") or critique_result.get("suggested_action", "expand_mask_dilation")
            artifacts = judge.get("artifacts") or critique_result.get("artifacts", [])
        else:
            return None

        if is_pass or action == "pass_no_action":
            return None

        # Bounded iteration: Max rounds reached
        if round_num > self.max_refinement_rounds:
            logger.info("[VideoCritiqueEngine] Maximum refinement rounds (%d) reached.", self.max_refinement_rounds)
            return None

        if round_num == 1:
            if action == "expand_mask_dilation" or "text_residue" in artifacts or "seam_edge_artifact" in artifacts:
                return {
                    "round_num": 1,
                    "action": "expand_mask_dilation",
                    "dilation_extra_px": 4,
                    "top_margin_px": 8,  # Vietnamese diacritics margin
                    "bottom_margin_px": 4,
                    "description": "Thang 1: Mở rộng dilation (+4px) và tăng lề trên (+8px) cho dấu phụ tiếng Việt",
                }
            elif action == "borrow_flow_keyframe" or "blur_smear" in artifacts:
                return {
                    "round_num": 1,
                    "action": "borrow_flow_keyframe",
                    "use_flow_borrowing": True,
                    "description": "Thang 2: Kích hoạt mượn pixel thật từ keyframe sạch qua DIS Optical Flow",
                }
            else:
                return {
                    "round_num": 1,
                    "action": "emergency_ns_feather",
                    "feather_radius_px": 5,
                    "description": "Thang 3: Áp dụng Navier-Stokes kết hợp Gaussian Alpha Feathering 5px",
                }

        elif round_num == 2:
            # Round 2: Multi-tier combined deep refinement
            return {
                "round_num": 2,
                "action": "combined_deep_refine",
                "dilation_extra_px": 8,
                "top_margin_px": 10,
                "bottom_margin_px": 4,
                "use_flow_borrowing": True,
                "feather_radius_px": 5,
                "description": "Thang 4: Tinh chỉnh sâu kết hợp Dilation +8px, Flow borrowing và Feathering",
            }

        return None

    # ─── STREAMING EVALUATION PIPELINE (RAM < 100MB) ─────────────────────────

    def evaluate_video_stream_sync(
        self,
        original_path: str,
        cleaned_path: str,
        sample_interval: float = 0.25,
    ) -> Dict[str, Any]:
        """
        Streaming evaluation comparing original and cleaned videos with 2-frame sliding window.
        Keeps memory footprint strictly under 100MB.
        """
        orig_p = Path(original_path)
        clean_p = Path(cleaned_path)
        if not orig_p.exists() or not clean_p.exists():
            return {
                "status": "error",
                "message": f"Input files not found: {orig_p} or {clean_p}",
                "is_pass": False,
            }

        cap_orig = cv2.VideoCapture(str(orig_p))
        cap_clean = cv2.VideoCapture(str(clean_p))

        if not cap_orig.isOpened() or not cap_clean.isOpened():
            cap_orig.release()
            cap_clean.release()
            return {"status": "error", "message": "Cannot open video capture.", "is_pass": False}

        fps = cap_clean.get(cv2.CAP_PROP_FPS) or 29.98
        total_frames = int(cap_clean.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_step = max(1, int(fps * sample_interval))

        records: List[FrameQualityRecord] = []
        prev_clean_frame: Optional[np.ndarray] = None

        frame_idx = 0
        try:
            while cap_orig.isOpened() and cap_clean.isOpened():
                ret_o, fr_orig = cap_orig.read()
                ret_c, fr_clean = cap_clean.read()

                if not ret_o or not ret_c or fr_orig is None or fr_clean is None:
                    break

                if frame_idx % frame_step == 0:
                    timestamp = float(frame_idx / fps)

                    # Derive inpaint mask from pixel difference
                    mask = self.derive_inpaint_mask(fr_orig, fr_clean)

                    # Compute 5 CPU metrics
                    # Metric 1: Residual OCR on inpaint ROI
                    m_idx = mask > 0
                    if np.any(m_idx):
                        y_indices, x_indices = np.where(m_idx)
                        x1, y1 = max(0, int(np.min(x_indices)) - 8), max(0, int(np.min(y_indices)) - 8)
                        x2, y2 = min(fr_clean.shape[1], int(np.max(x_indices)) + 8), min(fr_clean.shape[0], int(np.max(y_indices)) + 8)
                        roi_rect = (x1, y1, x2 - x1, y2 - y1)
                        clean_roi = fr_clean[y1:y2, x1:x2].copy()
                        orig_roi = fr_orig[y1:y2, x1:x2].copy()
                        mask_roi = mask[y1:y2, x1:x2].copy()
                    else:
                        roi_rect = (0, 0, fr_clean.shape[1], fr_clean.shape[0])
                        clean_roi = fr_clean.copy()
                        orig_roi = fr_orig.copy()
                        mask_roi = mask.copy()

                    words_count, max_conf, words_str = self.compute_residual_ocr(clean_roi)
                    tex_ratio, var_inp, var_ctx = self.compute_texture_ratio(fr_clean, mask)
                    flicker_mse, is_shot_flicker = self.compute_temporal_flicker(fr_clean, prev_clean_frame, mask)
                    seam_ratio, seam_g, ref_g = self.compute_edge_seam_ratio(fr_clean, mask)
                    drift, is_shot_drift = self.compute_dhash_drift(fr_clean, prev_clean_frame)
                    is_shot_cut = is_shot_flicker or is_shot_drift

                    # Keep memory strictly bounded: downsize stored crops if larger than 320x240
                    if clean_roi.shape[0] > 240 or clean_roi.shape[1] > 320:
                        ch, cw = clean_roi.shape[:2]
                        s_f = min(320.0 / cw, 240.0 / ch)
                        tw, th = max(10, int(cw * s_f)), max(10, int(ch * s_f))
                        clean_crop_saved = cv2.resize(clean_roi, (tw, th), interpolation=cv2.INTER_AREA)
                        orig_crop_saved = cv2.resize(orig_roi, (tw, th), interpolation=cv2.INTER_AREA)
                        mask_crop_saved = cv2.resize(mask_roi, (tw, th), interpolation=cv2.INTER_NEAREST)
                    else:
                        clean_crop_saved = clean_roi
                        orig_crop_saved = orig_roi
                        mask_crop_saved = mask_roi

                    rec = FrameQualityRecord(
                        frame_idx=frame_idx,
                        timestamp_sec=timestamp,
                        residual_words=words_count,
                        residual_max_conf=max_conf,
                        residual_text=words_str,
                        texture_ratio=tex_ratio,
                        temporal_flicker_mse=flicker_mse,
                        edge_seam_ratio=seam_ratio,
                        dhash_drift=drift,
                        is_shot_cut=is_shot_cut,
                        penalty_score=0.0,
                        roi_rect=roi_rect,
                        orig_crop=orig_crop_saved,
                        clean_crop=clean_crop_saved,
                        mask_crop=mask_crop_saved,
                    )
                    records.append(rec)

                    prev_clean_frame = fr_clean.copy()

                    # Periodic memory cleanup to prevent glibc fragmentation
                    if len(records) % 32 == 0:
                        try:
                            from app.core.memory_reclaimer import _sync_collect_and_trim
                            _sync_collect_and_trim()
                        except Exception:
                            pass

                frame_idx += 1
        finally:
            cap_orig.release()
            cap_clean.release()
            try:
                from app.core.memory_reclaimer import _sync_collect_and_trim
                _sync_collect_and_trim()
            except Exception:
                pass

        # Aggregate Metrics Summary
        total_samples = max(1, len(records))
        residual_words_sum = sum(r.residual_words for r in records)
        max_residual_conf = max([r.residual_max_conf for r in records], default=0.0)
        mean_texture = float(np.mean([r.texture_ratio for r in records])) if records else 1.0
        min_texture = float(np.min([r.texture_ratio for r in records])) if records else 1.0
        mean_flicker = float(np.mean([r.temporal_flicker_mse for r in records if not r.is_shot_cut])) if records else 0.0
        mean_seam = float(np.mean([r.edge_seam_ratio for r in records])) if records else 1.0
        max_drift = max([r.dhash_drift for r in records if not r.is_shot_cut], default=0)

        # Select Worst-K candidates
        worst_candidates = self.select_worst_k_candidates(records, k=3, min_gap_sec=1.0)

        # Pass condition: 0 residual text words, acceptable texture and seam
        is_pass = (residual_words_sum == 0) and (min_texture >= 0.70) and (mean_seam <= 1.25)

        metrics_summary = {
            "residual_ocr_words": residual_words_sum,
            "residual_max_conf": max_residual_conf,
            "laplacian_texture_ratio": mean_texture,
            "laplacian_texture_min": min_texture,
            "temporal_flicker_mse": mean_flicker,
            "temporal_flicker_ratio": 1.0 + (mean_flicker / 100.0),
            "seam_discontinuity": mean_seam,
            "phash_drift": max_drift,
            "total_sampled_frames": total_samples,
        }

        return {
            "status": "ok",
            "is_pass": is_pass,
            "metrics": metrics_summary,
            "worst_candidates": worst_candidates,
            "records_count": len(records),
        }

    async def evaluate_video_stream(
        self,
        original_path: str,
        cleaned_path: str,
        sample_interval: float = 0.25,
    ) -> Dict[str, Any]:
        """Asynchronous wrapper for evaluate_video_stream_sync."""
        return await asyncio.to_thread(
            self.evaluate_video_stream_sync,
            original_path,
            cleaned_path,
            sample_interval,
        )

    def critique_worst_crops_sync(
        self,
        worst_candidates: List[WorstCandidateRecord],
        aggregated_cpu_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous evaluation of worst crops.
        If an event loop is running, dispatches to loop; otherwise executes pure CPU fallback.
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self.judge_with_vision_llm(worst_candidates, aggregated_cpu_metrics),
                loop
            )
            res = future.result(timeout=30.0)
            return res.to_dict()
        except Exception:
            return self.pure_cpu_fallback_judge(worst_candidates, aggregated_cpu_metrics).to_dict()
