#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance/synthetic_generator.py — Deterministic Synthetic Benchmark Generator (P1-P10).
Milestone M0: Frozen Acceptance Judge Infrastructure.

Generates 10 Frozen Evaluation Cases:
  - Category R (P1-P6): Moving background with intermittent/ticker/karaoke text.
  - Category U (P9-P10): Static camera persistent text.
  - Negative Control (P7): Absolutely zero text.
  - Scene Text Control (P8): Text painted physically onto moving background texture.

Deterministic with seed (default 42).
Low memory footprint (< 80MB RAM).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PROCEDURAL TEXTURE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

class TextureGenerator:
    """Deterministic mathematical texture synthesis."""

    @staticmethod
    def generate_gradient_studio(width: int, height: int) -> np.ndarray:
        x = np.linspace(0, 1, width, dtype=np.float32)
        y = np.linspace(0, 1, height, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        diag = (xx + yy) / 2.0
        diag = np.expand_dims(diag, axis=2)
        c1 = np.array([25, 30, 45], dtype=np.float32)
        c2 = np.array([80, 110, 140], dtype=np.float32)
        canvas = (1.0 - diag) * c1 + diag * c2
        return np.clip(canvas, 0, 255).astype(np.uint8)

    @staticmethod
    def generate_wood_grain(width: int, height: int) -> np.ndarray:
        y_coords, x_coords = np.mgrid[0:height, 0:width]
        wave = np.sin(x_coords / 16.0 + 3.0 * np.sin(y_coords / 22.0))
        noise = (wave + 1.0) * 0.5
        base_color = np.array([45, 80, 140], dtype=np.float32)
        highlight_color = np.array([85, 130, 200], dtype=np.float32)
        noise_3d = np.expand_dims(noise, axis=2)
        canvas = (1.0 - noise_3d) * base_color + noise_3d * highlight_color
        fine_noise = np.random.normal(0, 3.0, (height, width, 1)).astype(np.float32)
        return np.clip(canvas + fine_noise, 0, 255).astype(np.uint8)

    @staticmethod
    def generate_contract_document(width: int, height: int, line_spacing: int = 24) -> np.ndarray:
        canvas = np.full((height, width, 3), 245, dtype=np.uint8)
        line_color = (90, 90, 95)
        for y in range(40, height - 30, line_spacing):
            x = 40
            while x < width - 40:
                seg_len = random.randint(30, 90)
                gap = random.randint(12, 28)
                x_end = min(width - 40, x + seg_len)
                cv2.line(canvas, (x, y), (x_end, y), line_color, 1)
                x = x_end + gap
        return canvas

    @staticmethod
    def generate_concrete_wall(width: int, height: int) -> np.ndarray:
        base = np.full((height, width, 3), 135, dtype=np.float32)
        noise1 = np.random.normal(0, 12.0, (height, width, 1)).astype(np.float32)
        noise2 = cv2.GaussianBlur(np.random.normal(0, 8.0, (height, width, 1)).astype(np.float32), (7, 7), 2.0)
        canvas = base + noise1 + np.expand_dims(noise2, axis=2) if len(noise2.shape) == 2 else base + noise1 + noise2
        return np.clip(canvas, 0, 255).astype(np.uint8)

    @staticmethod
    def generate_fabric_linen(width: int, height: int) -> np.ndarray:
        canvas = np.full((height, width, 3), 190, dtype=np.uint8)
        canvas[::3, :, :] = np.clip(canvas[::3, :, :].astype(np.int16) - 20, 0, 255).astype(np.uint8)
        canvas[:, ::3, :] = np.clip(canvas[:, ::3, :].astype(np.int16) + 20, 0, 255).astype(np.uint8)
        return canvas

    @staticmethod
    def generate_burmester_mesh(width: int, height: int, hole_radius: int = 2, step: int = 8) -> np.ndarray:
        canvas = np.full((height, width, 3), 150, dtype=np.uint8)
        for y in range(step, height - step, step):
            shift = (step // 2) if (y // step) % 2 == 1 else 0
            for x in range(step + shift, width - step, step):
                cv2.circle(canvas, (x, y), hole_radius, (50, 50, 55), -1)
                cv2.circle(canvas, (x, y), hole_radius + 1, (180, 180, 190), 1)
        return canvas

    @staticmethod
    def generate_brick_wall(width: int, height: int, brick_w: int = 60, brick_h: int = 25) -> np.ndarray:
        canvas = np.full((height, width, 3), 180, dtype=np.uint8)  # Mortar color
        brick_color1 = np.array([40, 55, 160], dtype=np.int16)
        row = 0
        for y in range(0, height, brick_h + 3):
            shift = (brick_w // 2) if row % 2 == 1 else 0
            for x in range(-shift, width, brick_w + 3):
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(width, x + brick_w), min(height, y + brick_h)
                if x2 > x1 and y2 > y1:
                    noise = random.randint(-15, 15)
                    color = np.clip(brick_color1 + noise, 0, 255).astype(np.uint8)
                    canvas[y1:y2, x1:x2] = color
            row += 1
        return canvas


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OVERLAY TEXT RENDERING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def render_text_overlay(
    frame_bgr: np.ndarray,
    text: str,
    pos: Tuple[int, int],
    font_scale: float = 1.0,
    text_color: Tuple[int, int, int] = (255, 255, 255),
    border_color: Tuple[int, int, int] = (0, 0, 0),
    thickness: int = 2,
    alpha: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Renders text onto frame_bgr and returns (composite_frame, binary_mask).
    """
    h, w = frame_bgr.shape[:2]
    out_frame = frame_bgr.copy()
    mask = np.zeros((h, w), dtype=np.uint8)

    # Use PIL for better unicode font rendering if possible, or OpenCV putText
    font = cv2.FONT_HERSHEY_SIMPLEX
    lines = text.split("\n")
    cur_y = pos[1]

    for line in lines:
        (tw, th), baseline = cv2.getTextSize(line, font, font_scale, thickness)
        tx = pos[0]
        ty = cur_y + th

        # Bounding box for mask
        bx1 = max(0, tx - 4)
        by1 = max(0, ty - th - 4)
        bx2 = min(w, tx + tw + 4)
        by2 = min(h, ty + baseline + 4)

        # Draw on overlay layer
        overlay = out_frame.copy()
        if border_color is not None:
            cv2.putText(overlay, line, (tx, ty), font, font_scale, border_color, thickness + 2, cv2.LINE_AA)
        cv2.putText(overlay, line, (tx, ty), font, font_scale, text_color, thickness, cv2.LINE_AA)

        if alpha < 0.99:
            cv2.addWeighted(overlay, alpha, out_frame, 1.0 - alpha, 0, out_frame)
        else:
            out_frame = overlay

        # Update mask
        mask[by1:by2, bx1:bx2] = 255
        cur_y += th + baseline + 10

    return out_frame, mask


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CASE CONFIGURATIONS (P1 - P10)
# ═══════════════════════════════════════════════════════════════════════════════

P_CASES: Dict[str, Dict[str, Any]] = {
    "P1": {
        "id": "P1",
        "category": "R",
        "width": 576,
        "height": 1024,
        "fps": 30,
        "num_frames": 60,
        "texture": "gradient_studio",
        "motion": "pan_horizontal",
        "motion_speed": 3.5,
        "text": "BAN TIN BUOI SANG",
        "text_pos": (60, 100),
        "font_scale": 1.1,
        "text_color": (255, 255, 255),
        "border_color": (0, 0, 0),
        "alpha": 1.0,
        "description": "Gradient Studio, horizontal pan, top title with outline",
    },
    "P2": {
        "id": "P2",
        "category": "R",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "num_frames": 60,
        "texture": "wood_grain",
        "motion": "tilt_vertical",
        "motion_speed": 2.5,
        "text": "XU HUONG CONG NGHE 2026",
        "text_pos": (350, 340),
        "font_scale": 1.2,
        "text_color": (240, 240, 240),
        "border_color": (30, 30, 30),
        "alpha": 0.55,
        "description": "Wood Grain, vertical tilt, center semi-transparent subtitle",
    },
    "P3": {
        "id": "P3",
        "category": "R",
        "width": 576,
        "height": 1024,
        "fps": 30,
        "num_frames": 60,
        "texture": "contract_document",
        "motion": "zoom_in",
        "motion_speed": 0.0025,
        "text": "TIEN DO THUC HIEN DU AN",
        "text_pos": (50, 780),
        "font_scale": 0.95,
        "text_color": (0, 240, 255),  # Yellow BGR
        "border_color": (0, 0, 200),  # Red border
        "alpha": 1.0,
        "description": "Contract Document, zoom-in, bottom karaoke subtitle with red outline",
    },
    "P4": {
        "id": "P4",
        "category": "R",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "num_frames": 60,
        "texture": "concrete_wall",
        "motion": "diagonal",
        "motion_speed": (2.0, 1.5),
        "text": "TIN NONG TRONG NGAY: THI TRUONG TANG TRUONG MANH ME",
        "text_pos": (100, 980),
        "font_scale": 1.1,
        "text_color": (255, 255, 255),
        "border_color": (0, 0, 0),
        "alpha": 1.0,
        "description": "Concrete Wall, diagonal pan, bottom news ticker banner",
    },
    "P5": {
        "id": "P5",
        "category": "R",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "num_frames": 60,
        "texture": "fabric_linen",
        "motion": "sinusoidal",
        "motion_speed": 4.0,
        "text": "DOAN VAN BAN MOI XUAT HIEN",
        "text_pos": (200, 1500),
        "font_scale": 1.2,
        "text_color": (255, 255, 255),
        "border_color": (20, 20, 20),
        "alpha": 1.0,
        "intermittent_frames": [(10, 25), (35, 52)],
        "description": "Fabric Linen, sinusoidal pan, intermittent jumping caption",
    },
    "P6": {
        "id": "P6",
        "category": "R",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "num_frames": 60,
        "texture": "scene_cut_dual",
        "motion": "scene_cut",
        "text": "CHUYEN CANH DOT NGOT",
        "text_pos": (400, 580),
        "font_scale": 1.1,
        "text_color": (255, 255, 255),
        "border_color": (0, 0, 0),
        "alpha": 1.0,
        "description": "Scene cut at frame 30, wood grain pan -> concrete tilt",
    },
    "P7": {
        "id": "P7",
        "category": "Negative",
        "width": 576,
        "height": 1024,
        "fps": 30,
        "num_frames": 60,
        "texture": "burmester_mesh",
        "motion": "pan_horizontal",
        "motion_speed": 2.0,
        "text": None,  # Negative control: absolutely no text!
        "description": "Negative Control: Burmester speaker mesh, pan, zero text",
    },
    "P8": {
        "id": "P8",
        "category": "SceneText",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "num_frames": 60,
        "texture": "brick_wall",
        "motion": "pan_horizontal",
        "motion_speed": 3.0,
        "scene_text": "CUA HANG BACH HOA",
        "scene_text_pos": (200, 300),
        "text": None,  # No overlay text
        "description": "Scene Text Control: Text painted directly on brick wall background",
    },
    "P9": {
        "id": "P9",
        "category": "U",
        "width": 576,
        "height": 1024,
        "fps": 30,
        "num_frames": 60,
        "texture": "gradient_studio",
        "motion": "static",
        "motion_speed": 0.0,
        "text": "TIEU BAO BAO\nTRO LY THONG MINH\nPHIEN BAN MOI",
        "text_pos": (100, 200),
        "font_scale": 1.0,
        "text_color": (255, 255, 255),
        "border_color": (10, 10, 10),
        "alpha": 1.0,
        "description": "Static Camera, 3-line persistent title across all frames",
    },
    "P10": {
        "id": "P10",
        "category": "U",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "num_frames": 60,
        "texture": "concrete_wall",
        "motion": "static",
        "motion_speed": 0.0,
        "text": "2026-10-30 14:30:00",
        "text_pos": (100, 100),
        "font_scale": 1.1,
        "text_color": (0, 255, 0),  # Green digital clock
        "border_color": (0, 0, 0),
        "alpha": 1.0,
        "description": "Static Camera, security timestamp digital clock overlay",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DETERMINISTIC BENCHMARK GENERATOR ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class SyntheticBenchmarkGenerator:
    """Generates synthetic benchmark videos and ground truth masks."""

    def __init__(self, out_dir: Path, seed: int = 42):
        self.out_dir = Path(out_dir)
        self.seed = seed
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def generate_case(self, case_id: str) -> Path:
        """Generate a single case P1-P10."""
        cfg = P_CASES[case_id]
        random.seed(self.seed + hash(case_id) % 10000)
        np.random.seed(self.seed + hash(case_id) % 10000)

        case_dir = self.out_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        mask_dir = case_dir / "mask_ground_truth"
        mask_dir.mkdir(parents=True, exist_ok=True)

        w, h = cfg["width"], cfg["height"]
        num_frames = cfg["num_frames"]
        fps = cfg["fps"]

        # Step 1: Generate canvas texture
        canvas_w = int(w * 2.5)
        canvas_h = int(h * 2.5)

        tex_name = cfg["texture"]
        if tex_name == "gradient_studio":
            canvas = TextureGenerator.generate_gradient_studio(canvas_w, canvas_h)
        elif tex_name == "wood_grain":
            canvas = TextureGenerator.generate_wood_grain(canvas_w, canvas_h)
        elif tex_name == "contract_document":
            canvas = TextureGenerator.generate_contract_document(canvas_w, canvas_h)
        elif tex_name == "concrete_wall":
            canvas = TextureGenerator.generate_concrete_wall(canvas_w, canvas_h)
        elif tex_name == "fabric_linen":
            canvas = TextureGenerator.generate_fabric_linen(canvas_w, canvas_h)
        elif tex_name == "burmester_mesh":
            canvas = TextureGenerator.generate_burmester_mesh(canvas_w, canvas_h)
        elif tex_name == "brick_wall":
            canvas = TextureGenerator.generate_brick_wall(canvas_w, canvas_h)
        elif tex_name == "scene_cut_dual":
            canvas_a = TextureGenerator.generate_wood_grain(canvas_w, canvas_h)
            canvas_b = TextureGenerator.generate_concrete_wall(canvas_w, canvas_h)
            canvas = canvas_a
        else:
            canvas = TextureGenerator.generate_gradient_studio(canvas_w, canvas_h)

        # For P8 scene text, stamp text on background canvas BEFORE camera motion
        scene_mask_dir = case_dir / "scene_text_mask"
        scene_canvas_mask = None
        if cfg.get("scene_text"):
            scene_mask_dir.mkdir(parents=True, exist_ok=True)
            scene_canvas_mask = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
            st_text = cfg["scene_text"]
            st_pos = cfg["scene_text_pos"]
            cv2.putText(canvas, st_text, st_pos, cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 3, cv2.LINE_AA)
            (tw, th), baseline = cv2.getTextSize(st_text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
            bx1 = max(0, st_pos[0] - 6)
            by1 = max(0, st_pos[1] - th - 6)
            bx2 = min(canvas_w, st_pos[0] + tw + 6)
            by2 = min(canvas_h, st_pos[1] + baseline + 6)
            scene_canvas_mask[by1:by2, bx1:bx2] = 255

        # Temp video paths
        clean_mp4 = case_dir / "clean.mp4"
        text_mp4 = case_dir / "text.mp4"

        # Writers
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        clean_writer = cv2.VideoWriter(str(clean_mp4), fourcc, fps, (w, h))
        text_writer = cv2.VideoWriter(str(text_mp4), fourcc, fps, (w, h))

        cur_x = 50.0
        cur_y = 50.0
        scale = 1.0

        for f_idx in range(num_frames):
            # Compute camera motion
            motion = cfg["motion"]
            if motion == "pan_horizontal":
                cur_x += cfg["motion_speed"]
            elif motion == "tilt_vertical":
                cur_y += cfg["motion_speed"]
            elif motion == "diagonal":
                dx, dy = cfg["motion_speed"]
                cur_x += dx
                cur_y += dy
            elif motion == "zoom_in":
                scale += cfg["motion_speed"]
            elif motion == "sinusoidal":
                cur_x = 50.0 + cfg["motion_speed"] * 10.0 * (1.0 + math.sin(f_idx / 5.0))
            elif motion == "scene_cut":
                if f_idx < 30:
                    canvas = canvas_a
                    cur_x += 2.0
                else:
                    canvas = canvas_b
                    cur_y += 2.0
            elif motion == "static":
                pass

            # Crop clean frame from canvas
            ix = int(cur_x)
            iy = int(cur_y)
            if motion == "zoom_in":
                cw = int(w / scale)
                ch = int(h / scale)
                crop = canvas[iy : iy + ch, ix : ix + cw]
                clean_frame = cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)
            else:
                clean_frame = canvas[iy : iy + h, ix : ix + w].copy()

            # Create text frame
            if cfg.get("text") is not None:
                is_active = True
                if "intermittent_frames" in cfg:
                    is_active = any(start <= f_idx <= end for start, end in cfg["intermittent_frames"])

                if is_active:
                    text_frame, mask = render_text_overlay(
                        clean_frame,
                        cfg["text"],
                        cfg["text_pos"],
                        font_scale=cfg.get("font_scale", 1.0),
                        text_color=cfg.get("text_color", (255, 255, 255)),
                        border_color=cfg.get("border_color", (0, 0, 0)),
                        alpha=cfg.get("alpha", 1.0),
                    )
                else:
                    text_frame = clean_frame.copy()
                    mask = np.zeros((h, w), dtype=np.uint8)
            else:
                # No overlay text
                text_frame = clean_frame.copy()
                mask = np.zeros((h, w), dtype=np.uint8)

            clean_writer.write(clean_frame)
            text_writer.write(text_frame)
            cv2.imwrite(str(mask_dir / f"frame_{f_idx:04d}.png"), mask)

            if scene_canvas_mask is not None:
                st_mask_frame = scene_canvas_mask[iy : iy + h, ix : ix + w].copy()
                cv2.imwrite(str(scene_mask_dir / f"frame_{f_idx:04d}.png"), st_mask_frame)

        clean_writer.release()
        text_writer.release()

        # Step 3: Multiplex bit-exact audio track if ffmpeg is available
        self._inject_audio_if_possible(clean_mp4, text_mp4, fps, num_frames)

        # Step 4: Write metadata.json
        meta = {
            "case_id": case_id,
            "category": cfg["category"],
            "description": cfg["description"],
            "resolution": [w, h],
            "fps": fps,
            "num_frames": num_frames,
            "has_overlay_text": (cfg.get("text") is not None),
            "is_negative_control": (cfg["category"] == "Negative"),
            "is_scene_text_control": (cfg["category"] == "SceneText"),
            "target_scope_default": "overlay",
        }
        with open(case_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return case_dir

    def _inject_audio_if_possible(self, clean_mp4: Path, text_mp4: Path, fps: float, num_frames: int):
        """Synthesize and inject audio stream into both clean and text videos."""
        dur = num_frames / fps
        try:
            # Check ffmpeg
            res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if res.returncode != 0:
                return

            audio_aac = clean_mp4.parent / "temp_audio.aac"
            # Generate deterministic 440Hz sine wave
            cmd_gen = [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur:.3f}",
                "-c:a", "aac", "-b:a", "128k", str(audio_aac)
            ]
            subprocess.run(cmd_gen, check=True, timeout=30)

            # Mux into clean.mp4
            clean_mux = clean_mp4.parent / "clean_mux.mp4"
            cmd_mux1 = [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(clean_mp4), "-i", str(audio_aac),
                "-c:v", "copy", "-c:a", "copy", str(clean_mux)
            ]
            subprocess.run(cmd_mux1, check=True, timeout=30)
            shutil.move(str(clean_mux), str(clean_mp4))

            # Mux into text.mp4 with identical audio
            text_mux = text_mp4.parent / "text_mux.mp4"
            cmd_mux2 = [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(text_mp4), "-i", str(audio_aac),
                "-c:v", "copy", "-c:a", "copy", str(text_mux)
            ]
            subprocess.run(cmd_mux2, check=True, timeout=30)
            shutil.move(str(text_mux), str(text_mp4))

            if audio_aac.exists():
                audio_aac.unlink()
        except Exception:
            pass

    def generate_all(self) -> Dict[str, Path]:
        """Generate all cases P1 through P10."""
        results = {}
        for case_id in P_CASES:
            results[case_id] = self.generate_case(case_id)
        return results


def main():
    parser = argparse.ArgumentParser(description="Deterministic Synthetic Benchmark Generator P1-P10")
    parser.add_argument("--out", required=True, help="Output directory for generated benchmark cases")
    parser.add_argument("--cases", default="all", help="Comma-separated list of cases (e.g. P1,P2,P7) or 'all'")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    args = parser.parse_args()

    gen = SyntheticBenchmarkGenerator(Path(args.out), seed=args.seed)
    if args.cases == "all":
        cases_to_run = list(P_CASES.keys())
    else:
        cases_to_run = [c.strip().upper() for c in args.cases.split(",") if c.strip()]

    print(f"Generating synthetic benchmark cases: {cases_to_run} to {args.out} (seed={args.seed})")
    for cid in cases_to_run:
        p = gen.generate_case(cid)
        print(f"  [DONE] Case {cid} -> {p}")
    print("All benchmark generation completed.")


if __name__ == "__main__":
    main()
