#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance/thresholds.py — Frozen Quality & Anti-Gaming Threshold Constants.
Milestone M0: Frozen Acceptance Judge Infrastructure.

All thresholds for C1-C8 are immutably defined here.
Any modification requires a dedicated 'FREEZE-BREAK: <reason>' commit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


# ═══════════════════════════════════════════════════════════════════════════════
# C1: RESIDUAL OVERLAY TEXT REMOVAL
# ═══════════════════════════════════════════════════════════════════════════════
RESIDUAL_OCR_WORDS_MAX: int = 0  # Zero frame tolerance across 100% of frames
RESIDUAL_CORE_MATCH_MAX: float = 0.02  # <= 2% text-core luminance match ratio
RESIDUAL_OCR_CONF_THRESHOLD: float = 45.0  # Tesseract OCR confidence cutoff
RESIDUAL_OCR_MIN_WORD_LENGTH: int = 2  # Syllable length cutoff
RESIDUAL_OCR_REQUIRE_VOWEL: bool = True  # Reject high-frequency noise hallucinations


# ═══════════════════════════════════════════════════════════════════════════════
# C2: COLLATERAL DAMAGE OUTSIDE DILATED MASK (+15px)
# ═══════════════════════════════════════════════════════════════════════════════
MASK_DILATION_PX: int = 15  # Strict spatial dilation margin (+15px)
COLLATERAL_PSNR_DELTA_MEAN_MAX_DB: float = 1.0  # Mean PSNR >= baseline - 1.0 dB
COLLATERAL_PSNR_DELTA_P5_MAX_DB: float = 3.0  # 5th percentile PSNR >= baseline - 3.0 dB
COLLATERAL_SSIM_MIN: float = 0.980  # Structural similarity outside mask


# ═══════════════════════════════════════════════════════════════════════════════
# C3: RECONSTRUCTION FIDELITY (INSIDE INPAINT MASK VS CLEAN GT)
# ═══════════════════════════════════════════════════════════════════════════════
# Category R: Moving background / Intermittent text (P1-P6)
CAT_R_PSNR_MEDIAN_MIN_DB: float = 30.0
CAT_R_PSNR_P10_MIN_DB: float = 25.0
CAT_R_SSIM_MEDIAN_MIN: float = 0.900

# Category U: Static camera / Persistent text (P9-P10)
CAT_U_PSNR_MEDIAN_MIN_DB: float = 24.0
CAT_U_SSIM_MEDIAN_MIN: float = 0.900


# ═══════════════════════════════════════════════════════════════════════════════
# C4: TEMPORAL CONSISTENCY & SCENE CUTS
# ═══════════════════════════════════════════════════════════════════════════════
TEMPORAL_FLOW_WARP_RATIO_MAX: float = 1.20  # Flow error inside <= 1.20x natural context
TEMPORAL_JUMP_SIGMA_MAX: float = 3.0  # No frame jump > natural + 3 * sigma
SCENE_CUT_MEAN_DIFF_THRESHOLD: float = 45.0  # Pixel absolute difference cutoff
SCENE_CUT_HIST_THRESHOLD: float = 0.45  # Bhattacharyya distance cutoff
SCENE_CUT_DHASH_THRESHOLD: int = 22  # 64-bit dHash Hamming distance cutoff


# ═══════════════════════════════════════════════════════════════════════════════
# C5: NEGATIVES INTEGRITY (P7 & P8)
# ═══════════════════════════════════════════════════════════════════════════════
NEGATIVE_PSNR_MIN_DB: float = 60.0  # Output must be identical to input (>= 60 dB)
SCENE_TEXT_SSIM_DELTA_MAX: float = 0.020  # Scene text SSIM degradation <= 0.02 vs plain re-encode
NEGATIVE_REGIONS_MAX: int = 0  # Zero regions detected/inpainted on clean footage


# ═══════════════════════════════════════════════════════════════════════════════
# C6: VISUAL ARTIFACTS & SEAMS
# ═══════════════════════════════════════════════════════════════════════════════
MAX_CONNECTED_ARTIFACT_AREA_RATIO: float = 0.0025  # Zero connected blocks > 0.25% frame area
SEAM_DISCONTINUITY_RATIO_MAX: float = 1.25  # Sobel edge discontinuity ratio <= 1.25
LAPLACIAN_TEXTURE_RATIO_MIN: float = 0.70  # Texture variance ratio >= 0.70


# ═══════════════════════════════════════════════════════════════════════════════
# C7: A/V INTEGRITY & CONTAINER ATTRIBUTES
# ═══════════════════════════════════════════════════════════════════════════════
AUDIO_BIT_EXACT: bool = True  # Audio stream MD5 hash must match bit-for-bit (100%)
DURATION_DELTA_MAX_SEC: float = 0.100  # Duration difference <= 0.1s
EXPECTED_PIX_FMT: str = "yuv420p"  # Standard pixel format


# ═══════════════════════════════════════════════════════════════════════════════
# C8: RESOURCE & OPERATIONAL LIMITS
# ═══════════════════════════════════════════════════════════════════════════════
MAX_CONTAINER_RSS_MB: float = 1350.0  # Peak container memory < 1350 MB on kirito-server
MAX_ORPHAN_PROCESSES: int = 0  # Zero orphaned worker processes
MAX_LEAKED_GPU_JOBS: int = 0  # Zero leaked remote GPU jobs


@dataclass(frozen=True)
class FrozenJudgeThresholds:
    """Frozen thresholds configuration object."""
    schema_version: str = "3.0.0"
    status: str = "FROZEN_LOCKED"

    # C1
    residual_ocr_words_max: int = RESIDUAL_OCR_WORDS_MAX
    residual_core_match_max: float = RESIDUAL_CORE_MATCH_MAX
    residual_ocr_conf_threshold: float = RESIDUAL_OCR_CONF_THRESHOLD
    residual_ocr_min_word_length: int = RESIDUAL_OCR_MIN_WORD_LENGTH
    residual_ocr_require_vowel: bool = RESIDUAL_OCR_REQUIRE_VOWEL

    # C2
    mask_dilation_px: int = MASK_DILATION_PX
    collateral_psnr_delta_mean_max_db: float = COLLATERAL_PSNR_DELTA_MEAN_MAX_DB
    collateral_psnr_delta_p5_max_db: float = COLLATERAL_PSNR_DELTA_P5_MAX_DB
    collateral_ssim_min: float = COLLATERAL_SSIM_MIN

    # C3
    cat_r_psnr_median_min_db: float = CAT_R_PSNR_MEDIAN_MIN_DB
    cat_r_psnr_p10_min_db: float = CAT_R_PSNR_P10_MIN_DB
    cat_r_ssim_median_min: float = CAT_R_SSIM_MEDIAN_MIN
    cat_u_psnr_median_min_db: float = CAT_U_PSNR_MEDIAN_MIN_DB
    cat_u_ssim_median_min: float = CAT_U_SSIM_MEDIAN_MIN

    # C4
    temporal_flow_warp_ratio_max: float = TEMPORAL_FLOW_WARP_RATIO_MAX
    temporal_jump_sigma_max: float = TEMPORAL_JUMP_SIGMA_MAX
    scene_cut_mean_diff_threshold: float = SCENE_CUT_MEAN_DIFF_THRESHOLD
    scene_cut_hist_threshold: float = SCENE_CUT_HIST_THRESHOLD
    scene_cut_dhash_threshold: int = SCENE_CUT_DHASH_THRESHOLD

    # C5
    negative_psnr_min_db: float = NEGATIVE_PSNR_MIN_DB
    scene_text_ssim_delta_max: float = SCENE_TEXT_SSIM_DELTA_MAX
    negative_regions_max: int = NEGATIVE_REGIONS_MAX

    # C6
    max_connected_artifact_area_ratio: float = MAX_CONNECTED_ARTIFACT_AREA_RATIO
    seam_discontinuity_ratio_max: float = SEAM_DISCONTINUITY_RATIO_MAX
    laplacian_texture_ratio_min: float = LAPLACIAN_TEXTURE_RATIO_MIN

    # C7
    audio_bit_exact: bool = AUDIO_BIT_EXACT
    duration_delta_max_sec: float = DURATION_DELTA_MAX_SEC
    expected_pix_fmt: str = EXPECTED_PIX_FMT

    # C8
    max_container_rss_mb: float = MAX_CONTAINER_RSS_MB
    max_orphan_processes: int = MAX_ORPHAN_PROCESSES
    max_leaked_gpu_jobs: int = MAX_LEAKED_GPU_JOBS

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


GLOBAL_THRESHOLDS = FrozenJudgeThresholds()
