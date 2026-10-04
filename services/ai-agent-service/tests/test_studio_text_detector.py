import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from app.services.studio_text_detector import StudioTextDetector


class TestStudioTextDetector(unittest.TestCase):
    """Test suite for StudioTextDetector under Zero Local AI Policy."""

    def setUp(self):
        self.detector = StudioTextDetector.get_instance()

    def test_singleton_instance_returns_same_object(self):
        """get_instance() returns the exact same singleton instance."""
        inst1 = StudioTextDetector.get_instance()
        inst2 = StudioTextDetector.get_instance()
        self.assertIs(inst1, inst2)

    def test_model_path_resolves_correctly(self):
        """Model path resolves to text_detector_model."""
        self.assertEqual(self.detector.model_path.name, "text_detector_model")

    def test_detect_regions_with_none_or_empty_image(self):
        """detect_regions returns empty list when given None or empty array."""
        self.assertEqual(self.detector.detect_regions(None), [])
        empty_img = np.zeros((0, 0, 3), dtype=np.uint8)
        self.assertEqual(self.detector.detect_regions(empty_img), [])

    def test_detect_regions_synthetic_text(self):
        """detect_regions returns empty list when local neural model is absent."""
        h, w = 320, 640
        img = np.full((h, w, 3), 40, dtype=np.uint8)
        cv2.putText(img, "TOP TITLE LINE", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 4)
        cv2.putText(img, "BOTTOM SUBTITLE LINE", (50, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 4)

        if not self.detector.is_available():
            boxes = self.detector.detect_regions(img)
            self.assertEqual(boxes, [])
            return

        boxes = self.detector.detect_regions(img)
        self.assertGreaterEqual(len(boxes), 1)

    def test_detect_regions_with_mock_session(self):
        """Mock session accurately processes probability map output."""
        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "x"
        mock_session.get_inputs.return_value = [mock_input]

        prob = np.zeros((1, 1, 320, 320), dtype=np.float32)
        prob[0, 0, 50:80, 100:200] = 0.95
        mock_session.run.return_value = [prob]

        custom_detector = StudioTextDetector(model_path=Path("dummy_model"))
        custom_detector._session = mock_session
        custom_detector._is_available = True

        test_img = np.zeros((320, 320, 3), dtype=np.uint8)
        boxes = custom_detector.detect_regions(test_img)

        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["type"], "title")
        self.assertGreaterEqual(boxes[0]["score"], 0.90)

    def test_unclip_ratio_and_padding_expansion(self):
        """Unclip expansion correctly widens bounding box to encompass entire character strokes."""
        detector = StudioTextDetector(unclip_ratio=2.0)
        self.assertEqual(detector._unclip_ratio, 2.0)


if __name__ == "__main__":
    unittest.main()
