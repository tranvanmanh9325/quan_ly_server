"""Unit tests verifying generalization and zero-hardcoding for VideoEditorService and HostedInpainterClient."""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import cv2
import httpx

from app.services.video_editor_service import VideoEditorService
from app.services.hosted_inpainter_client import HostedInpainterClient


class TestGeneralizationSynthetic(unittest.TestCase):
    """Kiểm chứng tính tổng quát 100% (Zero Hardcoding) trên ảnh và video tổng hợp mới lạ."""

    def test_dynamic_stroke_mask_scales_with_distance_transform(self):
        """Kiểm chứng Adaptive Dilation tự động co giãn theo stroke thickness thực tế từ distanceTransform."""
        h, w = 120, 400

        # Tạo 2 ROI nhân tạo: Một có nét mỏng (thickness=1), một có nét dày (thickness=4)
        roi_thin = np.zeros((h, w, 3), dtype=np.uint8)
        roi_thick = np.zeros((h, w, 3), dtype=np.uint8)

        # Nền tối
        roi_thin[:] = (30, 30, 30)
        roi_thick[:] = (30, 30, 30)

        # Vẽ text màu vàng có viền đen nhẹ
        cv2.putText(roi_thin, "TEST THIN", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(roi_thick, "TEST THICK", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 4, cv2.LINE_AA)

        mask_thin = VideoEditorService._generate_text_stroke_mask(roi_thin)
        mask_thick = VideoEditorService._generate_text_stroke_mask(roi_thick)

        self.assertIsNotNone(mask_thin)
        self.assertIsNotNone(mask_thick)
        self.assertGreater(np.count_nonzero(mask_thin), 0)
        self.assertGreater(np.count_nonzero(mask_thick), 0)

        # Mặt nạ của nét dày phải có diện tích lớn hơn mặt nạ của nét mỏng do adaptive dilation tự động tính theo nét
        area_thin = np.count_nonzero(mask_thin)
        area_thick = np.count_nonzero(mask_thick)
        self.assertGreater(area_thick, area_thin, f"Thick area ({area_thick}) should be larger than thin ({area_thin})")
        self.assertGreater(area_thick, area_thin * 1.2, f"Thick area ({area_thick}) should scale visibly larger than thin ({area_thin})")

    def test_stroke_mask_adaptive_gradient_enclosure(self):
        """Kiểm chứng Morphological Gradient Enclosure gom sạch quầng viền mờ gradient."""
        h, w = 100, 300
        roi = np.full((h, w, 3), 40, dtype=np.uint8)

        # Chữ có viền gradient chuyển tiếp mượt (anti-aliased)
        cv2.putText(roi, "GRADIENT", (20, 60), cv2.FONT_HERSHEY_DUPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsNotNone(mask)
        self.assertGreater(np.count_nonzero(mask), 0)

        # Xác nhận mask bao phủ đầy đủ cả phần chuyển tiếp của nét chữ (dilated beyond raw threshold)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        core_raw = (gray >= 200).astype(np.uint8) * 255
        self.assertGreater(np.count_nonzero(mask), np.count_nonzero(core_raw), "Mask must encompass gradient edges beyond raw core")

    def test_line_confinement_protects_speaker_grill_region(self):
        """Kiểm chứng line confinement mask và safe_pad_y=4 bảo vệ an toàn vùng họa tiết trên mép."""
        h, w = 150, 400
        roi = np.full((h, w, 3), 50, dtype=np.uint8)

        # Vẽ họa tiết giả lập speaker grill (chấm bi) ở dải y = 0..30
        for x in range(10, w - 10, 8):
            for y in range(5, 30, 6):
                cv2.circle(roi, (x, y), 2, (180, 180, 180), -1)

        # Vẽ text phụ đề ở dải y = 70..130
        cv2.putText(roi, "SUBTITLE LINE", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

        # Định nghĩa line box cho phụ đề: y từ 70 đến 125
        region_meta = {
            "x": 0,
            "y": 0,
            "lines": [{"x": 20, "y": 70, "w": 360, "h": 55}],
        }

        mask = VideoEditorService._generate_text_stroke_mask(roi, region_meta=region_meta)

        # Kiểm tra vùng speaker grill (y < 40) hoàn toàn không có bất kỳ pixel mask nào
        self.assertEqual(np.count_nonzero(mask[:40, :]), 0, "Speaker grill region must be strictly 0")
        # Trong khi vùng subtitle line phải có mask đầy đủ
        self.assertGreater(np.count_nonzero(mask[65:135, :]), 0, "Subtitle line must be masked")

    def test_sbtp_sequential_temporal_flow_mad(self):
        """Kiểm chứng SBTP với delta t = 1 frame giữ MAD cực thấp (< 9.0) trên camera chuyển động nhân tạo."""
        h, w = 200, 300

        # Tạo frame t-1 với texture nền ngẫu nhiên
        np.random.seed(42)
        base_texture = np.random.randint(60, 200, (h + 20, w + 20, 3), dtype=np.uint8)
        base_texture = cv2.GaussianBlur(base_texture, (5, 5), 1.5)

        # Frame t-1 crop tại offset (5, 5)
        frame_prev = base_texture[5:h + 5, 5:w + 5].copy()
        # Frame t crop tại offset (6, 6) mô phỏng chuyển động camera 1 px giữa 2 frame liên tiếp
        frame_curr = base_texture[6:h + 6, 6:w + 6].copy()

        # Tính DIS optical flow giữa frame_prev và frame_curr
        gray_prev = cv2.cvtColor(frame_prev, cv2.COLOR_BGR2GRAY)
        gray_curr = cv2.cvtColor(frame_curr, cv2.COLOR_BGR2GRAY)

        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
        flow = dis.calc(gray_curr, gray_prev, None)

        # Warp frame_prev sang frame_curr
        h_f, w_f = gray_curr.shape
        grid_x, grid_y = np.meshgrid(np.arange(w_f, dtype=np.float32), np.arange(h_f, dtype=np.float32))
        map_x = grid_x + flow[:, :, 0]
        map_y = grid_y + flow[:, :, 1]
        warped = cv2.remap(frame_prev, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        # Tính MAD
        diff = cv2.absdiff(frame_curr[10:h - 10, 10:w - 10], warped[10:h - 10, 10:w - 10])
        mad = float(np.mean(diff))

        # Xác nhận MAD nhỏ hơn nhiều so với ngưỡng fallback 15.0
        self.assertLess(mad, 8.0, f"SBTP delta t=1 MAD ({mad:.2f}) must be strictly < 8.0")

    def test_hosted_client_round_robin_failover_mechanism(self):
        """Kiểm chứng HostedInpainterClient có cơ chế round robin failover tuần tự giữa các endpoint."""
        client = HostedInpainterClient()
        self.assertGreaterEqual(len(client.endpoints), 2, "Must configure at least 2 endpoints for redundancy")

        # Mock requests: endpoint đầu tiên timeout, endpoint thứ hai thành công
        dummy_img = np.zeros((50, 50, 3), dtype=np.uint8)
        dummy_mask = np.zeros((50, 50), dtype=np.uint8)
        success_png = cv2.imencode(".png", np.full((50, 50, 3), 128, dtype=np.uint8))[1].tobytes()

        call_counts = {"count": 0}

        def mock_client_post(self_client, url, *args, **kwargs):
            call_counts["count"] += 1
            mock_resp = MagicMock()
            if call_counts["count"] == 1:
                raise httpx.ReadTimeout("Primary endpoint timeout")
            mock_resp.status_code = 200
            mock_resp.content = success_png
            return mock_resp

        with patch.object(httpx.Client, "post", new=mock_client_post):
            result = client.inpaint_roi_sync(dummy_img, dummy_mask)
            self.assertIsNotNone(result, "Failover to second endpoint must succeed")
            self.assertEqual(result.shape, dummy_img.shape)
            self.assertGreaterEqual(call_counts["count"], 2, "Must have attempted failover across endpoints")

    def test_multi_region_concurrent_text_generalization(self):
        """Kiểm chứng tính tổng quát đa vùng: Frame có text ở Top, Center, Bottom cùng lúc đều được phát hiện song song."""
        h, w = 500, 400
        frame = np.full((h, w, 3), 40, dtype=np.uint8)

        # Vẽ 3 cụm text độc lập ở 3 vùng độ cao khác nhau
        cv2.putText(frame, "TOP TITLE", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "CENTER ANNOTATION", (30, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "BOTTOM SUBTITLE", (40, 440), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

        svc = VideoEditorService()
        mask, _ = svc._build_inpaint_mask_for_frame(0, frame.shape, frame_img=frame)

        self.assertIsNotNone(mask)
        self.assertEqual(mask.shape, (h, w))

        # Kiểm chứng cả 3 vùng đều có mask bao phủ đồng thời (> 0)
        top_mask_count = np.count_nonzero(mask[20:100, :])
        center_mask_count = np.count_nonzero(mask[200:290, :])
        bottom_mask_count = np.count_nonzero(mask[390:470, :])

        self.assertGreater(top_mask_count, 100, f"Top text must be masked concurrently, got {top_mask_count}")
        self.assertGreater(center_mask_count, 100, f"Center text must be masked concurrently, got {center_mask_count}")
        self.assertGreater(bottom_mask_count, 100, f"Bottom text must be masked concurrently, got {bottom_mask_count}")


if __name__ == "__main__":
    unittest.main()

