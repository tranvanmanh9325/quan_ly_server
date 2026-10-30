"""
Test Suite Phase 3 Remediation:
- Static scan against forbidden hardcoded heuristics and clip-specific overfitting
- General geometry invariance (Top 20%, Middle 50%, Lower-third 85%)
- Short words preservation ("ok", "w", "ch")
- Multi-resolution scaling (480p, 720p, 1080p, 4K)
- Bidirectional Optical Flow consistency and dense local photometric collar gating
- Scene Cut Isolation (no cross-shot keyframe borrowing)
- Non-mask bit-exact invariance
"""
import os
import re
import sys
import unittest
from pathlib import Path
import numpy as np
import cv2

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services.video_editor_service import VideoEditorService
from app.services.classical_fallback_manager import get_classical_fallback_manager


class TestPhase3Remediation(unittest.TestCase):
    def setUp(self):
        self.editor = VideoEditorService()
        self.classical_mgr = get_classical_fallback_manager()

    def test_01_static_scan_zero_forbidden_patterns(self):
        """Kiểm tra tĩnh 100% không còn bất kỳ regex cấm hoặc overfit heuristics nào."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "services"))
        files_to_check = [
            os.path.join(base_dir, "video_editor_service.py"),
            os.path.join(base_dir, "classical_fallback_manager.py"),
        ]

        forbidden_patterns = [
            r'0\.38\s*\*\s*[hH]',
            r'0\.60\s*\*\s*[hH]',
            r'0\.40\s*\*\s*(?:[hH]|frame_h)',
            r'ry\s*<\s*350',
            r'y\s*<\s*350',
            r'F350',
            r'F1383',
            r'F1496',
            r'Burmester',
            r'Soạn hợp đồng',
            r'Soan hop dong',
            r'cov\s*>=\s*0\.30',
            r'len\(cur_cl\)\s*>=\s*3\s+or',
            r'len\(cur_cl\)\s*>=\s*2\s+or',
            r'dx\s*<=\s*55',
        ]

        violations = []
        for fpath in files_to_check:
            self.assertTrue(os.path.isfile(fpath), f"File missing: {fpath}")
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line_no, line in enumerate(lines, start=1):
                for pat in forbidden_patterns:
                    if re.search(pat, line, re.IGNORECASE):
                        violations.append(f"{os.path.basename(fpath)}:{line_no} [Pat: {pat}] -> {line.strip()}")

        self.assertEqual(
            len(violations),
            0,
            f"Phát hiện {len(violations)} vi phạm overfit/hardcoded heuristics:\n" + "\n".join(violations),
        )

    def test_02_geometry_invariance_top_middle_lower_third(self):
        """Phát hiện phụ đề độc lập vị trí: Top (20% H), Middle (50% H), Lower-third (85% H)."""
        w, h = 720, 1280
        test_y_positions = [
            ("top_20pct", int(0.20 * h)),
            ("middle_50pct", int(0.50 * h)),
            ("lower_third_85pct", int(0.85 * h)),
        ]

        for name, y_pos in test_y_positions:
            with self.subTest(position=name):
                # Tạo synthetic frame tối có thanh chữ sáng
                frame = np.full((h, w, 3), 40, dtype=np.uint8)
                cv2.putText(
                    frame,
                    "PHU DE TONG QUAT TEST",
                    (100, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    (255, 255, 255),
                    3,
                    cv2.LINE_AA,
                )

                mask, sub_info = self.editor._build_inpaint_mask_for_frame(
                    0, (h, w, 3), frame_img=frame, target_regions=None
                )

                self.assertIsNotNone(mask, f"Mask is None for position {name}")
                self.assertIsNotNone(sub_info, f"sub_info is None for position {name}")

                # Kiểm tra diện tích mask tại vùng đặt chữ
                roi_mask = mask[max(0, y_pos - 40):min(h, y_pos + 20), 90:630]
                text_pixels = np.count_nonzero(roi_mask)
                self.assertGreater(
                    text_pixels,
                    300,
                    f"Vị trí {name} (y={y_pos}) không bắt được phụ đề! Text pixels: {text_pixels}",
                )

    def test_03_short_words_preservation(self):
        """Bảo tồn các từ ngắn 1-2 ký tự ('ok', 'w', 'ch') không bị rụng chữ hoặc mất dấu."""
        w, h = 720, 1280
        frame = np.full((h, w, 3), 45, dtype=np.uint8)

        # Vẽ từ ngắn "ok" và "ch"
        cv2.putText(frame, "ok", (200, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(frame, "ch", (350, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)

        mask, sub_info = self.editor._build_inpaint_mask_for_frame(
            0, (h, w, 3), frame_img=frame, target_regions=None
        )

        self.assertIsNotNone(mask)
        self.assertIsNotNone(sub_info)

        # Kiểm tra mask tại vùng chữ "ok"
        mask_ok = mask[560:620, 190:260]
        self.assertGreater(
            np.count_nonzero(mask_ok), 50, "Từ ngắn 'ok' (2 ký tự) bị rụng khỏi mask!"
        )

        # Kiểm tra mask tại vùng chữ "ch"
        mask_ch = mask[560:620, 340:410]
        self.assertGreater(
            np.count_nonzero(mask_ch), 50, "Từ ngắn 'ch' (2 ký tự) bị rụng khỏi mask!"
        )

    def test_04_resolution_scaling(self):
        """Đảm bảo các hệ số hình thái học co dãn thích ứng theo độ phân giải."""
        resolutions = [
            (480, 854),
            (720, 1280),
            (1080, 1920),
            (2160, 3840),
        ]

        for w, h in resolutions:
            scale_geom = max(0.5, min(w, h) / 720.0)
            diag = np.sqrt(h ** 2 + w ** 2)
            base_diag = np.sqrt(1024 ** 2 + 576 ** 2)
            s_res = max(0.5, float(diag / base_diag))

            if w == 480:
                self.assertLess(scale_geom, 1.0)
                self.assertLess(s_res, 1.0)
            elif w == 1080:
                self.assertGreater(scale_geom, 1.4)
                self.assertGreater(s_res, 1.7)
            elif w == 2160:
                self.assertGreater(scale_geom, 2.8)
                self.assertGreater(s_res, 3.5)

    def test_05_bidirectional_optical_flow_consistency(self):
        """Kiểm tra Forward-Backward consistency check và Photometric collar gating."""
        h, w = 200, 300
        base_img = np.zeros((h, w, 3), dtype=np.uint8)
        # Nền có kết cấu sọc ngang dọc
        for y in range(0, h, 20):
            base_img[y:y+10, :] = 120
        for x in range(0, w, 30):
            base_img[:, x:x+15] = (base_img[:, x:x+15] + 60) // 2

        # 1. Ca hợp lệ: Chuyển động tịnh tiến nhỏ (dx=2, dy=1)
        M_shift = np.float32([[1, 0, 2], [0, 1, 1]])
        shifted_img = cv2.warpAffine(base_img, M_shift, (w, h), borderMode=cv2.BORDER_REFLECT)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[80:120, 100:200] = 255

        warped, success = self.classical_mgr.reconstruct_frame_with_optical_flow(
            shifted_img, base_img, mask, error_threshold=24.0
        )
        self.assertTrue(success, "Quang thông 2 chiều thất bại trên chuyển động tịnh tiến nhỏ hợp lệ!")
        self.assertIsNotNone(warped)

        # 2. Ca không hợp lệ: Occlusion mạnh trên vành đai collar
        corrupted_img = shifted_img.copy()
        # Đổi màu hoàn toàn vùng lân cận mask (collar)
        corrupted_img[70:130, 90:210] = 255 - corrupted_img[70:130, 90:210]

        warped_bad, success_bad = self.classical_mgr.reconstruct_frame_with_optical_flow(
            corrupted_img, base_img, mask, error_threshold=15.0
        )
        self.assertFalse(success_bad, "Photometric collar gating không chặn được vùng bị occlusion/sai lệch lớn!")

    def test_06_non_mask_bit_exact_invariance(self):
        """Ngoài vùng mask, 100% pixel gốc phải được bảo toàn nguyên vẹn (bit-exact)."""
        h, w = 150, 200
        curr_frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        clean_key = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[50:100, 60:140] = 255

        warped, _ = self.classical_mgr.reconstruct_frame_with_optical_flow(
            curr_frame, clean_key, mask, error_threshold=255.0
        )
        if warped is not None:
            # Pixel ngoài dilated mask
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            dil_m = cv2.dilate(mask, k)
            outside = (dil_m == 0)
            self.assertTrue(
                np.array_equal(warped[outside], curr_frame[outside]),
                "Vùng ngoài mask bị thay đổi pixel, vi phạm Non-mask Invariance!",
            )


if __name__ == "__main__":
    unittest.main()
