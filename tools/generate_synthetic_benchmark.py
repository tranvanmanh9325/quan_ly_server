#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/generate_synthetic_benchmark.py — Deterministic Synthetic Benchmark Generator (42 Cases).
Phase 6 (R6 - Section 5, 6 & 7): Independent Frozen Measurement Suite, Synthetic Benchmark & Evidence Package.

Strict Anti-Gaming Partitioning:
  - 21 Tuning Cases:   SYNTH_TUNE_01 to SYNTH_TUNE_21
  - 21 Held-Out Cases: SYNTH_HELD_01 to SYNTH_HELD_21
  - 4 Artifacts per Case: clean.mp4, text.mp4, mask_ground_truth/ (PNG 255=text, 0=clean), metadata.json
  - Deterministic with --seed 42.
  - Streaming memory consumption < 80MB RAM.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TEXTURE GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class TextureGenerator:
    """Sinh các kết cấu nền vật lý và tần số cao dựa trên các hàm toán học tất định."""

    @staticmethod
    def generate_gradient_studio(width: int, height: int, color1=(20, 25, 30), color2=(80, 95, 110)) -> np.ndarray:
        x = np.linspace(0, 1, width, dtype=np.float32)
        y = np.linspace(0, 1, height, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        diag = (xx + yy) / 2.0
        diag = np.expand_dims(diag, axis=2)

        c1 = np.array(color1, dtype=np.float32)
        c2 = np.array(color2, dtype=np.float32)
        canvas = (1.0 - diag) * c1 + diag * c2
        return np.clip(canvas, 0, 255).astype(np.uint8)

    @staticmethod
    def generate_burmester_mesh(width: int, height: int, hole_radius: int = 2, step: int = 8) -> np.ndarray:
        """Porsche Burmester speaker mesh texture."""
        canvas = np.full((height, width, 3), 145, dtype=np.uint8)
        for y in range(step, height - step, step):
            shift = (step // 2) if (y // step) % 2 == 1 else 0
            for x in range(step + shift, width - step, step):
                cv2.circle(canvas, (x, y), hole_radius, (55, 55, 60), -1)
                cv2.circle(canvas, (x, y), hole_radius + 1, (185, 185, 195), 1)
        return canvas

    @staticmethod
    def generate_wood_grain(width: int, height: int) -> np.ndarray:
        """High frequency natural wood grain texture."""
        y_coords, x_coords = np.mgrid[0:height, 0:width]
        wave = np.sin(x_coords / 16.0 + 3.0 * np.sin(y_coords / 22.0))
        noise = (wave + 1.0) * 0.5

        base_color = np.array([45, 80, 140], dtype=np.float32)
        highlight_color = np.array([85, 130, 200], dtype=np.float32)
        noise_3d = np.expand_dims(noise, axis=2)

        canvas = (1.0 - noise_3d) * base_color + noise_3d * highlight_color
        fine_noise = np.random.normal(0, 4.0, (height, width, 1)).astype(np.float32)
        canvas = np.clip(canvas + fine_noise, 0, 255).astype(np.uint8)
        return canvas

    @staticmethod
    def generate_contract_document(width: int, height: int, line_spacing: int = 20) -> np.ndarray:
        """Paper document with tiny printed contract text lines."""
        canvas = np.full((height, width, 3), 245, dtype=np.uint8)
        line_color = (90, 90, 95)
        for y in range(40, height - 30, line_spacing):
            x = 40
            while x < width - 40:
                seg_len = random.randint(25, 80)
                gap = random.randint(10, 25)
                x_end = min(width - 40, x + seg_len)
                cv2.line(canvas, (x, y), (x_end, y), line_color, 1)
                x = x_end + gap
        return canvas

    @staticmethod
    def generate_fabric_linen(width: int, height: int) -> np.ndarray:
        """Fabric linen with woven mesh."""
        canvas = np.full((height, width, 3), 190, dtype=np.uint8)
        canvas[::3, :, :] = np.clip(canvas[::3, :, :].astype(np.int16) - 25, 0, 255).astype(np.uint8)
        canvas[:, ::3, :] = np.clip(canvas[:, ::3, :].astype(np.int16) + 20, 0, 255).astype(np.uint8)
        return canvas

    @staticmethod
    def generate_concrete_wall(width: int, height: int) -> np.ndarray:
        """Rough concrete wall."""
        base = np.full((height, width, 3), 120, dtype=np.uint8)
        noise = np.random.randint(-20, 21, (height, width, 3), dtype=np.int16)
        canvas = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return cv2.GaussianBlur(canvas, (3, 3), 0.8)

    @staticmethod
    def generate_brick_wall(width: int, height: int) -> np.ndarray:
        """Storefront brick wall texture."""
        canvas = np.full((height, width, 3), (40, 50, 160), dtype=np.uint8)
        mortar = (180, 180, 190)
        bw, bh = 80, 25
        for y in range(0, height, bh):
            shift = (bw // 2) if (y // bh) % 2 == 1 else 0
            cv2.line(canvas, (0, y), (width, y), mortar, 2)
            for x in range(shift, width, bw):
                cv2.line(canvas, (x, y), (x, y + bh), mortar, 2)
        noise = np.random.normal(0, 8.0, (height, width, 3)).astype(np.float32)
        return np.clip(canvas.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    @staticmethod
    def generate_chalkboard(width: int, height: int) -> np.ndarray:
        """Chalkboard texture."""
        canvas = np.full((height, width, 3), (35, 60, 35), dtype=np.uint8)
        dust = np.random.normal(0, 12.0, (height, width, 3)).astype(np.float32)
        return np.clip(canvas.astype(np.float32) + dust, 0, 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MOTION SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════

class MotionSimulator:
    """Mô phỏng chuyển động camera và cảnh quay trên Super Canvas."""

    def __init__(self, target_w: int, target_h: int, texture_type: str, motion_type: str,
                 scene_cut_frame: Optional[int] = None, scene_b_texture: Optional[str] = None):
        self.tw = target_w
        self.th = target_h
        self.motion_type = motion_type
        self.scene_cut_frame = scene_cut_frame

        self.pad_w = 400
        self.pad_h = 300
        self.canvas_w = target_w + self.pad_w
        self.canvas_h = target_h + self.pad_h

        self.canvas_a = self._create_canvas(texture_type, self.canvas_w, self.canvas_h)
        self.canvas_b = self._create_canvas(scene_b_texture, self.canvas_w, self.canvas_h) if scene_b_texture else None

    def _create_canvas(self, texture_type: str, w: int, h: int) -> np.ndarray:
        if texture_type == "burmester_mesh":
            return TextureGenerator.generate_burmester_mesh(w, h)
        elif texture_type == "wood_grain":
            return TextureGenerator.generate_wood_grain(w, h)
        elif texture_type == "contract_document":
            return TextureGenerator.generate_contract_document(w, h)
        elif texture_type == "fabric_linen":
            return TextureGenerator.generate_fabric_linen(w, h)
        elif texture_type == "concrete_wall":
            return TextureGenerator.generate_concrete_wall(w, h)
        elif texture_type == "brick_wall":
            return TextureGenerator.generate_brick_wall(w, h)
        elif texture_type == "chalkboard":
            return TextureGenerator.generate_chalkboard(w, h)
        else:
            return TextureGenerator.generate_gradient_studio(w, h)

    def get_clean_frame(self, frame_idx: int, total_frames: int) -> np.ndarray:
        source_canvas = self.canvas_a
        if self.scene_cut_frame is not None and frame_idx >= self.scene_cut_frame and self.canvas_b is not None:
            source_canvas = self.canvas_b

        center_x = self.pad_w // 2
        center_y = self.pad_h // 2

        if self.motion_type == "pan_horizontal":
            offset_x = int(center_x + (frame_idx - total_frames / 2.0) * 3.5)
            x1 = max(0, min(self.canvas_w - self.tw, offset_x))
            y1 = center_y
            return source_canvas[y1:y1 + self.th, x1:x1 + self.tw].copy()

        elif self.motion_type == "tilt_vertical":
            offset_y = int(center_y + (frame_idx - total_frames / 2.0) * 2.5)
            x1 = center_x
            y1 = max(0, min(self.canvas_h - self.th, offset_y))
            return source_canvas[y1:y1 + self.th, x1:x1 + self.tw].copy()

        elif self.motion_type == "zoom":
            progress = frame_idx / max(1, total_frames - 1)
            scale = 1.0 + 0.15 * progress
            crop_w = int(self.tw / scale)
            crop_h = int(self.th / scale)
            cx1 = center_x + (self.tw - crop_w) // 2
            cy1 = center_y + (self.th - crop_h) // 2
            cropped = source_canvas[cy1:cy1 + crop_h, cx1:cx1 + crop_w]
            return cv2.resize(cropped, (self.tw, self.th), interpolation=cv2.INTER_LINEAR)

        elif self.motion_type == "diagonal":
            offset_x = int(center_x + (frame_idx - total_frames / 2.0) * 2.0)
            offset_y = int(center_y + (frame_idx - total_frames / 2.0) * 2.0)
            x1 = max(0, min(self.canvas_w - self.tw, offset_x))
            y1 = max(0, min(self.canvas_h - self.th, offset_y))
            return source_canvas[y1:y1 + self.th, x1:x1 + self.tw].copy()

        else:
            return source_canvas[center_y:center_y + self.th, center_x:center_x + self.tw].copy()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TEXT OVERLAY ENGINE (UNICODE VIETNAMESE & EXACT MASKING)
# ═══════════════════════════════════════════════════════════════════════════════

class TextOverlayEngine:
    """Vẽ chữ tiếng Việt và các hiệu ứng thị giác phân tầng RGBA."""

    def __init__(self, target_w: int, target_h: int):
        self.tw = target_w
        self.th = target_h

    @staticmethod
    def get_font(size: int) -> ImageFont.FreeTypeFont:
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def render_element(self, text: str, font_size: int, pos_norm: Tuple[float, float],
                       style: str = "white_black_stroke", alpha: float = 1.0,
                       box_banner: bool = False) -> Tuple[Image.Image, Image.Image]:
        font = self.get_font(font_size)
        img_rgba = Image.new("RGBA", (self.tw, self.th), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_rgba)

        px = int(pos_norm[0] * self.tw)
        py = int(pos_norm[1] * self.th)

        core_color = (255, 255, 255, int(255 * alpha))
        stroke_color = (0, 0, 0, int(255 * alpha))
        stroke_width = max(2, font_size // 12)

        if style == "yellow_karaoke":
            core_color = (255, 220, 0, int(255 * alpha))
            stroke_color = (180, 0, 0, int(255 * alpha))
        elif style == "white_yellow_stroke":
            core_color = (255, 255, 255, int(255 * alpha))
            stroke_color = (255, 200, 0, int(255 * alpha))
        elif style == "cyan_purple_glow":
            core_color = (0, 240, 255, int(255 * alpha))
            stroke_color = (180, 0, 220, int(255 * alpha))

        if box_banner:
            # Draw semi-transparent background box
            box_layer = Image.new("RGBA", (self.tw, self.th), (0, 0, 0, 0))
            box_draw = ImageDraw.Draw(box_layer)
            box_h = int(font_size * 2.2)
            box_draw.rectangle([px - 20, py - 10, px + int(len(text) * font_size * 0.6) + 30, py + box_h],
                               fill=(30, 30, 40, int(200 * alpha)))
            img_rgba.alpha_composite(box_layer)

        if "shadow" in style:
            shadow_layer = Image.new("RGBA", (self.tw, self.th), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            shadow_draw.text((px + 4, py + 4), text, font=font, fill=(0, 0, 0, int(180 * alpha)))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(3))
            img_rgba.alpha_composite(shadow_layer)

        if "glow" in style:
            glow_layer = Image.new("RGBA", (self.tw, self.th), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow_layer)
            glow_fill = (255, 180, 0, int(200 * alpha)) if style != "cyan_purple_glow" else (200, 0, 240, int(220 * alpha))
            glow_draw.text((px, py), text, font=font, fill=glow_fill,
                           stroke_width=stroke_width + 4, stroke_fill=glow_fill)
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(6))
            img_rgba.alpha_composite(glow_layer)

        # Draw main core
        draw.text((px, py), text, font=font, fill=core_color, stroke_width=stroke_width, stroke_fill=stroke_color)

        # Extract binary mask from alpha channel
        alpha_channel = np.array(img_rgba.getchannel("A"))
        mask = (alpha_channel > 15).astype(np.uint8) * 255

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.dilate(mask, kernel, iterations=1)

        mask_pil = Image.fromarray(mask, mode="L")
        return img_rgba, mask_pil

    def blend_onto_frame(self, clean_bgr: np.ndarray, text_rgba: Image.Image) -> np.ndarray:
        clean_rgb = cv2.cvtColor(clean_bgr, cv2.COLOR_BGR2RGB)
        clean_pil = Image.fromarray(clean_rgb).convert("RGBA")
        clean_pil.alpha_composite(text_rgba)
        out_rgb = np.array(clean_pil.convert("RGB"))
        return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 42-CASE SPECIFICATION REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════════

def get_tuning_cases_specs() -> List[Dict[str, Any]]:
    """Tập Tuning 21 ca (SYNTH_TUNE_01 .. SYNTH_TUNE_21)."""
    return [
        {
            "case_id": "SYNTH_TUNE_01", "set": "tuning", "category": "layout_placement",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "TIÊU ĐỀ ĐẶC BIỆT", "font_size": 44, "pos_norm": [0.10, 0.08],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_02", "set": "tuning", "category": "layout_placement",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static"},
            "text_elements": [{
                "text": "BẢN QUYỀN NỘI DUNG", "font_size": 36, "pos_norm": [0.25, 0.45],
                "style": "white_black_stroke", "alpha": 0.50, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_03", "set": "tuning", "category": "layout_placement",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "static"},
            "text_elements": [{
                "text": "Hát karaoke vui vẻ cùng bạn bè", "font_size": 32, "pos_norm": [0.08, 0.82],
                "style": "yellow_karaoke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_04", "set": "tuning", "category": "layout_placement",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 75, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "BẢN TIN CÔNG NGHỆ 24H: CẬP NHẬT MỚI NHẤT", "font_size": 34, "pos_norm": [0.08, 0.85],
                "style": "white_black_stroke", "box_banner": True, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_05", "set": "tuning", "category": "layout_placement",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "static"},
            "text_elements": [{
                "text": "@channel_id", "font_size": 14, "pos_norm": [0.82, 0.05],
                "style": "white_black_stroke", "alpha": 0.65, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_06", "set": "tuning", "category": "temporal_dynamics",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static"},
            "text_elements": [{
                "text": "CHUYỂN TIẾP MỜ ẢO", "font_size": 36, "pos_norm": [0.12, 0.50],
                "style": "white_black_stroke", "temporal_behavior": "fade", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_07", "set": "tuning", "category": "temporal_dynamics",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 75, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "TIN NÓNG: THỊ TRƯỜNG CHỨNG KHOÁN TĂNG ĐIỂM LIÊN TỤC TRONG PHIÊN...",
                "font_size": 28, "pos_norm": [0.10, 0.88], "speed_norm": 0.010,
                "style": "white_black_stroke", "temporal_behavior": "ticker", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_08", "set": "tuning", "category": "temporal_dynamics",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 90, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "Chào mừng các bạn", "text_phase2": "Đến với kênh của chúng tôi",
                "jump_frame": 45, "font_size": 32, "pos_norm": [0.12, 0.78],
                "style": "white_black_stroke", "temporal_behavior": "jumping", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_09", "set": "tuning", "category": "layout_placement",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "fabric_linen", "camera_motion": "static"},
            "text_elements": [
                {"text": "DÒNG 1: TIÊU ĐỀ CHÍNH", "font_size": 36, "pos_norm": [0.15, 0.35], "style": "white_black_stroke", "is_overlay": True},
                {"text": "DÒNG 2: PHỤ CHÚ CHI TIẾT", "font_size": 32, "pos_norm": [0.15, 0.40], "style": "white_black_stroke", "is_overlay": True},
                {"text": "DÒNG 3: LIÊN HỆ NGAY", "font_size": 30, "pos_norm": [0.15, 0.45], "style": "white_black_stroke", "is_overlay": True}
            ]
        },
        {
            "case_id": "SYNTH_TUNE_10", "set": "tuning", "category": "temporal_dynamics",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static", "scene_cut_frame": 31, "scene_b_texture": "burmester_mesh"},
            "text_elements": [{
                "text": "PHỤ ĐỀ XUYÊN SUỐT CẢNH QUAY", "font_size": 32, "pos_norm": [0.20, 0.85],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_11", "set": "tuning", "category": "camera_motion",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "burmester_mesh", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "HỆ THỐNG ÂM THANH ĐỈNH CAO", "font_size": 30, "pos_norm": [0.08, 0.80],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_12", "set": "tuning", "category": "camera_motion",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "tilt_vertical"},
            "text_elements": [{
                "text": "HỢP ĐỒNG KINH TẾ QUAN TRỌNG", "font_size": 34, "pos_norm": [0.20, 0.15],
                "style": "yellow_karaoke_shadow", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_13", "set": "tuning", "category": "camera_motion",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "zoom"},
            "text_elements": [{
                "text": "ZOOM ĐIỆN ẢNH", "font_size": 48, "pos_norm": [0.35, 0.50],
                "style": "white_black_stroke_shadow", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_14", "set": "tuning", "category": "camera_motion",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "diagonal"},
            "text_elements": [{
                "text": "CHUYỂN ĐỘNG CHÉO NHANH", "font_size": 38, "pos_norm": [0.15, 0.70],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_15", "set": "tuning", "category": "camera_motion",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "ÁNH SÁNG NEON", "font_size": 36, "pos_norm": [0.15, 0.40],
                "style": "glow", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_16", "set": "tuning", "category": "short_words",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [
                {"text": "ok", "font_size": 26, "pos_norm": [0.20, 0.30], "style": "white_black_stroke", "is_overlay": True},
                {"text": "w", "font_size": 24, "pos_norm": [0.55, 0.55], "style": "white_black_stroke", "is_overlay": True},
                {"text": "ch", "font_size": 26, "pos_norm": [0.35, 0.75], "style": "white_black_stroke", "is_overlay": True}
            ]
        },
        {
            "case_id": "SYNTH_TUNE_17", "set": "tuning", "category": "short_words",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static"},
            "text_elements": [{
                "text": "Hướng Dẫn Kỹ Thuật Tối Ưu Hóa Tự Động", "font_size": 32, "pos_norm": [0.10, 0.45],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_TUNE_18", "set": "tuning", "category": "short_words",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "tilt_vertical"},
            "text_elements": [
                {"text": "đi", "font_size": 32, "pos_norm": [0.20, 0.40], "style": "white_black_stroke", "is_overlay": True},
                {"text": "ăn", "font_size": 32, "pos_norm": [0.45, 0.40], "style": "white_black_stroke", "is_overlay": True},
                {"text": "ở?", "font_size": 32, "pos_norm": [0.70, 0.40], "style": "white_black_stroke", "is_overlay": True}
            ]
        },
        {
            "case_id": "SYNTH_TUNE_19", "set": "tuning", "category": "negative_controls",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "burmester_mesh", "camera_motion": "pan_horizontal"},
            "text_elements": []  # Clean video negative control
        },
        {
            "case_id": "SYNTH_TUNE_20", "set": "tuning", "category": "negative_controls",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "brick_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "CỬA HÀNG ABC - GIẢM GIÁ 50%", "font_size": 32, "pos_norm": [0.20, 0.35],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": False  # Scene text
            }]
        },
        {
            "case_id": "SYNTH_TUNE_21", "set": "tuning", "category": "target_scope_positive",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "all",
            "background": {"texture_type": "brick_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [
                {"text": "GIỚI THIỆU PHỐ CỔ", "font_size": 32, "pos_norm": [0.25, 0.85], "style": "white_black_stroke", "is_overlay": True},
                {"text": "BIỂN HIỆU QUÁN ĂN", "font_size": 30, "pos_norm": [0.25, 0.25], "style": "white_black_stroke", "is_overlay": False}
            ]
        }
    ]


def get_held_out_cases_specs() -> List[Dict[str, Any]]:
    """Tập Held-Out 21 ca (SYNTH_HELD_01 .. SYNTH_HELD_21)."""
    return [
        {
            "case_id": "SYNTH_HELD_01", "set": "held_out", "category": "layout_placement",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "static"},
            "text_elements": [{
                "text": "HỘI NGHỊ KHOA HỌC QUỐC TẾ 2026", "font_size": 52, "pos_norm": [0.15, 0.08],
                "style": "white_black_stroke_shadow", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_02", "set": "held_out", "category": "layout_placement",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "static"},
            "text_elements": [{
                "text": "DEMO WATERMARK - DO NOT COPY", "font_size": 40, "pos_norm": [0.10, 0.48],
                "style": "white_black_stroke", "alpha": 0.40, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_03", "set": "held_out", "category": "layout_placement",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "Hôm nay thời tiết thật là tuyệt vời", "font_size": 30, "pos_norm": [0.06, 0.84],
                "style": "white_yellow_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_04", "set": "held_out", "category": "layout_placement",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 75, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [{
                "text": "[TRỰC TIẾP] GIẢI BÓNG ĐÁ VÔ ĐỊCH QUỐC GIA", "font_size": 30, "pos_norm": [0.08, 0.85],
                "style": "white_black_stroke", "box_banner": True, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_05", "set": "held_out", "category": "layout_placement",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "fabric_linen", "camera_motion": "static"},
            "text_elements": [{
                "text": "© 2026 AI TEAM", "font_size": 12, "pos_norm": [0.06, 0.94],
                "style": "white_black_stroke", "alpha": 0.70, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_06", "set": "held_out", "category": "temporal_dynamics",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 75, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static"},
            "text_elements": [{
                "text": "XUẤT HIỆN CHỚP NHOÁNG", "font_size": 38, "pos_norm": [0.15, 0.50],
                "style": "white_black_stroke", "temporal_behavior": "fade", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_07", "set": "held_out", "category": "temporal_dynamics",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 90, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "static"},
            "text_elements": [{
                "text": "DỰ BÁO THỜI TIẾT: CÁC TỈNH BẮC BỘ TRỜI TIẾP TỤC CÓ MƯA RÀO VÀ DÔNG RẢI RÁC VÀO CHIỀU TỐI...",
                "font_size": 32, "pos_norm": [0.10, 0.90], "speed_norm": 0.012,
                "style": "white_black_stroke", "temporal_behavior": "ticker", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_08", "set": "held_out", "category": "temporal_dynamics",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 90, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "static"},
            "text_elements": [{
                "text": "Bước 1: Chuẩn bị nguyên liệu", "text_phase2": "Bước 2: Xử lý sơ chế",
                "jump_frame": 45, "font_size": 30, "pos_norm": [0.08, 0.80],
                "style": "white_black_stroke", "temporal_behavior": "jumping", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_09", "set": "held_out", "category": "layout_placement",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "wood_grain", "camera_motion": "static"},
            "text_elements": [
                {"text": "Dòng ngắn", "font_size": 30, "pos_norm": [0.10, 0.78], "style": "white_black_stroke", "is_overlay": True},
                {"text": "Đây là một dòng phụ đề rất dài chiếm gần hết chiều ngang của khung hình", "font_size": 24, "pos_norm": [0.05, 0.85], "style": "white_black_stroke", "is_overlay": True}
            ]
        },
        {
            "case_id": "SYNTH_HELD_10", "set": "held_out", "category": "temporal_dynamics",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 75, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "static", "scene_cut_frame": 39, "scene_b_texture": "burmester_mesh"},
            "text_elements": [{
                "text": "NỘI DUNG TRƯỚC KHI CẮT", "font_size": 32, "pos_norm": [0.10, 0.75],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_11", "set": "held_out", "category": "camera_motion",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "burmester_mesh", "camera_motion": "tilt_vertical"},
            "text_elements": [{
                "text": "ÂM THANH VÒM 3D STEREO", "font_size": 30, "pos_norm": [0.08, 0.82],
                "style": "yellow_karaoke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_12", "set": "held_out", "category": "camera_motion",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "CHƯƠNG MỤC SÁCH LỊCH SỬ", "font_size": 44, "pos_norm": [0.25, 0.45],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_13", "set": "held_out", "category": "camera_motion",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "fabric_linen", "camera_motion": "zoom"},
            "text_elements": [{
                "text": "LOGO-KÊNH", "font_size": 28, "pos_norm": [0.08, 0.10],
                "style": "white_black_stroke", "alpha": 0.60, "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_14", "set": "held_out", "category": "camera_motion",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "TỐC ĐỘ DI CHUYỂN CAO", "font_size": 42, "pos_norm": [0.15, 0.65],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_15", "set": "held_out", "category": "camera_motion",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "concrete_wall", "camera_motion": "diagonal"},
            "text_elements": [{
                "text": "HIỆU ỨNG CYBERPUNK", "font_size": 36, "pos_norm": [0.20, 0.50],
                "style": "cyan_purple_glow", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_16", "set": "held_out", "category": "short_words",
            "resolution": [1080, 1920], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "gradient_studio", "camera_motion": "static"},
            "text_elements": [
                {"text": "w", "font_size": 28, "pos_norm": [0.20, 0.25], "style": "white_black_stroke", "is_overlay": True},
                {"text": "ch", "font_size": 28, "pos_norm": [0.65, 0.40], "style": "white_black_stroke", "is_overlay": True},
                {"text": "ơi", "font_size": 28, "pos_norm": [0.30, 0.65], "style": "white_black_stroke", "is_overlay": True},
                {"text": "à", "font_size": 28, "pos_norm": [0.75, 0.80], "style": "white_black_stroke", "is_overlay": True}
            ]
        },
        {
            "case_id": "SYNTH_HELD_17", "set": "held_out", "category": "short_words",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "chalkboard", "camera_motion": "static"},
            "text_elements": [{
                "text": "Trường Đại Học Bách Khoa Hà Nội Đào Tạo Kỹ Sư Giỏi", "font_size": 22, "pos_norm": [0.04, 0.48],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_18", "set": "held_out", "category": "short_words",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "contract_document", "camera_motion": "tilt_vertical"},
            "text_elements": [{
                "text": "Ưu đãi 100% - Mã: #VIP2026 (Áp dụng 24/7!)", "font_size": 30, "pos_norm": [0.10, 0.45],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": True
            }]
        },
        {
            "case_id": "SYNTH_HELD_19", "set": "held_out", "category": "negative_controls",
            "resolution": [1280, 720], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "burmester_mesh", "camera_motion": "pan_horizontal"},
            "text_elements": []
        },
        {
            "case_id": "SYNTH_HELD_20", "set": "held_out", "category": "negative_controls",
            "resolution": [576, 1024], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "brick_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [{
                "text": "CAFE PHỐ XƯA - KÍNH CHÀO QUÝ KHÁCH", "font_size": 26, "pos_norm": [0.08, 0.35],
                "style": "white_black_stroke", "temporal_behavior": "static", "is_overlay": False
            }]
        },
        {
            "case_id": "SYNTH_HELD_21", "set": "held_out", "category": "negative_controls",
            "resolution": [1920, 1080], "fps": 30.0, "frame_count": 60, "target_scope": "overlay",
            "background": {"texture_type": "brick_wall", "camera_motion": "pan_horizontal"},
            "text_elements": [
                {"text": "CHƯƠNG TRÌNH KHÁM PHÁ ẨM THỰC", "font_size": 36, "pos_norm": [0.15, 0.85], "style": "white_black_stroke", "is_overlay": True},
                {"text": "NHÀ HÀNG HẢI SẢN TƯƠI SỐNG", "font_size": 32, "pos_norm": [0.15, 0.25], "style": "white_black_stroke", "is_overlay": False}
            ]
        }
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BENCHMARK GENERATOR ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class SyntheticBenchmarkGenerator:
    """Điều phối sinh toàn bộ ca kiểm chuẩn tất định, streaming frame, kiểm soát RAM."""

    def __init__(self, output_root: Path, seed: int = 42):
        self.output_root = output_root
        self.seed = seed
        self.output_root.mkdir(parents=True, exist_ok=True)

    def generate_case(self, case_spec: Dict[str, Any]) -> None:
        case_id = case_spec["case_id"]
        set_name = case_spec["set"]
        case_dir = self.output_root / set_name / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        mask_dir = case_dir / "mask_ground_truth"
        mask_dir.mkdir(parents=True, exist_ok=True)

        w, h = case_spec["resolution"]
        fps = case_spec["fps"]
        total_frames = case_spec["frame_count"]

        # Deterministic seed per case
        case_seed = self.seed + sum(ord(c) for c in case_id)
        random.seed(case_seed)
        np.random.seed(case_seed)

        bg_spec = case_spec["background"]
        motion_sim = MotionSimulator(
            target_w=w, target_h=h,
            texture_type=bg_spec.get("texture_type", "gradient_studio"),
            motion_type=bg_spec.get("camera_motion", "static"),
            scene_cut_frame=bg_spec.get("scene_cut_frame"),
            scene_b_texture=bg_spec.get("scene_b_texture")
        )
        overlay_engine = TextOverlayEngine(target_w=w, target_h=h)

        clean_path = case_dir / "clean.mp4"
        text_path = case_dir / "text.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        clean_writer = cv2.VideoWriter(str(clean_path), fourcc, fps, (w, h))
        text_writer = cv2.VideoWriter(str(text_path), fourcc, fps, (w, h))

        text_pixels_sum = 0
        text_elements = case_spec.get("text_elements", [])

        for f_idx in range(total_frames):
            clean_frame = motion_sim.get_clean_frame(f_idx, total_frames)

            # Negative control without text
            if not text_elements:
                clean_writer.write(clean_frame)
                text_writer.write(clean_frame)
                zero_mask = np.zeros((h, w), dtype=np.uint8)
                cv2.imwrite(str(mask_dir / f"frame_{f_idx:04d}.png"), zero_mask)
                continue

            frame_rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            frame_mask = np.zeros((h, w), dtype=np.uint8)

            for elem in text_elements:
                behavior = elem.get("temporal_behavior", "static")
                alpha = elem.get("alpha", 1.0)
                pos = list(elem["pos_norm"])
                box_banner = elem.get("box_banner", False)

                text_to_show = elem["text"]
                if behavior == "fade":
                    ramp_f = int(total_frames * 0.25)
                    if f_idx < ramp_f:
                        alpha = alpha * (f_idx / max(1, ramp_f))
                    elif f_idx > total_frames - ramp_f:
                        alpha = alpha * ((total_frames - f_idx) / max(1, ramp_f))

                elif behavior == "ticker":
                    scroll_speed = elem.get("speed_norm", 0.010)
                    pos[0] = 1.0 - (f_idx * scroll_speed)

                elif behavior == "jumping":
                    jump_frame = elem.get("jump_frame", total_frames // 2)
                    text_to_show = elem.get("text_phase2", elem["text"]) if f_idx >= jump_frame else elem["text"]

                elem_rgba, elem_mask = overlay_engine.render_element(
                    text=text_to_show,
                    font_size=elem["font_size"],
                    pos_norm=(pos[0], pos[1]),
                    style=elem.get("style", "white_black_stroke"),
                    alpha=alpha,
                    box_banner=box_banner
                )
                frame_rgba.alpha_composite(elem_rgba)
                frame_mask = np.maximum(frame_mask, np.array(elem_mask))

            text_frame = overlay_engine.blend_onto_frame(clean_frame, frame_rgba)

            clean_writer.write(clean_frame)
            text_writer.write(text_frame)
            cv2.imwrite(str(mask_dir / f"frame_{f_idx:04d}.png"), frame_mask)
            text_pixels_sum += int(np.count_nonzero(frame_mask))

        clean_writer.release()
        text_writer.release()

        case_spec["ground_truth_stats"] = {
            "total_frames": total_frames,
            "mean_text_pixels_per_frame": int(text_pixels_sum / max(1, total_frames)),
            "mean_coverage_ratio": float(text_pixels_sum / (total_frames * w * h)) if total_frames > 0 else 0.0,
        }
        case_spec["expected_metrics"] = {
            "residual_ocr_words_max": 0,
            "reconstruction_ssim_min": 0.95 if "pan" not in bg_spec.get("camera_motion", "") else 0.92,
            "ssim_outside_mask_min": 0.99,
            "psnr_outside_mask_delta_max_db": 0.5,
            "temporal_inconsistency_ratio_max": 1.20,
            "scene_text_preserved": True
        }

        with open(case_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(case_spec, f, ensure_ascii=False, indent=2)

        print(f"[{case_spec['set'].upper()}] Successfully generated {case_id} ({w}x{h}, {total_frames} frames)")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CLI INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic Synthetic Benchmark Generator (42 Cases)")
    parser.add_argument("--set", choices=["tuning", "held_out", "all"], default="all",
                        help="Partition to generate: tuning, held_out, or all")
    parser.add_argument("--case", type=str, default=None, help="Generate a specific case ID (e.g. SYNTH_TUNE_01)")
    parser.add_argument("--output-dir", type=str, default="benchmarks/synthetic", help="Output directory path")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    return parser


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()

    output_root = Path(args.output_dir)
    generator = SyntheticBenchmarkGenerator(output_root=output_root, seed=args.seed)

    tuning_specs = get_tuning_cases_specs()
    held_out_specs = get_held_out_cases_specs()

    all_specs: List[Dict[str, Any]] = []
    if args.set in ["tuning", "all"]:
        all_specs.extend(tuning_specs)
    if args.set in ["held_out", "all"]:
        all_specs.extend(held_out_specs)

    if args.case:
        all_specs = [s for s in all_specs if s["case_id"] == args.case]
        if not all_specs:
            print(f"[ERROR] Case {args.case} not found", file=sys.stderr)
            return 1

    print(f"[*] Generating {len(all_specs)} synthetic benchmark cases (set={args.set}, seed={args.seed})...")
    for spec in all_specs:
        generator.generate_case(spec)

    print(f"[OK] Benchmark generation complete. Target root: {output_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
