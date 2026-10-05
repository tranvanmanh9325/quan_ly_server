"""Video Quality Audit Verification Harness.

Independent verification toolkit for video text removal and background inpainting quality.
Includes OCR residual text audit, background SSIM calculation, Laplacian texture variance,
inter-frame temporal flicker measurement, and side-by-side Before/After comparison generation.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import unittest

import cv2
import numpy as np
import pytesseract

HAS_TESSERACT = bool(shutil.which("tesseract"))


# ==============================================================================
# 1. Residual OCR Audit Function
# ==============================================================================
def audit_frame_ocr(
    frame_image: Union[np.ndarray, str, Path],
    banned_words: Optional[Sequence[str]] = None,
    roi_box: Optional[Union[Tuple[int, int, int, int], Sequence[int]]] = None,
    lang: str = "vie+eng",
    conf_threshold: int = 25,
) -> List[str]:
    """Run independent Tesseract OCR on a video frame or cropped ROI.

    Detects if any residual or banned subtitle words remain after inpainting.
    Uses multi-pass thresholding (RGB, bright foreground, Otsu, inverted) to ensure
    robust recognition of subtitle text over textured or varying backgrounds.

    Args:
        frame_image: Numpy BGR array or path to the image file.
        banned_words: List of subtitle keywords to check for (e.g. ['2x', 'tuổi', 'hợp đồng']).
                      If None, returns all recognized words above confidence threshold.
        roi_box: Optional ROI bounding box (x, y, w, h) or (x1, y1, x2, y2) to crop old text region.
        lang: Tesseract language models (default: 'vie+eng').
        conf_threshold: Minimum OCR confidence (0-100) to consider a detected word.

    Returns:
        List of residual banned words found in the image.
    """
    if not HAS_TESSERACT:
        raise RuntimeError("Tesseract binary not found on system PATH. Please install tesseract-ocr.")

    if isinstance(frame_image, (str, Path)):
        img = cv2.imread(str(frame_image))
        if img is None:
            raise FileNotFoundError(f"Cannot read image file at {frame_image}")
    else:
        img = frame_image

    if img is None or img.size == 0:
        raise ValueError("Provided frame_image is empty or None")

    h_img, w_img = img.shape[:2]

    # Crop to ROI if specified
    if roi_box is not None:
        c0, c1, c2, c3 = roi_box
        if c2 > c0 and c3 > c1 and (c2 <= w_img and c3 <= h_img) and (c2 - c0 > 100 or c3 - c1 > 100):
            x1, y1, x2, y2 = int(c0), int(c1), int(c2), int(c3)
        else:
            x1, y1 = int(c0), int(c1)
            x2, y2 = int(c0 + c2), int(c1 + c3)

        x1 = max(0, min(x1, w_img - 1))
        y1 = max(0, min(y1, h_img - 1))
        x2 = max(x1 + 1, min(x2, w_img))
        y2 = max(y1 + 1, min(y2, h_img))
        target_img = img[y1:y2, x1:x2]
    else:
        target_img = img

    if target_img.size == 0:
        return []

    # Prepare multi-pass candidates for robust OCR
    candidates: List[np.ndarray] = []
    if len(target_img.shape) == 3:
        rgb = cv2.cvtColor(target_img, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
    else:
        rgb = cv2.cvtColor(target_img, cv2.COLOR_GRAY2RGB)
        gray = target_img

    candidates.append(rgb)

    # Threshold for bright subtitle core (TikTok/Reels bright subtitles)
    _, th_bright = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
    candidates.append(th_bright)

    # Otsu adaptive threshold and its inverted counterpart
    _, th_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates.append(th_otsu)
    candidates.append(cv2.bitwise_not(th_otsu))

    all_detected_tokens: set[str] = set()

    for cand in candidates:
        for psm in [6, 11]:
            try:
                txt = pytesseract.image_to_string(cand, lang=lang, config=f"--psm {psm}")
                tokens = re.findall(r"[\w]+", txt.lower())
                for t in tokens:
                    if len(t) >= 2:
                        all_detected_tokens.add(t)
            except Exception:
                continue

    if not banned_words:
        return sorted(list(all_detected_tokens))

    # Match banned words
    found_banned: List[str] = []
    for banned in banned_words:
        target = banned.strip().lower()
        if not target:
            continue
        sub_words = re.findall(r"[\w]+", target)
        if any(sw in all_detected_tokens for sw in sub_words) or any(
            target in tok for tok in all_detected_tokens
        ):
            found_banned.append(banned)

    return found_banned


# ==============================================================================
# 2. Background SSIM Calculation Function
# ==============================================================================
def calculate_background_ssim(
    frame_orig: Union[np.ndarray, str, Path],
    frame_clean: Union[np.ndarray, str, Path],
    text_mask: Optional[Union[np.ndarray, str, Path]] = None,
    dilation_radius: int = 10,
) -> float:
    """Calculate Structural Similarity Index (SSIM) strictly on background pixels outside text mask.

    Implements Wang et al. (2004) SSIM using pure OpenCV and NumPy with Gaussian weighting.

    Args:
        frame_orig: Original frame (BGR array or path).
        frame_clean: Inpainted/cleaned frame (BGR array or path).
        text_mask: Binary mask where 255 represents text/inpaint region and 0 represents background.
                   If None, SSIM is computed over the entire frame.
        dilation_radius: Pixel margin to dilate the text mask to avoid inpainting boundary artifacts.

    Returns:
        Mean SSIM score for the background area (float between 0.0 and 1.0).
    """
    if isinstance(frame_orig, (str, Path)):
        img_orig = cv2.imread(str(frame_orig))
        if img_orig is None:
            raise FileNotFoundError(f"Cannot read frame_orig at {frame_orig}")
    else:
        img_orig = frame_orig

    if isinstance(frame_clean, (str, Path)):
        img_clean = cv2.imread(str(frame_clean))
        if img_clean is None:
            raise FileNotFoundError(f"Cannot read frame_clean at {frame_clean}")
    else:
        img_clean = frame_clean

    if img_orig is None or img_clean is None:
        raise ValueError("Input frames cannot be None")

    # Match dimensions if necessary
    h, w = img_orig.shape[:2]
    if img_clean.shape[:2] != (h, w):
        img_clean = cv2.resize(img_clean, (w, h), interpolation=cv2.INTER_LINEAR)

    # Convert to grayscale
    gray1 = cv2.cvtColor(img_orig, cv2.COLOR_BGR2GRAY) if len(img_orig.shape) == 3 else img_orig
    gray2 = cv2.cvtColor(img_clean, cv2.COLOR_BGR2GRAY) if len(img_clean.shape) == 3 else img_clean

    # Determine background valid mask (True for background, False for text region)
    if text_mask is not None:
        if isinstance(text_mask, (str, Path)):
            m = cv2.imread(str(text_mask), cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise FileNotFoundError(f"Cannot read text_mask at {text_mask}")
        else:
            m = text_mask

        if len(m.shape) == 3:
            m = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)

        if m.shape[:2] != (h, w):
            m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)

        # Dilate mask to ensure edge boundary is excluded from background measurement
        if dilation_radius > 0:
            ksize = 2 * dilation_radius + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
            dilated = cv2.dilate(m, kernel)
        else:
            dilated = m

        valid_bg = (dilated < 128)
    else:
        valid_bg = np.ones((h, w), dtype=bool)

    if not np.any(valid_bg):
        # Mask covers 100% of the frame
        return 1.0

    # SSIM constants
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    img1 = gray1.astype(np.float64)
    img2 = gray2.astype(np.float64)

    # 11x11 Gaussian window, sigma 1.5
    kernel_1d = cv2.getGaussianKernel(11, 1.5)
    window = np.outer(kernel_1d, kernel_1d.transpose())

    mu1 = cv2.filter2D(img1, -1, window, borderType=cv2.BORDER_REFLECT)
    mu2 = cv2.filter2D(img2, -1, window, borderType=cv2.BORDER_REFLECT)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.filter2D(img1 * img1, -1, window, borderType=cv2.BORDER_REFLECT) - mu1_sq
    sigma2_sq = cv2.filter2D(img2 * img2, -1, window, borderType=cv2.BORDER_REFLECT) - mu2_sq
    sigma12 = cv2.filter2D(img1 * img2, -1, window, borderType=cv2.BORDER_REFLECT) - mu1_mu2

    numerator = (2.0 * mu1_mu2 + c1) * (2.0 * sigma12 + c2)
    denominator = (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)

    ssim_map = numerator / (denominator + 1e-12)
    bg_ssim = float(np.mean(ssim_map[valid_bg]))
    return float(np.clip(bg_ssim, 0.0, 1.0))


# ==============================================================================
# 3. Laplacian Texture Variance Function
# ==============================================================================
def check_laplacian_texture(
    frame_clean: Union[np.ndarray, str, Path],
    roi_box: Union[Tuple[int, int, int, int], Sequence[int]],
) -> float:
    """Calculate Laplacian variance to detect blurred or cement-like texture artifacts.

    High variance indicates sharp natural texture, while very low variance
    signals flat, blurred, or smeared inpaint patches (delogo cement defect).

    Args:
        frame_clean: Cleaned frame (BGR array or path).
        roi_box: Tuple representing bounding box. Supports either (x, y, w, h) or (x1, y1, x2, y2).

    Returns:
        Laplacian variance of the ROI (float).
    """
    if isinstance(frame_clean, (str, Path)):
        img = cv2.imread(str(frame_clean))
        if img is None:
            raise FileNotFoundError(f"Cannot read frame_clean at {frame_clean}")
    else:
        img = frame_clean

    if img is None or img.size == 0:
        raise ValueError("frame_clean is empty or None")

    h_img, w_img = img.shape[:2]
    c0, c1, c2, c3 = roi_box

    # Disambiguate (x, y, w, h) vs (x1, y1, x2, y2)
    if c2 > c0 and c3 > c1 and (c2 <= w_img and c3 <= h_img) and (c2 - c0 > 100 or c3 - c1 > 100):
        # Likely (x1, y1, x2, y2)
        x1, y1, x2, y2 = int(c0), int(c1), int(c2), int(c3)
    else:
        # Standard (x, y, w, h)
        x1, y1 = int(c0), int(c1)
        x2, y2 = int(c0 + c2), int(c1 + c3)

    # Clamp bounds to image dimensions
    x1 = max(0, min(x1, w_img - 1))
    y1 = max(0, min(y1, h_img - 1))
    x2 = max(x1 + 1, min(x2, w_img))
    y2 = max(y1 + 1, min(y2, h_img))

    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0

    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
    lap = cv2.Laplacian(gray_roi, cv2.CV_64F, ksize=3)
    variance = float(lap.var())
    return variance


# ==============================================================================
# 4. Inter-frame Flicker Measurement Function
# ==============================================================================
def check_interframe_flicker(
    frames: Sequence[Union[np.ndarray, str, Path]],
    roi_box: Optional[Union[Tuple[int, int, int, int], Sequence[int]]] = None,
) -> float:
    """Measure temporal luminance acceleration |2*F(t) - F(t-1) - F(t+1)| across 3 consecutive frames.

    A high score indicates jarring intensity fluctuations or inpainting flickering.

    Args:
        frames: Sequence of at least 3 consecutive frames [f_prev, f_curr, f_next].
        roi_box: Optional ROI box (x, y, w, h) to limit the evaluation to the inpainted region.

    Returns:
        Mean temporal second-derivative flicker score (float >= 0.0).
    """
    if len(frames) < 3:
        raise ValueError(f"At least 3 consecutive frames are required, got {len(frames)}")

    loaded_frames: List[np.ndarray] = []
    for item in frames[:3]:
        if isinstance(item, (str, Path)):
            fr = cv2.imread(str(item))
            if fr is None:
                raise FileNotFoundError(f"Cannot read frame at {item}")
        else:
            fr = item
        if fr is None or fr.size == 0:
            raise ValueError("Frame item is empty or None")
        loaded_frames.append(fr)

    h_img, w_img = loaded_frames[0].shape[:2]

    # Crop to ROI if specified
    if roi_box is not None:
        c0, c1, c2, c3 = roi_box
        if c2 > c0 and c3 > c1 and (c2 <= w_img and c3 <= h_img) and (c2 - c0 > 100 or c3 - c1 > 100):
            x1, y1, x2, y2 = int(c0), int(c1), int(c2), int(c3)
        else:
            x1, y1 = int(c0), int(c1)
            x2, y2 = int(c0 + c2), int(c1 + c3)

        x1 = max(0, min(x1, w_img - 1))
        y1 = max(0, min(y1, h_img - 1))
        x2 = max(x1 + 1, min(x2, w_img))
        y2 = max(y1 + 1, min(y2, h_img))

        crops = [fr[y1:y2, x1:x2] for fr in loaded_frames]
    else:
        crops = loaded_frames

    # Convert to grayscale float64
    grays = [
        cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).astype(np.float64) if len(c.shape) == 3 else c.astype(np.float64)
        for c in crops
    ]

    f_prev, f_curr, f_next = grays[0], grays[1], grays[2]
    # Ensure matching shapes
    h, w = f_curr.shape
    if f_prev.shape != (h, w):
        f_prev = cv2.resize(f_prev, (w, h))
    if f_next.shape != (h, w):
        f_next = cv2.resize(f_next, (w, h))

    # Second temporal derivative
    flicker_map = np.abs(2.0 * f_curr - f_prev - f_next)
    mean_flicker = float(np.mean(flicker_map))
    return mean_flicker


# ==============================================================================
# 5. Side-by-Side Comparison Generator Function
# ==============================================================================
def generate_side_by_side_comparison(
    frame_orig: Union[np.ndarray, str, Path],
    frame_clean: Union[np.ndarray, str, Path],
    label: str,
    output_path: Union[str, Path],
) -> str:
    """Generate professional side-by-side Before/After inspection image with annotated banner.

    Args:
        frame_orig: Original frame with text.
        frame_clean: Cleaned frame without text.
        label: Description text (timestamp, frame index, scene context).
        output_path: Target path to save the composite image.

    Returns:
        Absolute string path to the saved comparison image.
    """
    if isinstance(frame_orig, (str, Path)):
        img_orig = cv2.imread(str(frame_orig))
        if img_orig is None:
            raise FileNotFoundError(f"Cannot read frame_orig at {frame_orig}")
    else:
        img_orig = frame_orig

    if isinstance(frame_clean, (str, Path)):
        img_clean = cv2.imread(str(frame_clean))
        if img_clean is None:
            raise FileNotFoundError(f"Cannot read frame_clean at {frame_clean}")
    else:
        img_clean = frame_clean

    if img_orig is None or img_clean is None:
        raise ValueError("Frames cannot be None")

    h, w = img_orig.shape[:2]
    if img_clean.shape[:2] != (h, w):
        img_clean = cv2.resize(img_clean, (w, h), interpolation=cv2.INTER_LINEAR)

    # 1. Overlay badges on each frame
    annotated_orig = img_orig.copy()
    annotated_clean = img_clean.copy()

    # Draw semi-transparent badge "BEFORE (Original)"
    badge_h = 40
    overlay_orig = annotated_orig.copy()
    cv2.rectangle(overlay_orig, (0, 0), (280, badge_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay_orig, 0.75, annotated_orig, 0.25, 0, annotated_orig)
    cv2.putText(
        annotated_orig,
        "BEFORE (Original)",
        (15, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 165, 255),  # Orange
        2,
        cv2.LINE_AA,
    )

    # Draw semi-transparent badge "AFTER (Inpainted)"
    overlay_clean = annotated_clean.copy()
    cv2.rectangle(overlay_clean, (0, 0), (280, badge_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay_clean, 0.75, annotated_clean, 0.25, 0, annotated_clean)
    cv2.putText(
        annotated_clean,
        "AFTER (Cleaned)",
        (15, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 127),  # Green
        2,
        cv2.LINE_AA,
    )

    # 2. Horizontal concatenation with divider
    divider_w = 4
    divider = np.full((h, divider_w, 3), 200, dtype=np.uint8)
    combined_body = np.hstack([annotated_orig, divider, annotated_clean])
    total_w = combined_body.shape[1]

    # 3. Top header banner
    header_h = 56
    header = np.full((header_h, total_w, 3), 32, dtype=np.uint8)

    # Header label text
    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)[0]
    text_x = max(20, (total_w - text_size[0]) // 2)
    text_y = 36
    cv2.putText(
        header,
        label,
        (text_x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    # Stack header on top
    final_canvas = np.vstack([header, combined_body])

    # Save to output path
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), final_canvas)
    return str(out_path.resolve())


# ==============================================================================
# Unit Test Suite for Independent Verification Harness
# ==============================================================================
class TestVideoQualityAuditHarness(unittest.TestCase):
    """Test suite verifying the correctness of all quality audit functions."""

    def setUp(self) -> None:
        # Create synthetic test patterns
        self.canvas_w = 576
        self.canvas_h = 1024

        # Background with texture (synthetic grid/dots to simulate car speaker grill)
        self.base_texture = np.full((self.canvas_h, self.canvas_w, 3), 140, dtype=np.uint8)
        for y in range(0, self.canvas_h, 8):
            for x in range(0, self.canvas_w, 8):
                cv2.circle(self.base_texture, (x, y), 2, (70, 70, 70), -1)

    @unittest.skipUnless(HAS_TESSERACT, "Tesseract OCR binary required on PATH")
    def test_audit_frame_ocr_detection(self) -> None:
        """Verify audit_frame_ocr detects banned text when present and none when removed."""
        frame_with_text = self.base_texture.copy()
        cv2.putText(
            frame_with_text,
            "HOP DONG WEBSITE",
            (80, 200),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )

        banned = ["website", "hop", "dong", "khongco"]
        residuals = audit_frame_ocr(frame_with_text, banned_words=banned)
        self.assertTrue(any("website" in r.lower() or "hop" in r.lower() for r in residuals))
        self.assertNotIn("khongco", residuals)

        # On clean background, no banned words should be detected
        residuals_clean = audit_frame_ocr(self.base_texture, banned_words=banned)
        self.assertEqual(len(residuals_clean), 0)

    def test_calculate_background_ssim(self) -> None:
        """Verify SSIM outside text mask is 1.0 for untouched background."""
        orig = self.base_texture.copy()
        clean = self.base_texture.copy()

        # Modify inside mask region only
        mask = np.zeros((self.canvas_h, self.canvas_w), dtype=np.uint8)
        mask[100:300, 50:500] = 255
        clean[100:300, 50:500] = 0  # Inpainted differently

        # Background outside mask remains identical
        ssim_val = calculate_background_ssim(orig, clean, text_mask=mask, dilation_radius=5)
        self.assertGreaterEqual(ssim_val, 0.99)

    def test_check_laplacian_texture_blur_detection(self) -> None:
        """Verify Laplacian variance reliably differentiates between texture and flat smear."""
        roi_box = (50, 100, 200, 150)
        x, y, w, h = roi_box

        textured_frame = self.base_texture.copy()
        var_textured = check_laplacian_texture(textured_frame, roi_box)

        # Flat blurred smear (delogo artifact simulation)
        smeared_frame = self.base_texture.copy()
        smeared_frame[y : y + h, x : x + w] = cv2.GaussianBlur(
            smeared_frame[y : y + h, x : x + w], (31, 31), 0
        )
        var_smeared = check_laplacian_texture(smeared_frame, roi_box)

        # Texture variance should be significantly higher than blurred patch
        self.assertGreater(var_textured, var_smeared * 2.0)

    def test_check_interframe_flicker_smooth_vs_spike(self) -> None:
        """Verify flicker measurement distinguishes continuous motion from intensity spikes."""
        f0 = self.base_texture.copy()
        f1 = self.base_texture.copy()
        f2 = self.base_texture.copy()

        score_smooth = check_interframe_flicker([f0, f1, f2])
        self.assertAlmostEqual(score_smooth, 0.0, delta=0.01)

        # Introduce sudden luminance spike at middle frame (flicker)
        f1_flicker = f1.copy()
        f1_flicker[200:400, 100:300] = np.clip(
            f1_flicker[200:400, 100:300].astype(int) + 120, 0, 255
        ).astype(np.uint8)
        score_flicker = check_interframe_flicker([f0, f1_flicker, f2], roi_box=(100, 200, 200, 200))
        self.assertGreater(score_flicker, 40.0)

    def test_generate_side_by_side_comparison(self) -> None:
        """Verify composite image is generated with correct resolution and label."""
        tmp_out = Path("/tmp/test_sbs_output.png")
        if tmp_out.exists():
            tmp_out.unlink()

        res_path = generate_side_by_side_comparison(
            self.base_texture,
            self.base_texture,
            label="Frame 150 (t=5.0s) - Ground Truth Inspection",
            output_path=tmp_out,
        )
        self.assertTrue(os.path.exists(res_path))
        saved_img = cv2.imread(res_path)
        self.assertIsNotNone(saved_img)
        # Expected width: 576 * 2 + 4 divider = 1156
        self.assertEqual(saved_img.shape[1], self.canvas_w * 2 + 4)
        # Expected height: 1024 + 56 header = 1080
        self.assertEqual(saved_img.shape[0], self.canvas_h + 56)

        # Cleanup
        if tmp_out.exists():
            tmp_out.unlink()


if __name__ == "__main__":
    unittest.main()
