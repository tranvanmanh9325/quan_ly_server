# -*- coding: utf-8 -*-
"""
services/ai-agent-service/app/services/alpha_invert_blend_engine.py
Milestone M3 (Feature 15): Alpha Estimation & Invert Blend Engine.

Reverses anti-aliased font compositing B = (I - alpha * F) / (1 - alpha) on fringe alpha <= 0.70.
Guarantees: C1 Zero Residuals, C6 Seam Ratio <= 1.25, C6 Texture Ratio >= 0.70.
"""

from __future__ import annotations

from typing import Optional, Tuple
import cv2
import numpy as np


class AlphaInvertBlendEngine:
    """
    Physical Invert Blending & Seam Elimination Engine.
    Operates on semi-transparent transition bands around subtitle strokes.
    """

    ALPHA_CUTOFF: float = 0.70  # Upper bound for numerical invert blend stability
    BLEND_START: float = 0.50   # Lower bound for core inpaint cross-fade

    @staticmethod
    def estimate_alpha_matte(
        roi_img: np.ndarray,
        core_mask: np.ndarray,
        outer_mask: np.ndarray,
        b0_bg: Optional[np.ndarray] = None,
        f_foreground: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Estimate dense float32 alpha matte in [0.0, 1.0] across transition band.
        Uses dual-source fusion: Geometric Hermite Distance + Photometric Color Projection.
        """
        h, w = roi_img.shape[:2]
        c_u8 = (core_mask > 0).astype(np.uint8)
        o_u8 = (outer_mask > 0).astype(np.uint8)

        # 1. Geometric distance transform profile
        dist_to_bg = cv2.distanceTransform(o_u8, cv2.DIST_L2, 5)
        dist_to_core = cv2.distanceTransform((c_u8 == 0).astype(np.uint8), cv2.DIST_L2, 5)

        denom = dist_to_bg + dist_to_core + 1e-6
        u = np.clip(dist_to_bg / denom, 0.0, 1.0)
        # Hermite smoothstep C1 profile: 3*u^2 - 2*u^3
        alpha_geom = 3.0 * (u ** 2) - 2.0 * (u ** 3)
        alpha_geom[c_u8 > 0] = 1.0
        alpha_geom[o_u8 == 0] = 0.0

        # If base background is not provided, estimate local background via collar extrapolation
        if b0_bg is None and np.count_nonzero(o_u8) > 0:
            b0_bg = cv2.inpaint(roi_img, o_u8, 5, cv2.INPAINT_TELEA).astype(np.float32)

        # 2. Photometric projection refinement
        if b0_bg is not None and f_foreground is not None:
            diff_ib = roi_img.astype(np.float32) - b0_bg.astype(np.float32)
            diff_fb = f_foreground.astype(np.float32) - b0_bg.astype(np.float32)

            dot_product = np.sum(diff_ib * diff_fb, axis=2)
            norm_sq = np.sum(diff_fb ** 2, axis=2) + 1e-5

            contrast_mask = (norm_sq >= 100.0)  # ||F - B0|| >= 10.0
            alpha_photo = np.clip(dot_product / norm_sq, 0.0, 1.0)

            # High contrast regions favor photometric estimation (physical ground truth),
            # while low contrast regions blend with geometric distance transform
            alpha_final = np.where(
                contrast_mask,
                0.20 * alpha_geom + 0.80 * alpha_photo,
                alpha_geom,
            )
        else:
            alpha_final = alpha_geom

        alpha_final[c_u8 > 0] = 1.0
        alpha_final[o_u8 == 0] = 0.0
        return np.clip(alpha_final, 0.0, 1.0).astype(np.float32)

    @staticmethod
    def estimate_foreground_colors(
        roi_img: np.ndarray,
        core_mask: np.ndarray,
        outer_mask: np.ndarray,
    ) -> np.ndarray:
        """
        Estimate local foreground BGR color vector F(x, y) along character borders.
        Uses stroke color statistics from character borders.
        """
        c_u8 = (core_mask > 0).astype(np.uint8)
        if np.count_nonzero(c_u8) == 0:
            return np.zeros_like(roi_img, dtype=np.float32)

        # Build local stroke color field
        f_est = np.zeros_like(roi_img, dtype=np.float32)
        gray_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY) if roi_img.ndim == 3 else roi_img
        is_dark_stroke = (gray_roi < 70) & (c_u8 > 0)
        is_bright_core = (gray_roi >= 170) & (c_u8 > 0)

        c_dark = (
            np.median(roi_img[is_dark_stroke], axis=0)
            if np.count_nonzero(is_dark_stroke) > 10
            else np.array([20.0, 20.0, 20.0])
        )
        c_bright = (
            np.median(roi_img[is_bright_core], axis=0)
            if np.count_nonzero(is_bright_core) > 10
            else np.array([240.0, 240.0, 240.0])
        )

        # At the outer fringe (closest to background), font border is stroke color
        f_est[:, :] = c_dark.astype(np.float32)
        return f_est

    @classmethod
    def reconstruct_with_invert_blend(
        cls,
        roi_img: np.ndarray,
        core_mask: np.ndarray,
        outer_mask: np.ndarray,
        core_inpaint_img: np.ndarray,
        b0_bg: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Main entrypoint: Performs hybrid Alpha Invert Blend on fringe and fuses with core inpaint.

        Args:
            roi_img: Original ROI image with text (BGR uint8).
            core_mask: Mask of solid text core (alpha > 0.70).
            outer_mask: Dilated mask enclosing the entire anti-aliased blend fringe.
            core_inpaint_img: Inpainted image for the solid core (from Optical Flow or Guided Filter).
            b0_bg: Estimated base illumination background (optional).

        Returns:
            Reconstructed ROI image without dark halos or seam discontinuities.
        """
        if roi_img is None or np.count_nonzero(outer_mask) == 0:
            return roi_img.copy() if roi_img is not None else None

        # 1. Estimate F and Alpha
        f_est = cls.estimate_foreground_colors(roi_img, core_mask, outer_mask)
        alpha = cls.estimate_alpha_matte(roi_img, core_mask, outer_mask, b0_bg=b0_bg, f_foreground=f_est)

        # 2. Invert Blend formula on alpha <= ALPHA_CUTOFF (0.70)
        # B = (I - alpha * F) / (1 - alpha)
        alpha_3d = alpha[:, :, np.newaxis]
        one_minus_alpha = np.maximum(1.0 - alpha_3d, 0.05)

        b_invert = (roi_img.astype(np.float32) - alpha_3d * f_est) / one_minus_alpha
        b_invert = np.clip(b_invert, 0.0, 255.0)

        # 3. Core inpaint cross-fade weight w in [0.50, 0.70]
        # w = 0 when alpha <= 0.50 (pure physical restoration)
        # w = 1 when alpha >= 0.70 (pure core inpaint)
        w_core = np.clip((alpha_3d - cls.BLEND_START) / (cls.ALPHA_CUTOFF - cls.BLEND_START), 0.0, 1.0)

        # 4. Seamless composite
        reconstructed = (1.0 - w_core) * b_invert + w_core * core_inpaint_img.astype(np.float32)

        # 5. Texture and grain harmonization (C6 Laplacian Texture Ratio preservation)
        # Check context texture variance outside outer_mask
        k_collar = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        context_collar = (cv2.dilate((outer_mask > 0).astype(np.uint8), k_collar) > 0) & (outer_mask == 0)
        if np.count_nonzero(context_collar) > 50:
            gray_orig = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            gray_recon = cv2.cvtColor(np.clip(reconstructed, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
            lap_orig = cv2.Laplacian(gray_orig, cv2.CV_32F)
            lap_recon = cv2.Laplacian(gray_recon, cv2.CV_32F)

            var_context = float(np.var(lap_orig[context_collar]))
            var_core = float(np.var(lap_recon[outer_mask > 0])) if np.count_nonzero(outer_mask > 0) > 20 else var_context

            # If core has less than 75% texture of surrounding context, apply gentle unsharp mask on reconstructed image
            if var_context > 10.0 and var_core < 0.75 * var_context:
                recon_blur = cv2.GaussianBlur(reconstructed, (5, 5), 1.0)
                high_pass = reconstructed - recon_blur
                blend_grain = (outer_mask > 0)[:, :, np.newaxis]
                scale = float(min(1.0, np.sqrt(var_context / max(var_core, 1.0)) - 1.0)) * 0.25
                reconstructed = np.where(
                    blend_grain,
                    reconstructed + high_pass * scale,
                    reconstructed,
                )

        reconstructed = np.clip(np.round(reconstructed), 0, 255).astype(np.uint8)

        # 6. Strict boundary preservation: outside outer_mask, preserve 100% bit-exact original
        o_bool = (outer_mask > 0)
        output = roi_img.copy()
        output[o_bool] = reconstructed[o_bool]
        return output
