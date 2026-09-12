from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.vietnamese_dialect import VietnameseLinguisticNormalizer, linguistic_normalizer


class TestVietnameseDialectNormalizer(unittest.TestCase):
    """
    Unit tests for Vietnamese Dialect Normalizer (Nghệ Tĩnh & Chat Teencode)
    and Metacognitive Doubt / Clarification Detection.
    """

    def setUp(self):
        self.normalizer = linguistic_normalizer

    def test_normalize_nghe_tinh_user_case_1(self):
        """
        User case 1: 'răng m lại thích mấy cấy nớ'
        Must accurately normalize to 'tại sao em lại thích mấy cái đó'.
        """
        raw = "răng m lại thích mấy cấy nớ"
        normalized, count = self.normalizer.normalize_to_standard(raw)
        self.assertEqual(normalized, "tại sao em lại thích mấy cái đó")
        self.assertGreater(count, 0)

    def test_normalize_nghe_tinh_common_phrases(self):
        """Verifies common Nghệ Tĩnh idioms and syntactic structures."""
        cases = [
            ("bựa ni thời tiết Nghệ An a răng", "hôm nay thời tiết Nghệ An thế nào"),
            ("mần chi ở mô rứa", "làm gì ở đâu thế"),
            ("nỏ chộ cấy mô hết", "không thấy cái nào hết"),
            ("chiều ni đi nhởi không", "chiều nay đi chơi không"),
            ("răng rứa hè", "sao thế nhỉ"),
        ]
        for raw, expected in cases:
            norm, cnt = self.normalizer.normalize_to_standard(raw)
            self.assertEqual(norm, expected, f"Failed on raw: {raw}")
            self.assertGreater(cnt, 0)

    def test_enrich_dialect_semantics_dual_view(self):
        """
        Verifies Dual-View Context Injection: preserves original text while
        appending normalized semantic meaning for LLM attention anchor.
        """
        raw = "răng m lại thích mấy cấy nớ"
        enriched = self.normalizer.enrich_dialect_semantics(raw)
        expected = "răng m lại thích mấy cấy nớ [Ý định & Ngữ nghĩa: tại sao em lại thích mấy cái đó]"
        self.assertEqual(enriched, expected)

    def test_enrich_idempotency(self):
        """Ensures enrich_dialect_semantics does not double-inject tags."""
        raw = "răng m lại thích mấy cấy nớ"
        first_pass = self.normalizer.enrich_dialect_semantics(raw)
        second_pass = self.normalizer.enrich_dialect_semantics(first_pass)
        self.assertEqual(first_pass, second_pass)

    def test_enrich_standard_text_noop(self):
        """Standard Vietnamese with no slang or dialect should remain untouched."""
        raw = "kiểm tra dung lượng ram và ổ cứng"
        enriched = self.normalizer.enrich_dialect_semantics(raw)
        self.assertEqual(enriched, raw)

    def test_detect_clarification_intent_user_case_2(self):
        """
        User case 2: 'm hiểu t hỏi chi không'
        Must accurately detect comprehension challenge / doubt cue.
        """
        raw = "m hiểu t hỏi chi không"
        cue = self.normalizer.detect_clarification_intent(raw)
        self.assertIsNotNone(cue)
        self.assertIn("hiểu", cue.lower())

    def test_detect_clarification_intent_variations(self):
        """Verifies doubt / correction detection across dialect and teencode variations."""
        cues = [
            "m có hiểu t hỏi chi ko",
            "có hiểu anh nói gì không",
            "hiểu sai rồi em",
            "nỏ phải rứa",
            "ý anh là khác cơ mà",
            "sai rồi",
        ]
        for c in cues:
            detected = self.normalizer.detect_clarification_intent(c)
            self.assertIsNotNone(detected, f"Should have detected clarification in: {c}")

    def test_detect_clarification_negative(self):
        """Normal command or factual question should NOT trigger doubt cue."""
        non_cues = [
            "xem thời tiết hôm nay",
            "docker ps",
            "tại sao em lại thích mấy cái đó",
        ]
        for nc in non_cues:
            detected = self.normalizer.detect_clarification_intent(nc)
            self.assertIsNone(detected, f"Should NOT trigger clarification in: {nc}")

    def test_build_metacognitive_system_prompt(self):
        """Verifies metacognitive system prompt content and anti-sycophancy directives."""
        prompt = self.normalizer.build_metacognitive_system_prompt("m hiểu t hỏi chi không", "hiểu t hỏi chi không")
        self.assertIn("SYSTEM 2 METACOGNITIVE AUDIT", prompt)
        self.assertIn("TUYỆT ĐỐI CẤM", prompt)
        self.assertIn("TỰ RÀ SOÁT LƯỢT TRƯỚC", prompt)


if __name__ == "__main__":
    unittest.main()
