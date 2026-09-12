"""
Adversarial Stress Test Suite for Fast-Path Media Intent Detection and URL Extraction.
Authored by: Challenger M2_1 (Empirical Adversarial Verifier)
Target: telegram_bot.py (_detect_fastpath_media_download, _MEDIA_URL_REGEX)

This suite stress-tests edge cases, malformed URLs, false-positive intent triggers,
and yields for conversational questions.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import TelegramBot


class TestFastPathAdversarialChallenger(unittest.TestCase):
    """Adversarial stress-testing suite for Fast-Path intent and URL parser."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1: False Positive Triggers on Questions & Substrings (CRITICAL)
    # ──────────────────────────────────────────────────────────────────────────

    def test_false_positive_accident_disaster_with_tai(self):
        """
        FAILING TEST CASE: Words with 'tai' (tai nạn, thiên tai, tai tiếng)
        In Vietnamese, 'tai' is part of many common non-download words.
        When a user asks about an accident, Fast-Path must NOT intercept.
        """
        failing_cases = [
            ("Clip tai nạn giao thông này ở đâu https://youtu.be/dQw4w9WgXcQ", "tai nạn"),
            ("Video quay cảnh thiên tai lũ lụt https://youtu.be/dQw4w9WgXcQ", "thiên tai"),
            ("Vụ tai tiếng của nghệ sĩ trong video này https://youtu.be/dQw4w9WgXcQ", "tai tiếng"),
            ("Anh tài xế bị phạt bao nhiêu trong clip https://youtu.be/dQw4w9WgXcQ", "tài xế (unaccented tai xe)"),
        ]
        for text, desc in failing_cases:
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                res,
                f"FALSE POSITIVE: Query containing '{desc}' triggered Fast-Path: '{text}' -> {res}"
            )

    def test_false_positive_unaccented_tai_variants(self):
        """
        FAILING TEST CASE: Unaccented common words containing 'tai'
        (tai lieu = tài liệu, tai khoan = tài khoản, ton tai = tồn tại, de tai = đề tài).
        """
        failing_cases = [
            ("day la tai lieu hoc tap https://youtu.be/dQw4w9WgXcQ", "tài liệu"),
            ("link nay co can dang nhap tai khoan khong https://youtu.be/dQw4w9WgXcQ", "tài khoản"),
            ("video nay con ton tai khong https://youtu.be/dQw4w9WgXcQ", "tồn tại"),
            ("de tai cua video nay la gi https://youtu.be/dQw4w9WgXcQ", "đề tài"),
            ("tai vi sao lai xay ra chuyen nay https://youtu.be/dQw4w9WgXcQ", "tại vì"),
        ]
        for text, desc in failing_cases:
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                res,
                f"FALSE POSITIVE: Unaccented query '{desc}' triggered Fast-Path: '{text}' -> {res}"
            )

    def test_false_positive_lay_and_luu_substrings(self):
        """
        FAILING TEST CASE: Words containing 'lấy' (lấy chồng, lấy cảm hứng, lấy ví dụ)
        and 'lưu' (lưu ý, lưu truyền).
        """
        failing_cases = [
            ("Cô gái trong clip đi lấy chồng rồi https://youtu.be/dQw4w9WgXcQ", "lấy chồng"),
            ("Bài hát này lấy cảm hứng từ đâu https://youtu.be/dQw4w9WgXcQ", "lấy cảm hứng"),
            ("Lấy ví dụ clip này để phân tích https://youtu.be/dQw4w9WgXcQ", "lấy ví dụ"),
            ("Có lưu ý gì khi xem video này không https://youtu.be/dQw4w9WgXcQ", "lưu ý"),
            ("Clip này lưu truyền câu chuyện gì https://youtu.be/dQw4w9WgXcQ", "lưu truyền"),
        ]
        for text, desc in failing_cases:
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                res,
                f"FALSE POSITIVE: Query containing '{desc}' triggered Fast-Path: '{text}' -> {res}"
            )

    def test_false_positive_why_and_how_download_questions(self):
        """
        FAILING TEST CASE: Inquisitive questions asking 'why' or 'how' regarding download issues.
        The user is asking a conversational question, NOT requesting an immediate download.
        """
        failing_cases = [
            ("Vì sao không tải được video này https://youtu.be/dQw4w9WgXcQ", "vì sao không tải"),
            ("Sao không tải được video này https://youtu.be/dQw4w9WgXcQ", "sao không tải"),
            ("Làm sao để tải video này https://youtu.be/dQw4w9WgXcQ", "làm sao để tải"),
            ("Video này sao tải lâu thế https://youtu.be/dQw4w9WgXcQ", "sao tải lâu"),
        ]
        for text, desc in failing_cases:
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                res,
                f"FALSE POSITIVE: Conversational question '{desc}' triggered Fast-Path: '{text}' -> {res}"
            )

    def test_false_positive_negative_download_intent(self):
        """
        FAILING TEST CASE: Explicit negative intent telling the bot NOT to download.
        Phrases like 'đừng tải', 'không tải', 'dung tai' must NEVER trigger Fast-Path.
        """
        failing_cases = [
            ("Đừng tải video này nha https://youtu.be/dQw4w9WgXcQ", "đừng tải"),
            ("Không tải clip này https://youtu.be/dQw4w9WgXcQ", "không tải"),
            ("dung tai video https://youtu.be/dQw4w9WgXcQ", "dung tai"),
        ]
        for text, desc in failing_cases:
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                res,
                f"FALSE POSITIVE: Negative intent '{desc}' triggered Fast-Path: '{text}' -> {res}"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2: Trailing Punctuation & Enclosures
    # ──────────────────────────────────────────────────────────────────────────

    def test_url_enclosed_in_angle_brackets(self):
        """
        FAILING TEST CASE: Links wrapped in angle brackets <url> (Discord/Slack/Markdown standard).
        Currently, trailing '>' is NOT stripped by rstrip, corrupting the downloaded URL.
        """
        text = "tải video <https://www.youtube.com/watch?v=dQw4w9WgXcQ>"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Expected Fast-path detection for angle-bracketed URL")
        url, _ = res
        self.assertEqual(
            url,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            f"Trailing '>' was not stripped, resulting in corrupted URL: {url}"
        )

    def test_url_enclosed_in_square_brackets(self):
        """
        FAILING TEST CASE: Links wrapped in square brackets [url].
        Trailing ']' is not stripped, leaving trailing bracket on media URL.
        """
        text = "tải video [https://www.youtube.com/watch?v=dQw4w9WgXcQ]"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Expected Fast-path detection for bracketed URL")
        url, _ = res
        self.assertEqual(
            url,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            f"Trailing ']' was not stripped, resulting in corrupted URL: {url}"
        )

    def test_url_with_unicode_ellipsis(self):
        """
        FAILING TEST CASE: Links copied with trailing unicode ellipsis (…).
        """
        text = "tải video https://youtu.be/dQw4w9WgXcQ…"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Expected Fast-path detection for URL with ellipsis")
        url, _ = res
        self.assertEqual(
            url,
            "https://youtu.be/dQw4w9WgXcQ",
            f"Unicode ellipsis was not stripped, resulting in corrupted URL: {url}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3: True Positive Validations (Correct Fast-Path Behavior)
    # ──────────────────────────────────────────────────────────────────────────

    def test_true_positive_standalone_urls(self):
        """Verify standalone clean URLs trigger Fast-Path properly."""
        valid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/3dYx1pB9VvE",
            "https://web.facebook.com/reel/123456789",
            "https://www.threads.net/@zuck/post/DA12345",
            "https://vt.tiktok.com/ZS123456/",
        ]
        for u in valid_urls:
            res = self.bot._detect_fastpath_media_download(u)
            self.assertIsNotNone(res, f"Expected fast-path trigger for: {u}")
            self.assertEqual(res[0], u)
            self.assertEqual(res[1], "")

    def test_true_positive_explicit_download_intent(self):
        """Verify explicit download phrases trigger Fast-Path correctly."""
        base_url = "https://www.youtube.com/shorts/3dYx1pB9VvE"
        valid_phrases = [
            f"tải video {base_url}",
            f"{base_url} tải về",
            f"kéo video {base_url}",
            f"tai video {base_url}",
            f"{base_url} tai ve",
            f"lay video {base_url}",
            f"tai clip {base_url}",
            f"chuyển file {base_url}",
        ]
        for phrase in valid_phrases:
            res = self.bot._detect_fastpath_media_download(phrase)
            self.assertIsNotNone(res, f"Expected fast-path trigger for: {phrase}")
            self.assertEqual(res[0], base_url)

    def test_true_negative_content_analysis(self):
        """Verify conversational analysis questions yield to AI Agent (return None)."""
        base_url = "https://www.youtube.com/shorts/3dYx1pB9VvE"
        analysis_phrases = [
            f"tóm tắt nội dung video này {base_url}",
            f"dịch giúp anh bài hát trong video {base_url}",
            f"video này nói về gì {base_url}",
            f"giải thích clip này {base_url}",
            f"ai đây {base_url}",
            f"tai sao video nay noi ve gi {base_url}",
            f"tại sao lại như thế {base_url}",
        ]
        for phrase in analysis_phrases:
            res = self.bot._detect_fastpath_media_download(phrase)
            self.assertIsNone(res, f"Expected None for analysis question: {phrase}")


if __name__ == "__main__":
    unittest.main()
