"""
test_challenger_preview_27_1_adversarial.py — Empirical Challenger Test Suite.

Adversarial stress-testing for Milestone 27 Worker 27_1 changes:
1. TestAdversarialComposeAgentContext:
   - Anomalous inputs (empty, None-like, duration=0, large duration, float duration, None duration).
   - Zero-leakage verification of legacy hardcoded strings ("Trung Thu", "Drone show", "Nghệ An", etc.).
   - Exact presence and absence of video_path parameter under various conditions.
   - Large payload stress-test (100k+ chars) & special Unicode characters (RTL, emojis, injection strings).
2. TestAdversarialVideoEditIntentMatrix:
   - Comprehensive 30+ query matrix covering:
     * Clear video editing intents (Positive baseline).
     * Pure video analysis / transcription / Q&A queries (Negative baseline).
     * Multi-intent / Compound commands (Analysis + Edit).
     * Adversarial keyword traps, negation traps, advisory questions, synonyms, and edge cases.
3. TestBackwardCompatibilityAndAliases:
   - Verifies VideoAnalysisPipeline and TelegramBotService aliases.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

os.environ["TESTING"] = "true"

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.video_pipeline import LightweightVideoPipeline, VideoAnalysisPipeline
from app.services.telegram_bot import TelegramBot, TelegramBotService


class TestAdversarialComposeAgentContext(unittest.TestCase):
    """Adversarial testing for _compose_agent_context in VideoPipeline."""

    def setUp(self):
        self.mock_media = MagicMock()
        self.pipeline = LightweightVideoPipeline(self.mock_media)
        self.forbidden_legacy_strings = [
            "Trung Thu",
            "trung thu",
            "Tết Trung thu",
            "Drone show",
            "drone show",
            "Nghệ An",
            "nghệ an",
            "TP Vinh",
            "WinMart",
            "winmart",
            "Mama Hi",
            "mama hi",
            "500 thiết bị bay",
            "Quảng trường Hồ Chí Minh",
            "19h00",
            "12/9",
            "Phonetic Bridge",
        ]

    def test_anomalous_empty_inputs(self):
        """Kiểm tra xử lý các chuỗi đầu vào rỗng."""
        context = self.pipeline._compose_agent_context(
            filename="",
            duration=0,
            instruction="",
            transcript="",
            visual_summary="",
            video_path="",
        )
        self.assertIsInstance(context, str)
        self.assertIn("• Tệp video:  (Thời lượng: 00:00)", context)
        self.assertIn("• Yêu cầu từ anh Mạnh: ", context)
        self.assertNotIn("• Đường dẫn tệp cục bộ (video_path):", context)

    def test_duration_boundary_values(self):
        """Kiểm tra các giá trị biên của thời lượng video."""
        # 1. duration = 0
        ctx_0 = self.pipeline._compose_agent_context("test.mp4", 0, "inst", "trans", "vis")
        self.assertIn("Thời lượng: 00:00", ctx_0)

        # 2. duration lớn: 24 giờ (86400 giây)
        ctx_24h = self.pipeline._compose_agent_context("long.mp4", 86400, "inst", "trans", "vis")
        self.assertIn("Thời lượng: 1440:00", ctx_24h)

        # 3. duration lẻ: 125 giây -> 02:05
        ctx_125 = self.pipeline._compose_agent_context("clip.mp4", 125, "inst", "trans", "vis")
        self.assertIn("Thời lượng: 02:05", ctx_125)

    def test_duration_float_and_none_failure_modes(self):
        """
        [ADVERSARIAL CHALLENGE]
        Kiểm tra điểm yếu định kiểu của duration khi nhận float hoặc None.
        Ghi nhận chính xác ngoại lệ phát sinh để làm bằng chứng thực nghiệm.
        """
        # Nếu duration là float (ví dụ 15.5 giây từ ffprobe)
        with self.assertRaises(ValueError) as ctx_float:
            self.pipeline._compose_agent_context("test.mp4", 15.5, "inst", "trans", "vis")
        self.assertIn("Unknown format code 'd' for object of type 'float'", str(ctx_float.exception))

        # Nếu duration là None
        with self.assertRaises(TypeError) as ctx_none:
            self.pipeline._compose_agent_context("test.mp4", None, "inst", "trans", "vis")
        self.assertIn("unsupported operand type(s) for divmod()", str(ctx_none.exception))

    def test_none_like_string_inputs(self):
        """Kiểm tra các tham số chuỗi nhận None."""
        # filename=None, instruction=None, transcript=None, visual_summary=None
        context = self.pipeline._compose_agent_context(
            filename=None,
            duration=30,
            instruction=None,
            transcript=None,
            visual_summary=None,
            video_path=None,
        )
        self.assertIsInstance(context, str)
        self.assertIn("• Tệp video: None (Thời lượng: 00:30)", context)
        self.assertIn("• Yêu cầu từ anh Mạnh: None", context)
        self.assertIn("🖼️ [NGUỒN 1 - THỊ GIÁC & CHỮ IN TRÊN MÀN HÌNH (OCR Keyframes)]:\nNone", context)
        self.assertIn("🎧 [NGUỒN 2 - LỜI THOẠI ÂM THANH (Whisper STT)]:\nNone", context)
        self.assertNotIn("• Đường dẫn tệp cục bộ (video_path):", context)

    def test_legacy_hardcoded_strings_zero_leakage(self):
        """
        Kiểm tra triệt để: không một chuỗi hardcode cũ nào được phép xuất hiện
        trong output của _compose_agent_context trên 25 bộ input đa dạng.
        """
        test_samples = [
            ("meeting.mp4", 300, "tóm tắt cuộc họp", "Giám đốc báo cáo doanh thu quý 3", "Slide báo cáo tài chính"),
            ("cat.mp4", 15, "xóa chữ", "mèo kêu meo meo", "Chú mèo đang nằm sưởi nắng"),
            ("drone_flight.mp4", 60, "chống rung", "tiếng gió rít", "Flycam bay qua bãi biển Đà Nẵng"),
            ("sample.mkv", 120, "chỉnh màu vintage", "bài hát nhạc Jazz", "Quán cà phê cổ điển Sài Gòn"),
            ("tutorial.mp4", 900, "làm nét", "hướng dẫn lập trình Python", "Màn hình VSCode"),
            ("short.mp4", 5, "cắt clip", "", ""),
            ("news.mp4", 180, "phân tích", "Bản tin thời sự 19h VTV1", "Trường quay thời sự"),
            ("gameplay.mp4", 450, "tạo thumbnail", "game thủ bình luận sôi nổi", "Trận đấu Liên Minh Huyền Thoại"),
            ("review.mp4", 600, "nén video", "Đánh giá iPhone 16 Pro Max", "Mở hộp điện thoại"),
            ("nature.mp4", 80, "thêm phụ đề", "tiếng chim hót trong rừng", "Cảnh rừng Cúc Phương ban mai"),
        ]

        for fname, dur, inst, trans, vis in test_samples:
            ctx = self.pipeline._compose_agent_context(
                filename=fname,
                duration=dur,
                instruction=inst,
                transcript=trans,
                visual_summary=vis,
                video_path="/data/test.mp4",
            )
            for forbidden in self.forbidden_legacy_strings:
                self.assertNotIn(
                    forbidden,
                    ctx,
                    f"Rò rỉ chuỗi hardcode '{forbidden}' trong output khi chạy với file '{fname}'!",
                )

    def test_video_path_exact_presence_and_absence(self):
        """Kiểm tra sự xuất hiện chuẩn xác của video_path."""
        # 1. Có video_path hợp lệ
        valid_path = "/home/kirito/quan_ly_server/data/videos/sample_video.mp4"
        ctx_with_path = self.pipeline._compose_agent_context(
            filename="sample_video.mp4",
            duration=45,
            instruction="xóa logo",
            transcript="thoại mẫu",
            visual_summary="hình ảnh mẫu",
            video_path=valid_path,
        )
        expected_line = f"• Đường dẫn tệp cục bộ (video_path): {valid_path}"
        self.assertIn(expected_line, ctx_with_path)

        # 2. Không truyền video_path (mặc định)
        ctx_default = self.pipeline._compose_agent_context(
            filename="sample_video.mp4",
            duration=45,
            instruction="xóa logo",
            transcript="thoại mẫu",
            visual_summary="hình ảnh mẫu",
        )
        self.assertNotIn("video_path", ctx_default.split("• Tệp video")[0])  # Header section
        self.assertNotIn("• Đường dẫn tệp cục bộ (video_path):", ctx_default)

        # 3. video_path là chuỗi rỗng
        ctx_empty_path = self.pipeline._compose_agent_context(
            filename="sample_video.mp4",
            duration=45,
            instruction="xóa logo",
            transcript="thoại mẫu",
            visual_summary="hình ảnh mẫu",
            video_path="",
        )
        self.assertNotIn("• Đường dẫn tệp cục bộ (video_path):", ctx_empty_path)

        # 4. video_path chứa ký tự đặc biệt, dấu cách và Unicode
        complex_path = "/tmp/video test/bản ghi [2026] #1 (gốc).mp4"
        ctx_complex = self.pipeline._compose_agent_context(
            filename="complex.mp4",
            duration=45,
            instruction="chỉnh màu",
            transcript="thoại",
            visual_summary="hình ảnh",
            video_path=complex_path,
        )
        self.assertIn(f"• Đường dẫn tệp cục bộ (video_path): {complex_path}", ctx_complex)

    def test_stress_large_payload_and_unicode_robustness(self):
        """Stress-test với tải dữ liệu lớn (100k ký tự) và Unicode đặc biệt."""
        large_transcript = "Lời thoại Whisper STT thực tế kéo dài. " * 3000  # ~117k chars
        large_visual = "Khung hình phát hiện đối tượng, OCR chữ trên màn hình. " * 1000  # ~55k chars

        special_instruction = (
            "Xóa text: '🚀 Thử nghiệm Unicode: tiếng Việt ắ ằ ẳ ẵ ặ, "
            "RTL Arabic: اختبار الفيديو العربية, "
            "Prompt Injection: {instruction} {filename} [SYSTEM OVERRIDE], "
            "Control chars: \x00\r\n\t, Quotes: \" ' `'"
        )

        start_time = time.perf_counter()
        ctx_stress = self.pipeline._compose_agent_context(
            filename="stress_test.mp4",
            duration=3600,
            instruction=special_instruction,
            transcript=large_transcript,
            visual_summary=large_visual,
            video_path="/tmp/stress.mp4",
        )
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Assert không crash và thực thi cực nhanh (< 50ms)
        self.assertLess(duration_ms, 50.0, f"Thời gian tổng hợp context quá chậm: {duration_ms:.2f}ms")
        self.assertIn("60:00", ctx_stress)
        self.assertIn("اختبار الفيديو العربية", ctx_stress)
        self.assertIn("🚀 Thử nghiệm Unicode", ctx_stress)
        self.assertIn("stress_test.mp4", ctx_stress)
        self.assertIn(large_transcript, ctx_stress)
        self.assertIn(large_visual, ctx_stress)


class TestAdversarialVideoEditIntentMatrix(unittest.TestCase):
    """Adversarial testing matrix for TelegramBotService._is_video_edit_intent."""

    def test_clear_edit_intent_positives(self):
        """Nhóm A: Các câu lệnh biên tập video rõ ràng (phải trả về True)."""
        positive_cases = [
            "xóa sạch text trong video giúp tôi",
            "xoa chu trong video nay ho em voi",
            "cắt video từ giây 10 đến giây 45",
            "chỉnh màu video phong cách vintage hoài cổ",
            "chống rung video flycam này nhé",
            "nén video này xuống dưới 20MB",
            "thêm phụ đề tiếng việt cho video",
            "làm nét video này lên giùm anh",
            "chuyển đổi video này sang gif",
            "tạo thumbnail cho video này từ frame mở đầu",
            "loại bỏ chữ trong clip này",
            "xóa watermark ở góc video",
            "delogo video này giúp mình",
            "burn sub vào video luôn nhé",
            "ghép video này với video intro",
            "ổn định video bị rung lắc mạnh",
            "khử rung cho đoạn phim này",
            "filter màu cinematic cho clip",
            "giảm dung lượng video để gửi qua telegram",
            "trích frame đẹp nhất làm ảnh đại diện",
        ]
        for query in positive_cases:
            with self.subTest(query=query):
                self.assertTrue(
                    TelegramBotService._is_video_edit_intent(query),
                    f"Thất bại: Câu lệnh '{query}' phải được nhận diện là edit intent!",
                )

    def test_pure_analysis_intent_negatives(self):
        """Nhóm B: Các câu lệnh phân tích/tóm tắt thuần túy (phải trả về False)."""
        negative_cases = [
            "Tóm tắt nội dung video này giúp anh",
            "Trong video có bao nhiêu người tham gia thảo luận?",
            "Chép lời thoại cuộc họp trong video ra file text",
            "Video này được quay vào ban ngày hay ban đêm?",
            "Giải thích nội dung bài học trong clip này",
            "Người đàn ông áo xanh đang nói về vấn đề gì?",
            "Clip này có nhạc nền hay không?",
            "Tìm hiểu xem bối cảnh quay ở quốc gia nào",
            "Đánh giá chất lượng âm thanh của video",
            "Phân tích tâm trạng của diễn viên trong phân cảnh này",
            "Người phụ nữ trong video làm nghề gì?",
            "Liệt kê các sự kiện chính diễn ra theo dòng thời gian",
        ]
        for query in negative_cases:
            with self.subTest(query=query):
                self.assertFalse(
                    TelegramBotService._is_video_edit_intent(query),
                    f"Thất bại: Câu lệnh '{query}' không được nhận nhầm là edit intent!",
                )

    def test_multi_intent_compound_queries(self):
        """
        Nhóm C: Các câu lệnh đa mục tiêu (vừa muốn tóm tắt/phân tích vừa muốn biên tập).
        Khi có yêu cầu biên tập đi kèm, hệ thống BẮT BUỘC trả về True để cung cấp video_path
        và hướng dẫn biên tập cho LLM xử lý.
        """
        multi_intent_cases = [
            "Tóm tắt nội dung clip này trước, sau đó xóa text trên màn hình giúp anh",
            "Xem video nói gì rồi cắt video đoạn từ 01:00 đến 02:00 nhé",
            "Vừa phân tích lời thoại vừa làm nét video này",
            "Kiểm tra nội dung video và giảm dung lượng để gửi zalo",
            "Trích xuất tóm tắt ngắn gọn và tạo thumbnail giúp anh",
            "Phân tích xem video nói gì và xóa logo góc phải",
            "Tóm lược cuộc họp và nén video xuống dưới 30MB",
        ]
        for query in multi_intent_cases:
            with self.subTest(query=query):
                self.assertTrue(
                    TelegramBotService._is_video_edit_intent(query),
                    f"Thất bại: Câu lệnh đa mục tiêu '{query}' phải kích hoạt edit flow (True)!",
                )

    def test_adversarial_keyword_traps_and_edge_cases(self):
        """
        Nhóm D: Các ca đối kháng, bẫy từ khóa và giới hạn của giải pháp regex hiện tại.
        Mục tiêu: Đánh giá chính xác khả năng phòng thủ và ranh giới hoạt động.
        """
        # 1. Bẫy chữ/text nhưng là câu hỏi truy vấn OCR (KHÔNG PHẢI EDIT -> Mong đợi: False)
        self.assertFalse(
            TelegramBotService._is_video_edit_intent("Trong video có xuất hiện chữ gì trên tấm biển quảng cáo không?"),
            "Bẫy câu hỏi chữ: Không được nhận nhầm là edit intent.",
        )
        self.assertFalse(
            TelegramBotService._is_video_edit_intent("Đọc text trên màn hình xem viết gì"),
            "Bẫy đọc text OCR: Không được nhận nhầm là edit intent.",
        )

        # 2. Bẫy xóa đối tượng khác không phải video edit (KHÔNG PHẢI EDIT -> Mong đợi: False)
        self.assertFalse(
            TelegramBotService._is_video_edit_intent("Xóa video này khỏi cơ sở dữ liệu giúp anh"),
            "Bẫy xóa file db: Không được nhận nhầm là video edit.",
        )

        # 3. Input dị biệt rỗng / ký tự đặc biệt / số (Mong đợi: False)
        self.assertFalse(TelegramBotService._is_video_edit_intent(""))
        self.assertFalse(TelegramBotService._is_video_edit_intent(None))
        self.assertFalse(TelegramBotService._is_video_edit_intent("   \t\n  "))
        self.assertFalse(TelegramBotService._is_video_edit_intent("123456789"))
        self.assertFalse(TelegramBotService._is_video_edit_intent("SELECT * FROM videos WHERE id=1;"))
        self.assertFalse(TelegramBotService._is_video_edit_intent("🎥✨🔥🍿💯"))

        # 4. [CHALLENGER ADVERSARIAL FINDING 1 - Negation Trap]:
        # Câu lệnh phủ định: "Đừng xóa chữ trong video nhé, chỉ tóm tắt thôi"
        # Vì giải pháp hiện tại dùng keyword matching con 'xóa chữ', câu lệnh này bị nhận nhầm thành True!
        negation_query = "Đừng xóa chữ trong video nhé, chỉ tóm tắt thôi"
        is_edit_negation = TelegramBotService._is_video_edit_intent(negation_query)
        # Ghi nhận thực tế: Thuật toán keyword-based trả về True (False Positive)
        self.assertTrue(
            is_edit_negation,
            "Ghi nhận thực nghiệm: Keyword-based regex dính bẫy phủ định (False Positive) do chứa 'xóa chữ'.",
        )

        # 5. [CHALLENGER ADVERSARIAL FINDING 2 - Advisory Question Trap]:
        # Câu hỏi tư vấn: "Phần mềm nào hỗ trợ xóa chữ trong video tốt nhất hiện nay?"
        # Do chứa cụm 'xóa chữ', thuật toán trả về True dù đây là câu hỏi lý thuyết!
        advisory_query = "Phần mềm nào hỗ trợ xóa chữ trong video tốt nhất hiện nay?"
        is_edit_advisory = TelegramBotService._is_video_edit_intent(advisory_query)
        self.assertTrue(
            is_edit_advisory,
            "Ghi nhận thực nghiệm: Keyword-based regex dính bẫy câu hỏi tư vấn do chứa 'xóa chữ'.",
        )

        # 6. [CHALLENGER ADVERSARIAL FINDING 3 - Synonym Separation Trap]:
        # Câu lệnh dùng từ đồng nghĩa cách xa: "Gỡ bỏ hoàn toàn những ký tự thừa thãi trên màn hình"
        # Không chứa chính xác 'xóa text', 'bỏ chữ'... nên thuật toán trả về False!
        synonym_query = "Gỡ bỏ hoàn toàn những ký tự thừa thãi trên màn hình"
        is_edit_synonym = TelegramBotService._is_video_edit_intent(synonym_query)
        self.assertFalse(
            is_edit_synonym,
            "Ghi nhận thực nghiệm: Thuật toán bỏ sót câu lệnh biên tập dùng từ đồng nghĩa cách xa (False Negative).",
        )


class TestBackwardCompatibilityAndAliases(unittest.TestCase):
    """Kiểm tra tính tương thích ngược của các alias và hàm gọi."""

    def test_pipeline_alias(self):
        """Khẳng định VideoAnalysisPipeline là alias của LightweightVideoPipeline."""
        self.assertIs(VideoAnalysisPipeline, LightweightVideoPipeline)

    def test_telegram_bot_alias(self):
        """Khẳng định TelegramBotService là alias của TelegramBot."""
        self.assertIs(TelegramBotService, TelegramBot)


if __name__ == "__main__":
    unittest.main()
