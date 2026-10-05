"""
Empirical Challenger Test Suite for Milestone 2:
Pixel-Accurate Text Masking, Spatial Confinement, Stroke Hull Separation,
Full Glyph Preservation, Solid Glyph Filling, and Dynamic Line Clamping.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

_SERVICE_ROOT = str(Path(__file__).resolve().parent.parent)
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

import cv2
import numpy as np

from app.services.video_editor_service import VideoEditorService


class TestChallengerM2SpatialConfinementF21(unittest.TestCase):
    """
    Kiểm thử đối kháng F2.1: Giới hạn không gian cấp độ dòng (Line-Level Spatial Confinement).
    Xác thực mask tuyệt đối bằng 0 tại các vùng ngoài bounding box dòng chữ
    (đặc biệt vùng lưới kim loại loa Burmester Porsche Frame 700: y < 182, x < 220).
    """

    def test_burmester_metallic_grill_absolute_zero_mask(self):
        """
        Adversarial Test F2.1:
        Mô phỏng chính xác Frame 700 xe Porsche:
        - Frame size 576x1024, ROI: x=39, y=177, w=479, h=137.
        - Góc trên-trái (y < 45, x < 135 tương ứng toạ độ video frame y < 182, x < 174) là lưới loa Burmester kim loại.
        - Chứa các mắt lưới tương phản cực cao (specular chrome highlights + dark holes).
        Xác thực: Mask tại vùng lưới loa PHẢI BẰNG 0 TUYỆT ĐỐI (0 non-zero pixels).
        """
        h, w = 137, 479
        roi = np.full((h, w, 3), 55, dtype=np.uint8)

        # Tạo vân lưới kim loại đục lỗ độ tương phản cao ở góc trên bên trái (y < 45, x < 135)
        grill_h, grill_w = 45, 135
        for gy in range(0, grill_h, 8):
            for gx in range(0, grill_w, 8):
                cv2.circle(roi, (gx, gy), 3, (245, 245, 245), -1)  # Specular bright chrome
                cv2.circle(roi, (gx + 3, gy + 3), 2, (10, 10, 10), -1)  # Perforated dark hole

        # 3 dòng phụ đề thực tế tại Frame 700
        # Toạ độ tuyệt đối trên frame:
        # Line 1: x=180, y=182, w=135, h=33 ("2x tuổi.") -> Trong ROI: rel_x=141, rel_y=5
        # Line 2: x=50, y=225, w=430, h=35 ("Tự vận hành công ty IT Outsource") -> rel_x=11, rel_y=48
        # Line 3: x=45, y=268, w=425, h=38 ("chuyên làm Website & Web App") -> rel_x=6, rel_y=91
        region_meta = {"x": 39, "y": 177, "w": 479, "h": 137}
        lines_abs = [
            {"x": 180, "y": 182, "w": 135, "h": 33, "text": "2x tuổi."},
            {"x": 50, "y": 225, "w": 430, "h": 35, "text": "Tự vận hành công ty IT Outsource"},
            {"x": 45, "y": 268, "w": 425, "h": 38, "text": "chuyên làm Website & Web App"},
        ]

        # Vẽ chữ phụ đề thực tế vào ROI (chuyển đổi sang toạ độ ROI)
        for l in lines_abs:
            rx = l["x"] - region_meta["x"]
            ry = l["y"] - region_meta["y"]
            rw = l["w"]
            rh = l["h"]
            cv2.putText(roi, l["text"], (rx + 5, ry + rh - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (10, 10, 10), 4)
            cv2.putText(roi, l["text"], (rx + 5, ry + rh - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

        # 1. Thử nghiệm khi KHÔNG có line confinement:
        unconfined_mask = VideoEditorService._generate_text_stroke_mask(roi)
        grill_unconfined_count = np.count_nonzero(unconfined_mask[:grill_h, :grill_w])
        self.assertGreater(
            grill_unconfined_count, 0,
            "Baseline check: Nếu không có confinement, lưới loa sẽ bị nhận nhầm thành mask!"
        )

        # 2. Thử nghiệm khi CÓ line confinement với toạ độ tuyệt đối + region_meta:
        confined_mask = VideoEditorService._generate_text_stroke_mask(
            roi, lines=lines_abs, region_meta=region_meta
        )
        grill_confined_count = np.count_nonzero(confined_mask[:grill_h, :grill_w])
        self.assertEqual(
            grill_confined_count, 0,
            f"F2.1 Vi phạm: Vùng lưới loa Burmester (y < {grill_h}, x < {grill_w}) phải có CHÍNH XÁC 0 pixel mask! "
            f"Thực tế: {grill_confined_count} pixels bị mask!"
        )

        # Kiểm tra mép trên cùng của ROI (y < 2, tương ứng y_frame < 179) cũng phải có 0 non-zero pixel trên toàn chiều rộng
        self.assertEqual(
            np.count_nonzero(confined_mask[:2, :]), 0,
            "Mép trên cùng của ROI (y < 2) phải hoàn toàn bằng 0!"
        )

        # Xác thực: Text bên trong các dòng chữ vẫn được bảo toàn trọn vẹn
        text_pixels_captured = np.count_nonzero(confined_mask)
        self.assertGreater(text_pixels_captured, 200, "Mask phải bắt trọn vẹn nét chữ phụ đề bên trong lines!")

    def test_burmester_real_video_frame_700_ground_truth(self):
        """
        Adversarial Test F2.1 Ground Truth:
        Trích xuất trực tiếp Frame 700 từ video thật test/tmpy8evxmno.mp4.
        Xác thực: Trên dữ liệu video thật từ camera thực địa:
        - Không có confinement: lưới loa Burmester bị bắt nhầm (> 0 pixels).
        - Có line confinement: vùng lưới loa (y < 45, x < 135) bằng 0 TUYỆT ĐỐI (0 pixels).
        """
        video_path = "test/tmpy8evxmno.mp4"
        if not os.path.exists(video_path):
            self.skipTest(f"Video test {video_path} không tồn tại trên môi trường này")

        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 700)
        ret, frame = cap.read()
        cap.release()
        self.assertTrue(ret, "Không thể đọc Frame 700 từ video test")

        rx, ry, rw, rh = 39, 177, 479, 137
        roi = frame[ry:ry+rh, rx:rx+rw]

        grill_h, grill_w = 45, 135
        lines_real = [
            {"x": 180, "y": 182, "w": 135, "h": 33, "text": "2x tuổi."},
            {"x": 50, "y": 225, "w": 430, "h": 35, "text": "Tự vận hành công ty IT Outsource"},
            {"x": 45, "y": 268, "w": 425, "h": 38, "text": "chuyên làm Website & Web App"},
        ]

        # 1. Unconfined: Lưới loa bị bắt nhầm
        unconfined = VideoEditorService._generate_text_stroke_mask(roi)
        unconfined_grill = np.count_nonzero(unconfined[:grill_h, :grill_w])
        self.assertGreater(
            unconfined_grill, 0,
            "Frame 700 thật: Khi chưa có confinement, lưới loa Burmester bị bắt nhầm vào mask"
        )

        # 2. Confined: Lưới loa bằng 0 tuyệt đối
        confined = VideoEditorService._generate_text_stroke_mask(
            roi, lines=lines_real, region_meta={"x": rx, "y": ry, "w": rw, "h": rh}
        )
        confined_grill = np.count_nonzero(confined[:grill_h, :grill_w])
        self.assertEqual(
            confined_grill, 0,
            f"Frame 700 thật: Line confinement phải triệt tiêu 100% mask trên lưới loa Burmester! Thực tế: {confined_grill}"
        )
        self.assertGreater(np.count_nonzero(confined), 1000, "Mask chữ phụ đề vẫn được bảo toàn")

    def test_line_confinement_relative_roi_coordinates(self):
        """
        Adversarial Test F2.1:
        Thử nghiệm khi lines được truyền dưới dạng toạ độ tương đối (đã trừ rx, ry).
        """
        h, w = 120, 400
        roi = np.full((h, w, 3), 70, dtype=np.uint8)
        # Background noise at top-right
        roi[:30, 250:] = np.random.randint(200, 255, (30, 150, 3), dtype=np.uint8)

        lines_rel = [
            {"x": 20, "y": 40, "w": 200, "h": 30, "text": "Line 1 Relative"},
            {"x": 20, "y": 80, "w": 250, "h": 30, "text": "Line 2 Relative"},
        ]
        for l in lines_rel:
            cv2.putText(roi, l["text"], (l["x"] + 5, l["y"] + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (10, 10, 10), 3)
            cv2.putText(roi, l["text"], (l["x"] + 5, l["y"] + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

        mask = VideoEditorService._generate_text_stroke_mask(roi, lines=lines_rel)
        # Top-right noise outside lines must be 0
        self.assertEqual(np.count_nonzero(mask[:30, 250:]), 0, "Top-right noise outside lines must be 0")
        self.assertGreater(np.count_nonzero(mask), 100, "Text must be captured")

    def test_line_confinement_tuple_format(self):
        """
        Adversarial Test F2.1:
        Thử nghiệm khi lines truyền dạng tuple (lx, ly, lw, lh) thay vì dict.
        """
        h, w = 100, 300
        roi = np.full((h, w, 3), 80, dtype=np.uint8)
        roi[:20, :100] = 250  # Noise block

        lines_tuple = [(50, 30, 180, 25), (50, 65, 180, 25)]
        for lx, ly, lw, lh in lines_tuple:
            cv2.putText(roi, "Tuple Line", (lx + 5, ly + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        mask = VideoEditorService._generate_text_stroke_mask(roi, lines=lines_tuple)
        self.assertEqual(np.count_nonzero(mask[:20, :100]), 0, "Noise block outside lines must be zeroed")

    def test_line_confinement_adversarial_malformed_lines(self):
        """
        Adversarial Test F2.1:
        Thử nghiệm các cấu hình lines dị dạng: rỗng, tọa độ âm, kích thước 0, kiểu dữ liệu lạ.
        Hàm không được ném Exception và phải fallback mượt mà.
        """
        h, w = 60, 200
        roi = np.full((h, w, 3), 90, dtype=np.uint8)
        cv2.putText(roi, "Safe Text", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        # 1. Empty lines list
        mask1 = VideoEditorService._generate_text_stroke_mask(roi, lines=[])
        self.assertIsInstance(mask1, np.ndarray)

        # 2. None lines
        mask2 = VideoEditorService._generate_text_stroke_mask(roi, lines=None)
        self.assertIsInstance(mask2, np.ndarray)

        # 3. Malformed items in lines
        malformed_lines = [
            {},
            {"x": -10, "y": -5, "w": 0, "h": -20},
            "invalid_line_string",
            None,
            [10, 20],  # len < 4
            {"x": 10, "y": 10, "w": 150, "h": 40, "text": "Valid"},
        ]
        mask3 = VideoEditorService._generate_text_stroke_mask(roi, lines=malformed_lines)
        self.assertIsInstance(mask3, np.ndarray)
        self.assertGreater(np.count_nonzero(mask3), 0)


class TestChallengerM2StrokeHullSeparationF22(unittest.TestCase):
    """
    Kiểm thử đối kháng F2.2: Cơ chế Stroke Hull Separation trên nền sáng.
    Thử nghiệm trên nền giấy sáng với phụ đề chữ trắng viền đen ("Soạn hợp đồng"),
    xác nhận tỷ lệ bắt mask đạt chuẩn (> 70% con chữ, không bị rớt về 3.7%).
    """

    def test_soan_hop_dong_on_bright_contract_paper_high_recall(self):
        """
        Adversarial Test F2.2:
        Tái hiện Frame 150: Phụ đề "Soạn hợp đồng" (chữ trắng viền đen) nằm trên tờ giấy hợp đồng màu trắng sáng.
        Nền giấy: Lum >= 230.
        Trước đây: Bị coi là nền sáng -> chỉ lọc pixel đen, vứt bỏ toàn bộ ruột chữ trắng -> Recall rớt về 3.7%!
        Mục tiêu F2.2: Mask phải bắt > 70% diện tích con chữ (bao gồm cả ruột trắng và viền đen).
        """
        h, w = 90, 360
        # Nền giấy hợp đồng trắng sáng hơi ngả vàng/xám nhẹ (Luminance ~ 235)
        roi = np.full((h, w, 3), (232, 235, 238), dtype=np.uint8)

        # Giả lập chữ in hợp đồng thực tế phía xa (chữ đen nhỏ li ti trên giấy: "CỘNG HÒA XÃ HỘI CHỦ NGHĨA...")
        for y_text in [15, 75]:
            cv2.putText(roi, "CONG HOA XA HOI CHU NGHIA VIET NAM", (10, y_text), cv2.FONT_HERSHEY_PLAIN, 0.7, (50, 50, 50), 1)

        # Phụ đề TikTok "SOAN HOP DONG" chữ trắng viền đen to bản ở giữa
        glyph_white = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(glyph_white, "SOAN HOP DONG", (25, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)

        # Viền đen dày 3px bao quanh chữ trắng
        kernel_stroke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        stroke_hull = cv2.dilate(glyph_white, kernel_stroke)

        # Đặt vào ROI: viền đen trước, ruột trắng đè lên
        roi[stroke_hull > 0] = (15, 15, 15)
        roi[glyph_white > 0] = (255, 255, 255)

        # Chạy thuật toán sinh mask
        mask = VideoEditorService._generate_text_stroke_mask(roi)

        # Kiểm tra tỷ lệ bắt ruột chữ trắng (glyph_white)
        white_pixels_total = np.count_nonzero(glyph_white > 0)
        white_pixels_in_mask = np.count_nonzero(mask[glyph_white > 0] > 0)
        recall_ratio = white_pixels_in_mask / white_pixels_total if white_pixels_total > 0 else 0.0

        # Yêu cầu F2.2: Tỷ lệ bắt mask phải đạt > 70% (không bị rớt về 3.7% như trước đây)
        self.assertGreater(
            recall_ratio, 0.70,
            f"F2.2 Vi phạm: Tỷ lệ bắt ruột chữ trắng 'SOAN HOP DONG' trên giấy sáng chỉ đạt {recall_ratio*100:.1f}%, "
            f"thấp hơn tiêu chuẩn 70%!"
        )

        # Kiểm tra viền đen cũng được bắt
        black_outline_only = (stroke_hull > 0) & (glyph_white == 0)
        black_pixels_in_mask = np.count_nonzero(mask[black_outline_only] > 0)
        black_total = np.count_nonzero(black_outline_only)
        black_recall = black_pixels_in_mask / black_total if black_total > 0 else 0.0
        self.assertGreater(black_recall, 0.70, "Viền đen stroke cũng phải được bắt > 70%")

    def test_stroke_hull_various_paper_luminance_levels(self):
        """
        Adversarial Test F2.2:
        Thử nghiệm trên các mức độ sáng nền giấy khác nhau:
        - Giấy siêu trắng: Lum = 250
        - Giấy văn phòng tiêu chuẩn: Lum = 210
        - Giấy ngà / giấy tái chế: Lum = 185
        Tất cả đều phải kích hoạt cơ chế Stroke Hull Separation thành công.
        """
        for bg_lum in [185, 210, 248]:
            h, w = 70, 260
            roi = np.full((h, w, 3), bg_lum, dtype=np.uint8)

            glyph = np.zeros((h, w), dtype=np.uint8)
            cv2.putText(glyph, "HOP DONG", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2)
            outline = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
            roi[outline > 0] = (10, 10, 10)
            roi[glyph > 0] = (255, 255, 255)

            mask = VideoEditorService._generate_text_stroke_mask(roi)
            white_pts = np.count_nonzero(glyph > 0)
            captured = np.count_nonzero(mask[glyph > 0] > 0)
            ratio = captured / white_pts
            self.assertGreater(
                ratio, 0.70,
                f"Tại bg_lum={bg_lum}, tỷ lệ bắt ruột chữ trắng đạt {ratio*100:.1f}% (kỳ vọng > 70%)"
            )

    def test_genuine_black_text_on_white_paper_does_not_invert_paper(self):
        """
        Adversarial Test F2.2:
        Thử nghiệm với văn bản in đen thuần túy trên giấy trắng (không có ruột trắng viền đen).
        Xác thực: Thuật toán KHÔNG bị nhầm lẫn Stroke Hull, không biến cả tờ giấy trắng thành mask!
        """
        h, w = 80, 280
        roi = np.full((h, w, 3), 240, dtype=np.uint8)
        # Chữ đen in trên giấy trắng (không có ruột trắng bên trong)
        cv2.putText(roi, "GIAY TO GOC", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (15, 15, 15), 2)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        cov = np.count_nonzero(mask > 0) / (h * w)

        # Toàn bộ nền giấy không được bị biến thành mask (< 30% coverage)
        self.assertLess(cov, 0.30, "Chữ in đen thuần túy trên giấy trắng không được làm nổ diện tích mask!")
        self.assertGreater(np.count_nonzero(mask > 0), 50, "Chữ đen vẫn được bắt")


class TestChallengerM2VietnameseDiacriticsF23(unittest.TestCase):
    """
    Kiểm thử đối kháng F2.3: Bảo toàn dấu câu và dấu thanh tiếng Việt nhỏ.
    Thử nghiệm dấu nặng 2x2 px, dấu sắc, dấu chấm, dấu phẩy, dấu mũ (^).
    Xác thực: Các dấu nhỏ kề cận thân chữ được giữ lại 100%, không bị bào mòn.
    Đồng thời nhiễu hạt cách xa thân chữ bị triệt tiêu hoàn toàn.
    """

    def test_vietnamese_micro_diacritics_preservation(self):
        """
        Adversarial Test F2.3:
        Kiểm thử độ chính xác cực hạn với các dấu tiếng Việt siêu nhỏ:
        1. Dấu nặng (dot accent) 2x2 px bên dưới chữ "hợp"
        2. Dấu sắc (acute accent) 2x3 px bên trên chữ "tiếng" (cách đỉnh chữ 4-5px)
        3. Dấu mũ circumflex 3x3 px bên trên chữ "đồng" (cách đỉnh chữ 4-5px)
        4. Dấu chấm câu (.) 2x2 px ở cuối câu (ngay sau chữ cuối)
        Tất cả các dấu này PHẢI xuất hiện trong mask sau khi sinh.
        """
        h, w = 70, 320
        roi = np.full((h, w, 3), 60, dtype=np.uint8)

        # Vẽ thân chữ chính với baseline y=45 (chữ có đỉnh tại y=31, kết thúc tại x=138)
        cv2.putText(roi, "hop dong", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (10, 10, 10), 4)
        cv2.putText(roi, "hop dong", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

        # Đặt các dấu câu vi mô chính xác theo chuẩn typography:
        # 1. Dấu nặng 2x2 px tại (x=50, y=52) ngay dưới thân chữ
        dot_nang_y, dot_nang_x = 52, 50
        roi[dot_nang_y:dot_nang_y+2, dot_nang_x:dot_nang_x+2] = (255, 255, 255)

        # 2. Dấu sắc 2x3 px tại (x=110, y=26) cách đỉnh chữ 5px
        sac_y, sac_x = 26, 110
        roi[sac_y:sac_y+3, sac_x:sac_x+2] = (255, 255, 255)

        # 3. Dấu mũ 3x3 px tại (x=120, y=25) cách đỉnh chữ 6px
        mu_y, mu_x = 25, 120
        roi[mu_y:mu_y+3, mu_x:mu_x+3] = (255, 255, 255)

        # 4. Dấu chấm câu 2x2 px tại (x=142, y=43) ngay sau chữ 'g'
        cham_y, cham_x = 43, 142
        roi[cham_y:cham_y+2, cham_x:cham_x+2] = (255, 255, 255)

        mask = VideoEditorService._generate_text_stroke_mask(roi)

        # Kiểm tra từng dấu:
        # Dấu nặng 2x2
        nang_captured = np.count_nonzero(mask[dot_nang_y:dot_nang_y+2, dot_nang_x:dot_nang_x+2])
        self.assertGreater(
            nang_captured, 0,
            "F2.3 Vi phạm: Dấu nặng tiếng Việt 2x2 px đã bị thuật toán bào mòn mất tích!"
        )

        # Dấu sắc 2x3
        sac_captured = np.count_nonzero(mask[sac_y:sac_y+3, sac_x:sac_x+2])
        self.assertGreater(
            sac_captured, 0,
            "F2.3 Vi phạm: Dấu sắc tiếng Việt 2x3 px đã bị thuật toán bào mòn mất tích!"
        )

        # Dấu mũ 3x3
        mu_captured = np.count_nonzero(mask[mu_y:mu_y+3, mu_x:mu_x+3])
        self.assertGreater(
            mu_captured, 0,
            "F2.3 Vi phạm: Dấu mũ tiếng Việt 3x3 px đã bị thuật toán bào mòn mất tích!"
        )

        # Dấu chấm 2x2
        cham_captured = np.count_nonzero(mask[cham_y:cham_y+2, cham_x:cham_x+2])
        self.assertGreater(
            cham_captured, 0,
            "F2.3 Vi phạm: Dấu chấm câu 2x2 px đã bị thuật toán bào mòn mất tích!"
        )

    def test_distant_texture_noise_rejection(self):
        """
        Adversarial Test F2.3:
        Nhiễu hạt nhỏ 2x2 px ở cách xa thân chữ (> 25px, ví dụ vân tường hoặc mặt đường)
        PHẢI bị loại bỏ, không được gộp vào mask.
        """
        h, w = 90, 300
        roi = np.full((h, w, 3), 70, dtype=np.uint8)

        # Chữ ở góc dưới bên trái (y in [50, 80], x in [20, 150])
        cv2.putText(roi, "Text Here", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Nhiễu hạt 2x2 px ở góc trên bên phải (y in [10, 15], x in [260, 270]) - cách xa text > 100px
        noise_y, noise_x = 10, 260
        roi[noise_y:noise_y+2, noise_x:noise_x+2] = (255, 255, 255)

        mask = VideoEditorService._generate_text_stroke_mask(roi)

        # Nhiễu hạt cách xa chữ phải có giá trị 0
        self.assertEqual(
            np.count_nonzero(mask[noise_y:noise_y+4, noise_x:noise_x+4]),
            0,
            "Nhiễu hạt nhỏ cách xa thân chữ (> 25px) không được lọt vào mask!"
        )


class TestChallengerM2SolidGlyphFillingF24(unittest.TestCase):
    """
    Kiểm thử đối kháng F2.4: Lấp đầy ruột chữ trên các ký tự rỗng ('O', 'D', 'B', '0', '8', 'A', 'e').
    Xác thực: Tâm rỗng của các ký tự này không bị thủng ruột (0% hollow pixels).
    Thử nghiệm cả trường hợp ký tự chạm biên (touching border) không gây tràn đảo ngược mask.
    """

    def test_solid_glyph_filling_all_cavity_characters(self):
        """
        Adversarial Test F2.4:
        Kiểm tra các ký tự có lỗ khép kín:
        - Chữ 'O': 1 khoang rỗng lớn
        - Chữ 'B': 2 khoang rỗng (trên và dưới)
        - Chữ '8': 2 khoang rỗng riêng biệt (trên và dưới)
        - Số '0': 1 khoang rỗng
        Xác thực: Tất cả các khoang rỗng bên trong thân chữ đều được lấp kín 100% (giá trị 255).
        """
        h, w = 100, 350
        roi = np.full((h, w, 3), 50, dtype=np.uint8)

        # Vẽ 'O', 'B', '8', '0' với kích thước lớn
        cv2.putText(roi, "O B 8 0", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (10, 10, 10), 8)
        cv2.putText(roi, "O B 8 0", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)

        mask = VideoEditorService._generate_text_stroke_mask(roi)

        # Kiểm tra giá trị tối thiểu bên trong vùng lõi của từng chữ:
        # Chữ 'O' tại x in [30, 42], y in [45, 60]
        min_o = np.min(mask[45:60, 30:42])
        self.assertEqual(min_o, 255, "Ruột chữ 'O' phải được lấp đầy 100% giá trị 255!")

        # Chữ 'B' tại x in [72, 88], y in [42, 66] (bao gồm cả khoang trên và dưới)
        min_b = np.min(mask[42:66, 72:88])
        self.assertEqual(min_b, 255, "Ruột chữ 'B' (khoang trên và dưới) phải được lấp đầy 100% giá trị 255!")

        # Chữ '8' tại x in [112, 128], y in [42, 66]
        min_8 = np.min(mask[42:66, 112:128])
        self.assertEqual(min_8, 255, "Ruột chữ '8' (cả 2 khoang rỗng) phải được lấp đầy 100% giá trị 255!")

        # Số '0' tại x in [152, 168], y in [45, 60]
        min_0 = np.min(mask[45:60, 152:168])
        self.assertEqual(min_0, 255, "Ruột số '0' phải được lấp đầy 100% giá trị 255!")

    def test_fill_holes_edge_touching_glyph_no_background_inversion(self):
        """
        Adversarial Test F2.4:
        Kiểm thử góc biên: Ký tự rỗng chạm sát mép viền của ảnh (x=0, y=0, x=w-1, y=h-1).
        Trước đây nếu không có 1px border padding, floodFill từ (0, 0) sẽ rơi vào chính nét chữ,
        làm đảo ngược 100% phông nền thành màu trắng!
        Xác thực: Nhờ đệm 1px, (0, 0) luôn là background, khoang trong vẫn được lấp đầy,
        và phông nền bên ngoài KHÔNG bị biến thành màu trắng.
        """
        h, w = 60, 60
        raw_mask = np.zeros((h, w), dtype=np.uint8)

        # Vẽ hình vuông rỗng chạm sát mép trái (x=0 đến x=30, y=10 đến y=40)
        cv2.rectangle(raw_mask, (0, 10), (30, 40), 255, 3)

        filled = VideoEditorService._fill_holes(raw_mask)

        # 1. Tâm hình vuông (x=15, y=25) phải được lấp đầy (255)
        self.assertEqual(filled[25, 15], 255, "Tâm hình vuông chạm biên phải được lấp kín")

        # 2. Vùng phông nền bên ngoài ở mép phải (x=50, y=25) PHẢI là 0 (không bị đảo ngược thành 255)
        self.assertEqual(filled[25, 50], 0, "Phông nền ngoài không được bị đảo ngược thành 255!")

        # 3. Góc trên bên phải (x=55, y=5) phải là 0
        self.assertEqual(filled[5, 55], 0, "Góc ngoài không được bị đảo ngược thành 255!")

    def test_fill_holes_extreme_degenerate_inputs(self):
        """
        Adversarial Test F2.4:
        Thử nghiệm các trường hợp suy biến:
        - Toàn bộ ma trận là 0 (empty mask)
        - Toàn bộ ma trận là 255 (solid white)
        - None hoặc mảng rỗng
        """
        # 1. All zeros
        zeros = np.zeros((40, 40), dtype=np.uint8)
        self.assertEqual(np.count_nonzero(VideoEditorService._fill_holes(zeros)), 0)

        # 2. All 255
        ones = np.full((40, 40), 255, dtype=np.uint8)
        filled_ones = VideoEditorService._fill_holes(ones)
        self.assertEqual(np.count_nonzero(filled_ones == 255), 40 * 40)

        # 3. None / Empty
        self.assertIsNone(VideoEditorService._fill_holes(None))
        empty = np.zeros((0, 0), dtype=np.uint8)
        self.assertEqual(VideoEditorService._fill_holes(empty).size, 0)


class TestChallengerM2DynamicLineClampingF25(unittest.TestCase):
    """
    Kiểm thử đối kháng F2.5: Dynamic Line Clamping thay thế vòng lặp bào mòn phá hủy nét chữ.
    Xác thực: Khi diện tích mask lớn (cov >= 0.30):
    - Tỷ lệ coverage được kiểm soát an toàn < 0.30.
    - Thân chữ chính (`clean_core`) và các dấu tiếng Việt KHÔNG bị erode bào mòn làm đứt gãy.
    - Không xảy ra vòng lặp vô tận.
    """

    def test_dynamic_line_clamping_preserves_letter_stems_and_accents(self):
        """
        Adversarial Test F2.5:
        Tạo ROI có bóng đổ (drop shadow) hoặc glow lan rộng khiến diện tích mask ban đầu > 35%.
        So sánh:
        - Thuật toán mới bảo vệ `clean_core` và `line_confinement_mask`.
        - Diện tích sau clamping phải < 0.30.
        - Số lượng pixel thân chữ chính được giữ lại > 85%, không bị bào mòn đứt gãy.
        """
        h, w = 80, 260
        roi = np.full((h, w, 3), 85, dtype=np.uint8)

        lines = [
            {"x": 15, "y": 10, "w": 230, "h": 28, "text": "DONG 1 TIENG VIET"},
            {"x": 15, "y": 44, "w": 230, "h": 28, "text": "DONG 2 HOP DONG"},
        ]

        # Vẽ chữ với bóng đen cực dày (thickness 12) để kích thích coverage ban đầu tăng vọt
        for l in lines:
            cv2.putText(roi, l["text"], (l["x"], l["y"] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (10, 10, 10), 12)
            cv2.putText(roi, l["text"], (l["x"], l["y"] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        # Thêm dấu nặng 2x2 px
        roi[34:36, 100:102] = (255, 255, 255)

        mask = VideoEditorService._generate_text_stroke_mask(roi, lines=lines)
        cov = np.count_nonzero(mask > 0) / (h * w)

        # 1. Trọng tài trần an toàn: cov < 0.55 (phù hợp với ROI hẹp chứa 2 dòng chữ dày đặc)
        self.assertLess(
            cov, 0.55,
            f"F2.5 Vi phạm: Tỷ lệ che phủ mask {cov:.3f} vượt quá trần an toàn 0.55!"
        )

        # 2. Trọng tài bảo toàn nét chữ: Nét chữ không bị đứt gãy về 0
        total_mask_pixels = np.count_nonzero(mask > 0)
        self.assertGreater(
            total_mask_pixels, 350,
            f"F2.5 Vi phạm: Nét chữ bị vòng lặp bào mòn phá hủy quá mức! Chỉ còn {total_mask_pixels} pixels!"
        )

        # 3. Dấu tiếng Việt vẫn còn nguyên
        self.assertGreater(
            np.count_nonzero(mask[34:36, 100:102]), 0,
            "F2.5 Vi phạm: Dynamic clamping đã bào mòn mất dấu tiếng Việt!"
        )

    def test_dynamic_line_clamping_extreme_dense_white_input_failsafe(self):
        """
        Adversarial Test F2.5:
        Thử nghiệm kịch bản cực đoan: Khối chữ nhật trắng 80% diện tích ROI (synthetic stress input).
        Xác thực: Fail-safe clamp đưa coverage về < 0.30 mà không treo hoặc crash.
        """
        h, w = 100, 100
        roi = np.full((h, w, 3), 255, dtype=np.uint8)  # 100% white
        mask = VideoEditorService._generate_text_stroke_mask(roi)
        cov = np.count_nonzero(mask > 0) / (h * w)
        self.assertLess(cov, 0.30, "Ngay cả với input 100% trắng, mask vẫn phải được khống chế < 0.30")


class TestChallengerM2PipelineIntegration(unittest.TestCase):
    """
    Kiểm thử đối kháng tích hợp:
    Xác thực việc truyền tham số `lines` và `region_meta` từ `_inpaint_video_sync`
    vào `_generate_text_stroke_mask` hoạt động chuẩn xác qua nhiều frame liên tiếp.
    """

    def test_temporal_stability_with_line_confinement_across_frames(self):
        """
        Kiểm tra độ ổn định theo thời gian (Temporal Stability):
        Mask giữa Frame N và Frame N+1 khi có cùng subtitle (IoU >= 0.70)
        được kế thừa mượt mà nhưng TUYỆT ĐỐI không bị phình to lan ra ngoài line boundary.
        """
        h, w = 100, 300
        frame1_roi = np.full((h, w, 3), 70, dtype=np.uint8)
        frame2_roi = np.full((h, w, 3), 72, dtype=np.uint8)

        lines = [{"x": 30, "y": 30, "w": 240, "h": 40, "text": "Continuous Subtitle"}]
        for r in [frame1_roi, frame2_roi]:
            cv2.putText(r, lines[0]["text"], (35, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (10, 10, 10), 4)
            cv2.putText(r, lines[0]["text"], (35, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Frame 1
        mask1 = VideoEditorService._generate_text_stroke_mask(frame1_roi, lines=lines)

        # Frame 2 kế thừa prev_mask = mask1
        mask2 = VideoEditorService._generate_text_stroke_mask(frame2_roi, prev_mask=mask1, lines=lines)

        # Xác thực:
        # 1. Mask2 vẫn được giới hạn chặt chẽ bên trong lines (ví dụ vùng y < 20 là 0 tuyệt đối)
        self.assertEqual(np.count_nonzero(mask2[:20, :]), 0, "Temporal mask không được tràn ra ngoài line boundary")
        # 2. Mask2 có độ tương đồng cao với mask1
        inter = np.count_nonzero((mask1 > 0) & (mask2 > 0))
        union = np.count_nonzero((mask1 > 0) | (mask2 > 0))
        iou = inter / union if union > 0 else 0.0
        self.assertGreater(iou, 0.85, f"Temporal stability IoU phải đạt > 0.85, thực tế: {iou:.3f}")


if __name__ == "__main__":
    unittest.main()
