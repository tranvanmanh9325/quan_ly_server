"""
Adversarial Stress Test Suite for Subconscious Stream & Metacognitive Tag Stripping.
Authored by: Challenger 2 for Milestone 1 (M1 Empirical Adversarial Verifier)
Target: AIAgentService._strip_subconscious_stream

Scope:
1. Fully closed <subconscious_stream> and <metacognitive_audit> tags.
2. Unclosed tags due to token limit / truncation.
3. Whitespace variations (leading, trailing, tabs, newlines inside tags).
4. Tag attributes (<subconscious_stream confidence="0.9">).
5. Compound sequences: closed tag followed by unclosed tag.
6. Dangling closing tags (e.g. </subconscious_stream> without opening tag).
7. Special characters, angle brackets (<, >) inside reasoning block, unicode/emoji.
8. Stress/Performance: Long text with high token counts (ReDoS resistance).
9. Zero-token-leak verification on final cleaned text.
"""

import sys
import time
import unittest
from pathlib import Path

# Add services/ai-agent-service to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent import AiAgentService


class TestAdversarialStripSubconscious(unittest.TestCase):
    """Adversarial stress-testing suite for _strip_subconscious_stream."""

    @classmethod
    def setUpClass(cls):
        cls.strip = staticmethod(AiAgentService._strip_subconscious_stream)

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1: Standard Closed Tags & Basic Cleansing
    # ──────────────────────────────────────────────────────────────────────────

    def test_section1_01_standard_closed_subconscious_stream(self):
        """Standard <subconscious_stream> closed tag with inner thought."""
        raw = (
            "<subconscious_stream>\n"
            "confidence: 0.95\n"
            "assumptions: ['RAM 3.2GB']\n"
            "</subconscious_stream>\n"
            "Chào anh Mạnh! Em đã tối ưu hệ thống."
        )
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "Chào anh Mạnh! Em đã tối ưu hệ thống.")
        self.assertIsNotNone(inner)
        self.assertIn("confidence: 0.95", inner)
        self.assertNotIn("<subconscious_stream>", cleaned)
        self.assertNotIn("</subconscious_stream>", cleaned)

    def test_section1_02_standard_closed_metacognitive_audit(self):
        """Standard <metacognitive_audit> closed tag."""
        raw = (
            "<metacognitive_audit>\n"
            "Audit: Verified zero memory leak on 3.2GB RAM.\n"
            "</metacognitive_audit>\n"
            "Dạ em đã kiểm tra an toàn."
        )
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "Dạ em đã kiểm tra an toàn.")
        self.assertIsNotNone(inner)
        self.assertIn("Audit: Verified", inner)
        self.assertNotIn("<metacognitive_audit>", cleaned)
        self.assertNotIn("</metacognitive_audit>", cleaned)

    def test_section1_03_case_insensitivity(self):
        """Tags with various casing (uppercase, mixed case)."""
        cases = [
            ("<SUBCONSCIOUS_STREAM>Thought</SUBCONSCIOUS_STREAM>Result A", "Result A"),
            ("<Subconscious_Stream>Thought</Subconscious_Stream>Result B", "Result B"),
            ("<METACOGNITIVE_AUDIT>Audit</METACOGNITIVE_AUDIT>Result C", "Result C"),
            ("<Metacognitive_Audit>Audit</Metacognitive_Audit>Result D", "Result D"),
        ]
        for raw, expected in cases:
            cleaned, inner = self.strip(raw)
            self.assertEqual(cleaned, expected)
            self.assertNotIn("<", cleaned)
            self.assertNotIn(">", cleaned)

    def test_section1_04_multiple_closed_tags(self):
        """Multiple closed tags in a single message."""
        raw = (
            "<subconscious_stream>First thought</subconscious_stream>"
            "Part 1. "
            "<metacognitive_audit>Second thought</metacognitive_audit>"
            "Part 2."
        )
        cleaned, inner = self.strip(raw)
        self.assertNotIn("<subconscious_stream>", cleaned)
        self.assertNotIn("</subconscious_stream>", cleaned)
        self.assertNotIn("<metacognitive_audit>", cleaned)
        self.assertNotIn("</metacognitive_audit>", cleaned)
        self.assertNotIn("First thought", cleaned)
        self.assertNotIn("Second thought", cleaned)
        self.assertEqual(cleaned, "Part 1. Part 2.")

    def test_section1_05_empty_and_whitespace_only_tags(self):
        """Empty tag content or pure whitespace inside tags."""
        raw1 = "<subconscious_stream></subconscious_stream>Nội dung chính"
        cleaned1, inner1 = self.strip(raw1)
        self.assertEqual(cleaned1, "Nội dung chính")
        self.assertEqual(inner1, "")

        raw2 = "<subconscious_stream>   \n\t  \n  </subconscious_stream>Nội dung chính 2"
        cleaned2, inner2 = self.strip(raw2)
        self.assertEqual(cleaned2, "Nội dung chính 2")
        self.assertEqual(inner2, "")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2: Unclosed Tags Due to Token Limit / Truncation
    # ──────────────────────────────────────────────────────────────────────────

    def test_section2_01_unclosed_at_beginning_truncated(self):
        """Response cuts off while still generating inner thought (zero cleaned text)."""
        raw = "<subconscious_stream>\n1. Epistemic Confidence: 0.8\n2. Risk Matrix: RAM is tight..."
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "")
        self.assertIsNotNone(inner)
        self.assertIn("RAM is tight", inner)
        self.assertNotIn("<subconscious_stream>", cleaned)

    def test_section2_02_unclosed_metacognitive_audit(self):
        """Unclosed <metacognitive_audit> tag due to token budget."""
        raw = "<metacognitive_audit>\nAudit: Checking tool calls for safety..."
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "")
        self.assertIsNotNone(inner)
        self.assertIn("Checking tool calls", inner)
        self.assertNotIn("<metacognitive_audit>", cleaned)

    def test_section2_03_text_before_unclosed_tag(self):
        """Some text generated first, then unclosed subconscious stream appended."""
        raw = "Chào anh Mạnh! <subconscious_stream> suy nghĩ dở dang bị cắt..."
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "Chào anh Mạnh!")
        self.assertIsNotNone(inner)
        self.assertIn("suy nghĩ dở dang", inner)
        self.assertNotIn("<subconscious_stream>", cleaned)

    def test_section2_04_just_opening_tag(self):
        """Token limit hits exactly at the opening tag."""
        raw = "<subconscious_stream>"
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "")
        self.assertEqual(inner, "")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3: Compound & Mixed Tags (Adversarial Edge Cases)
    # ──────────────────────────────────────────────────────────────────────────

    def test_section3_01_closed_tag_followed_by_unclosed_tag(self):
        """
        CRITICAL VULNERABILITY TEST:
        First thought is closed, then intermediate text, then second thought gets cut off.
        Current implementation flaw: 'if stream_match:' strips only closed tags via re.sub,
        and leaves unclosed tags untouched in cleaned text!
        """
        raw = (
            "<subconscious_stream>Thought 1</subconscious_stream>"
            "Phản hồi đợt 1. "
            "<subconscious_stream>Thought 2 unclosed cut off by token limit..."
        )
        cleaned, inner = self.strip(raw)
        self.assertNotIn("<subconscious_stream>", cleaned, "LEAK: Opening tag leaked!")
        self.assertNotIn("Thought 2 unclosed", cleaned, "LEAK: Inner thought leaked to user!")
        self.assertEqual(cleaned, "Phản hồi đợt 1.")

    def test_section3_02_closed_metacognitive_followed_by_unclosed_subconscious(self):
        """Mixed tag types: closed <metacognitive_audit> then unclosed <subconscious_stream>."""
        raw = (
            "<metacognitive_audit>Audit passed</metacognitive_audit>"
            "Câu trả lời an toàn. "
            "<subconscious_stream>Suy nghĩ tiếp theo bị ngắt..."
        )
        cleaned, inner = self.strip(raw)
        self.assertNotIn("<subconscious_stream>", cleaned)
        self.assertNotIn("Suy nghĩ tiếp theo", cleaned)
        self.assertEqual(cleaned, "Câu trả lời an toàn.")

    def test_section3_03_dangling_closing_tag_alone(self):
        """
        Dangling closing tag without opening tag (e.g. prefill or LLM hallucination).
        A dangling </subconscious_stream> must NOT be visible to user.
        """
        raw = "Chào anh Mạnh! </subconscious_stream> Em đã sẵn sàng."
        cleaned, inner = self.strip(raw)
        self.assertNotIn("</subconscious_stream>", cleaned, "LEAK: Dangling closing tag leaked!")
        self.assertEqual(cleaned, "Chào anh Mạnh!  Em đã sẵn sàng.")

    def test_section3_04_dangling_metacognitive_closing_tag(self):
        """Dangling </metacognitive_audit> without opening tag."""
        raw = "Dạ kết quả đây ạ. </metacognitive_audit>"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("</metacognitive_audit>", cleaned)
        self.assertEqual(cleaned, "Dạ kết quả đây ạ.")

    def test_section3_05_mismatched_open_close_tags(self):
        """Mismatched tags: <subconscious_stream> closed with </metacognitive_audit>."""
        raw = "<subconscious_stream>Inner thought</metacognitive_audit>Nội dung cuối"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("<subconscious_stream>", cleaned)
        self.assertNotIn("</metacognitive_audit>", cleaned)
        self.assertNotIn("Inner thought", cleaned)
        self.assertEqual(cleaned, "Nội dung cuối")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4: Whitespace and Tag Malformations (Token Leaks)
    # ──────────────────────────────────────────────────────────────────────────

    def test_section4_01_trailing_space_in_opening_tag(self):
        """Whitespace before closing bracket in tag: <subconscious_stream >."""
        raw = "<subconscious_stream >Suy nghĩ có space</subconscious_stream>Kết quả"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("<subconscious_stream", cleaned, "LEAK: Tag with trailing space leaked!")
        self.assertNotIn("Suy nghĩ có space", cleaned)
        self.assertEqual(cleaned, "Kết quả")

    def test_section4_02_leading_space_in_opening_tag(self):
        """Whitespace after opening bracket: < subconscious_stream>."""
        raw = "< subconscious_stream>Suy nghĩ</subconscious_stream>Kết quả"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("subconscious_stream", cleaned, "LEAK: Tag with leading space leaked!")
        self.assertEqual(cleaned, "Kết quả")

    def test_section4_03_space_in_closing_tag(self):
        """Whitespace inside closing tag: </subconscious_stream > or </ subconscious_stream>."""
        raw = "<subconscious_stream>Suy nghĩ</subconscious_stream >Kết quả"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("subconscious_stream", cleaned)
        self.assertEqual(cleaned, "Kết quả")

    def test_section4_04_newline_inside_tag(self):
        """Newline or tab inside tag: <subconscious_stream\\n>."""
        raw = "<subconscious_stream\n>Suy nghĩ đa dòng</subconscious_stream>Kết quả"
        cleaned, inner = self.strip(raw)
        self.assertNotIn("subconscious_stream", cleaned)
        self.assertEqual(cleaned, "Kết quả")

    def test_section4_05_tags_with_attributes(self):
        """Tags containing LLM-generated attributes: <subconscious_stream confidence='0.95'>."""
        raw = (
            "<subconscious_stream confidence='0.95' mode='deliberative'>\n"
            "assumptions: ['RAM 3.2GB']\n"
            "</subconscious_stream>\n"
            "Hệ thống vận hành bình thường."
        )
        cleaned, inner = self.strip(raw)
        self.assertNotIn("subconscious_stream", cleaned, "LEAK: Tag with attributes leaked!")
        self.assertNotIn("confidence='0.95'", cleaned)
        self.assertEqual(cleaned, "Hệ thống vận hành bình thường.")

    def test_section4_06_unclosed_tag_with_attributes(self):
        """Unclosed tag with attributes: <subconscious_stream confidence='0.95'> cut off."""
        raw = (
            "<subconscious_stream confidence='0.95'>\n"
            "assumptions: ['RAM 3.2GB'] cut off here..."
        )
        cleaned, inner = self.strip(raw)
        self.assertNotIn("subconscious_stream", cleaned)
        self.assertNotIn("assumptions", cleaned)
        self.assertEqual(cleaned, "")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5: Special Characters, Angle Brackets & Content Robustness
    # ──────────────────────────────────────────────────────────────────────────

    def test_section5_01_nested_angle_brackets_in_thought(self):
        """Inner thought contains mathematical comparison operators (< and >)."""
        raw = (
            "<subconscious_stream>\n"
            "if memory_mb < 3200 and cpu_cores > 1:\n"
            "    risk = 'LOW'\n"
            "</subconscious_stream>\n"
            "Tài nguyên máy chủ an toàn."
        )
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "Tài nguyên máy chủ an toàn.")
        self.assertIsNotNone(inner)
        self.assertIn("memory_mb < 3200", inner)
        self.assertNotIn("<subconscious_stream>", cleaned)

    def test_section5_02_markdown_code_blocks_containing_subconscious(self):
        """Assistant outputs markdown code block containing tag."""
        raw = (
            "<subconscious_stream>Tư duy phân tích</subconscious_stream>\n"
            "```xml\n"
            "<subconscious_stream>code sample</subconscious_stream>\n"
            "```"
        )
        cleaned, inner = self.strip(raw)
        # Verify that either all or the reasoning is stripped cleanly
        self.assertNotIn("Tư duy phân tích", cleaned)

    def test_section5_03_vietnamese_unicode_and_emojis(self):
        """Vietnamese diacritics, complex emojis, and dialect words."""
        raw = (
            "<subconscious_stream>\n"
            "Trực giác: Anh Mạnh hỏi 'mô rứa hè', đây là phương ngữ Nghệ Tĩnh.\n"
            "Cảm xúc: 💖 🛡️ 🚀\n"
            "</subconscious_stream>\n"
            "Dạ anh Mạnh! Em ở đây nì!"
        )
        cleaned, inner = self.strip(raw)
        self.assertEqual(cleaned, "Dạ anh Mạnh! Em ở đây nì!")
        self.assertIsNotNone(inner)
        self.assertIn("mô rứa hè", inner)
        self.assertIn("💖", inner)

    def test_section5_04_zero_token_leak_guarantee(self):
        """
        Exhaustive check on various adversarial payloads to ensure ZERO leak
        of internal thinking keywords into cleaned text.
        """
        payloads = [
            "<subconscious_stream>LEAK_PAYLOAD_1</subconscious_stream>Visible text 1",
            "<metacognitive_audit>LEAK_PAYLOAD_2</metacognitive_audit>Visible text 2",
            "<subconscious_stream>LEAK_PAYLOAD_3",
            "Visible text 4 <subconscious_stream>LEAK_PAYLOAD_4",
            "<subconscious_stream>LEAK_PAYLOAD_5</subconscious_stream>Mid text <subconscious_stream>LEAK_PAYLOAD_6",
        ]
        for payload in payloads:
            cleaned, _ = self.strip(payload)
            for i in range(1, 7):
                self.assertNotIn(
                    f"LEAK_PAYLOAD_{i}",
                    cleaned,
                    f"CRITICAL LEAK: LEAK_PAYLOAD_{i} leaked into cleaned text from payload: {payload!r} -> {cleaned!r}",
                )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6: Performance & ReDoS Stress Test
    # ──────────────────────────────────────────────────────────────────────────

    def test_section6_01_redos_resistance_long_unclosed_text(self):
        """
        Stress-test regex performance with 100,000 characters of unclosed tags
        and pathological repetition to verify no exponential backtracking (ReDoS).
        """
        large_body = "<subconscious_stream>" + ("A" * 100_000)
        t0 = time.perf_counter()
        cleaned, inner = self.strip(large_body)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 1.0, f"Performance issue / ReDoS detected: took {elapsed:.3f}s")
        self.assertEqual(cleaned, "")
        self.assertEqual(len(inner), 100_000)

    def test_section6_02_many_repeated_closed_tags_performance(self):
        """Stress-test with 500 repeated tags in a single output."""
        chunks = [f"<subconscious_stream>thought {i}</subconscious_stream>text {i} " for i in range(500)]
        large_text = "".join(chunks)
        t0 = time.perf_counter()
        cleaned, inner = self.strip(large_text)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 1.0, f"Took too long: {elapsed:.3f}s")
        self.assertNotIn("thought", cleaned)
        self.assertIn("text 0", cleaned)
        self.assertIn("text 499", cleaned)


if __name__ == "__main__":
    unittest.main()
