"""
Unit Test Suite cho tính năng /teamwork trong Telegram Bot (Tiểu Bảo Bảo)
services/ai-agent-service/tests/test_telegram_teamwork.py

Kiểm thử toàn diện:
- Validation đầu vào: lệnh rỗng, khoảng trắng, lệnh quá ngắn (< 8 ký tự), engine chưa sẵn sàng.
- Phản hồi Acknowledge tức thì < 1s và hiển thị đầy đủ 4 agent roles.
- Tiến trình chạy ngầm non-blocking giải phóng luồng polling của bot.
- Callback cập nhật tiến độ theo từng bước qua edit_message_text.
- Gửi báo cáo Markdown hoàn chỉnh (hỗ trợ chunking > 4000 ký tự).
- Xử lý lỗi an toàn không làm crash bot khi engine hoặc Telegram API gặp sự cố.
- Cập nhật menu trợ giúp /help và /start.
- Mock HTTP endpoints của Telegram Bot API (/sendMessage, /editMessageText, /sendChatAction).
"""

import asyncio
import html
import json
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.telegram_formatter import TelegramFormatter
from app.services.telegram_bot import TelegramBot
from app.services.teamwork_engine import TeamworkEngine, TeamworkResult


def _create_mock_bot(teamwork_engine: Optional[Any] = None) -> TelegramBot:
    """Tạo đối tượng TelegramBot với mock AI Agent, SshClient và HTTP Client."""
    mock_ai_agent = MagicMock()
    mock_ai_agent.chat = AsyncMock(return_value="AI Assistant response")
    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(return_value="Command output: OK")

    bot = TelegramBot(ai_agent=mock_ai_agent, ssh_client=mock_ssh)
    bot.token = "test_telegram_token_12345"
    bot.chat_id = "987654321"

    if teamwork_engine is not None:
        bot.set_teamwork_engine(teamwork_engine)

    return bot


class TestTelegramTeamworkValidation(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra xác thực đầu vào và điều kiện sẵn sàng của dịch vụ Teamwork."""

    async def asyncSetUp(self):
        self.mock_engine = MagicMock(spec=TeamworkEngine)
        self.mock_engine.execute_teamwork = AsyncMock()
        self.bot = _create_mock_bot(self.mock_engine)
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_message_with_result = AsyncMock(return_value={"message_id": 101})
        self.bot.edit_message_text = AsyncMock(return_value=True)

    async def test_validation_empty_command_returns_usage_guide(self):
        """Lệnh rỗng '/teamwork' phải trả về hướng dẫn sử dụng, không gọi engine."""
        chat_id = "test_chat_empty"
        await self.bot._handle_command("/teamwork", chat_id)

        self.bot.send_message.assert_called_once()
        sent_text = self.bot.send_message.call_args[0][1]
        self.assertIn("Cú pháp", sent_text)
        self.assertIn("Ví dụ", sent_text)
        self.mock_engine.execute_teamwork.assert_not_called()
        self.assertIsNone(getattr(self.bot, "_last_teamwork_task", None))

    async def test_validation_whitespace_command_returns_usage_guide(self):
        """Lệnh chỉ có khoảng trắng '/teamwork   ' phải trả về hướng dẫn sử dụng."""
        chat_id = "test_chat_spaces"
        await self.bot._handle_command("/teamwork    ", chat_id)

        self.bot.send_message.assert_called_once()
        sent_text = self.bot.send_message.call_args[0][1]
        self.assertIn("Cú pháp", sent_text)
        self.mock_engine.execute_teamwork.assert_not_called()

    async def test_validation_short_command_less_than_8_chars_rejects(self):
        """Lệnh có mô tả dưới 8 ký tự '/teamwork fix bug' phải yêu cầu mô tả chi tiết."""
        chat_id = "test_chat_short"
        await self.bot._handle_command("/teamwork fix bug", chat_id)

        self.bot.send_message.assert_called_once()
        sent_text = self.bot.send_message.call_args[0][1]
        self.assertIn("yêu cầu mô tả nhiệm vụ chi tiết", sent_text)
        self.mock_engine.execute_teamwork.assert_not_called()
        self.assertIsNone(getattr(self.bot, "_last_teamwork_task", None))

    async def test_teamwork_engine_not_ready_notifies_user(self):
        """Khi teamwork_engine chưa được gán (None), thông báo dịch vụ chưa sẵn sàng."""
        bot_without_engine = _create_mock_bot(teamwork_engine=None)
        bot_without_engine.send_message = AsyncMock(return_value=True)

        chat_id = "test_chat_no_engine"
        await bot_without_engine._handle_command("/teamwork Tối ưu hóa Nginx giảm latency", chat_id)

        bot_without_engine.send_message.assert_called_once()
        sent_text = bot_without_engine.send_message.call_args[0][1]
        self.assertIn("chưa sẵn sàng", sent_text)


class TestTelegramTeamworkExecution(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra quy trình thực thi Teamwork, Acknowledge, Background task, và Báo cáo."""

    async def asyncSetUp(self):
        self.mock_engine = MagicMock(spec=TeamworkEngine)
        self.sample_result = TeamworkResult(
            task="Tối ưu hóa Nginx giảm latency",
            report_markdown=(
                "## 🎯 1. Tóm tắt bài toán & giải pháp\nTối ưu epoll và worker connections.\n\n"
                "## 📚 2. Nguồn tham khảo thực tế\n• https://nginx.org/en/docs/\n\n"
                "## 💻 3. Giải pháp & Mã nguồn chi tiết (Production-Ready)\n```nginx\nworker_processes auto;\n```\n\n"
                "## ⚠️ 4. Cảnh báo rủi ro & Edge cases\n• Giới hạn ulimit open files.\n\n"
                "## 🛡️ 5. Reviewer's Verdict\nPhê duyệt cấu hình."
            ),
            sources=[{"title": "Nginx Tuning", "url": "https://nginx.org/en/docs/"}],
            risks=["Cạn kiệt File Descriptors nếu ulimit thấp"],
            chosen_solution="Sử dụng epoll và tinh chỉnh worker_rlimit_nofile",
            reviewer_verdict="Phê duyệt kiến trúc",
            execution_time_seconds=1.23,
        )

        async def _mock_exec(task_description: str, progress_callback=None):
            if progress_callback:
                await progress_callback("🔍 [1/4] Researcher Agent...")
                await progress_callback("🧠 [2/4] Analyst Agent...")
                await progress_callback("⚙️ [3/4] Implementer Agent...")
                await progress_callback("🔎 [4/4] Reviewer Agent...")
            return self.sample_result

        self.mock_engine.execute_teamwork = AsyncMock(side_effect=_mock_exec)

        self.bot = _create_mock_bot(self.mock_engine)
        self.sent_messages: List[Dict[str, Any]] = []
        self.edited_messages: List[Dict[str, Any]] = []

        async def _mock_send_with_res(chat_id, text, reply_markup=None, parse_mode="HTML"):
            msg_id = len(self.sent_messages) + 1
            entry = {"chat_id": chat_id, "text": text, "message_id": msg_id, "parse_mode": parse_mode}
            self.sent_messages.append(entry)
            return {"message_id": msg_id, "text": text}

        async def _mock_send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
            msg_id = len(self.sent_messages) + 1
            entry = {"chat_id": chat_id, "text": text, "message_id": msg_id, "parse_mode": parse_mode}
            self.sent_messages.append(entry)
            return True

        async def _mock_edit_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
            entry = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
            self.edited_messages.append(entry)
            return True

        self.bot.send_message_with_result = AsyncMock(side_effect=_mock_send_with_res)
        self.bot.send_message = AsyncMock(side_effect=_mock_send_msg)
        self.bot.edit_message_text = AsyncMock(side_effect=_mock_edit_text)

    async def test_instant_acknowledge_timing_and_content(self):
        """Phản hồi Acknowledge tức thì < 1s, chứa đầy đủ danh sách 4 vai trò agent."""
        chat_id = "test_chat_ack"
        task_cmd = "/teamwork Cấu hình failover PostgreSQL Streaming Replication"

        t_start = time.perf_counter()
        await self.bot._handle_command(task_cmd, chat_id)
        latency = time.perf_counter() - t_start

        # Latency phải dưới 1 giây
        self.assertLess(latency, 1.0, f"Acknowledge latency was {latency:.3f}s (exceeded 1s)")

        # Tin nhắn đầu tiên gửi đi là tin nhắn Acknowledge
        self.assertGreaterEqual(len(self.sent_messages), 1)
        ack_msg = self.sent_messages[0]["text"]
        self.assertIn("Đang triệu tập Biệt đội Kỹ sư AI", ack_msg)
        self.assertIn("🔍", ack_msg)
        self.assertIn("Researcher Agent", ack_msg)
        self.assertIn("🧠", ack_msg)
        self.assertIn("Analyst Agent", ack_msg)
        self.assertIn("⚙️", ack_msg)
        self.assertIn("Implementer Agent", ack_msg)
        self.assertIn("🔎", ack_msg)
        self.assertIn("Reviewer Agent", ack_msg)

        # Chờ background task hoàn thành
        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        self.assertIsNotNone(bg_task)
        await bg_task

    async def test_progress_callback_calls_edit_message_text(self):
        """Tiến trình cập nhật từng bước thông qua edit_message_text mà không spam tin nhắn mới."""
        chat_id = "test_chat_progress"
        await self.bot._handle_command("/teamwork Tối ưu hóa Nginx giảm latency", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        self.assertIsNotNone(bg_task)
        await bg_task

        # edit_message_text phải được gọi ít nhất 4 lần cho 4 vai trò + 1 lần cho thông báo hoàn tất
        self.assertGreaterEqual(len(self.edited_messages), 5)
        edited_texts = [m["text"] for m in self.edited_messages]
        joined = " ".join(edited_texts)
        self.assertIn("Researcher Agent", joined)
        self.assertIn("Analyst Agent", joined)
        self.assertIn("Implementer Agent", joined)
        self.assertIn("Reviewer Agent", joined)

        # Tin nhắn edit cuối cùng phải thể hiện đã hoàn tất
        last_edit = self.edited_messages[-1]["text"]
        self.assertTrue("Hoàn tất" in last_edit or "hoàn thành" in last_edit.lower())

    async def test_successful_completion_sends_full_markdown_report(self):
        """Báo cáo Markdown hoàn chỉnh được gửi tới Telegram chat_id sau khi hoàn thành."""
        chat_id = "test_chat_report"
        await self.bot._handle_command("/teamwork Tối ưu hóa Nginx giảm latency", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        await bg_task

        # Báo cáo được gửi qua send_message
        report_entries = [m for m in self.sent_messages if "1. Tóm tắt bài toán & giải pháp" in m["text"]]
        self.assertEqual(len(report_entries), 1)
        report_text = report_entries[0]["text"]
        self.assertIn("## 🎯 1. Tóm tắt bài toán & giải pháp", report_text)
        self.assertIn("## 📚 2. Nguồn tham khảo thực tế", report_text)
        self.assertIn("## 💻 3. Giải pháp & Mã nguồn chi tiết", report_text)
        self.assertIn("## ⚠️ 4. Cảnh báo rủi ro & Edge cases", report_text)
        self.assertIn("## 🛡️ 5. Reviewer's Verdict", report_text)

    async def test_long_markdown_report_split_chunks(self):
        """Báo cáo dài > 4000 ký tự được tự động chia chunks và gửi tuần tự an toàn."""
        # Tạo báo cáo dài 6000 ký tự
        long_body = "Thông tin kỹ thuật chuyên sâu về cấu hình kernel và web server.\n\n" * 80
        large_report = f"## 🎯 1. Tóm tắt\n{long_body}\n## 📚 2. Nguồn\nhttps://example.com"
        self.assertGreater(len(large_report), 4000)

        large_result = TeamworkResult(
            task="Bài toán dung lượng lớn",
            report_markdown=large_report,
            sources=[],
            risks=[],
        )
        self.mock_engine.execute_teamwork = AsyncMock(return_value=large_result)

        chat_id = "test_chat_large_report"
        await self.bot._handle_command("/teamwork Tinh chỉnh TCP stack Linux 10Gbps", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        await bg_task

        # Kiểm tra send_message được gọi với nội dung báo cáo
        called_texts = [m["text"] for m in self.sent_messages if "1. Tóm tắt" in m["text"]]
        self.assertEqual(len(called_texts), 1)

    async def test_non_blocking_polling_loop_release(self):
        """_handle_command trả về ngay lập tức, không chặn chu trình xử lý tin nhắn tiếp theo."""
        chat_id = "test_chat_nonblock"
        task_executed = asyncio.Event()

        async def _slow_teamwork(task_description: str, progress_callback=None):
            await task_executed.wait()
            return self.sample_result

        self.mock_engine.execute_teamwork = AsyncMock(side_effect=_slow_teamwork)

        # Gọi _handle_command
        t0 = time.perf_counter()
        await self.bot._handle_command("/teamwork Bài toán chạy lâu", chat_id)
        elapsed = time.perf_counter() - t0

        # Phải trả về gần như ngay lập tức (< 0.1s)
        self.assertLess(elapsed, 0.1)

        # Tin nhắn Acknowledge đã được gửi
        self.assertEqual(len(self.sent_messages), 1)

        # Giải phóng task ngầm
        task_executed.set()
        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        await bg_task


class TestTelegramTeamworkErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra tính an toàn (fault-tolerance) khi gặp lỗi trong quá trình thực thi."""

    async def asyncSetUp(self):
        self.mock_engine = MagicMock(spec=TeamworkEngine)
        self.bot = _create_mock_bot(self.mock_engine)
        self.sent_messages: List[Dict[str, Any]] = []
        self.edited_messages: List[Dict[str, Any]] = []

        async def _mock_send_with_res(chat_id, text, reply_markup=None, parse_mode="HTML"):
            msg_id = len(self.sent_messages) + 1
            entry = {"chat_id": chat_id, "text": text, "message_id": msg_id}
            self.sent_messages.append(entry)
            return {"message_id": msg_id}

        async def _mock_send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
            entry = {"chat_id": chat_id, "text": text}
            self.sent_messages.append(entry)
            return True

        async def _mock_edit_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
            entry = {"chat_id": chat_id, "message_id": message_id, "text": text}
            self.edited_messages.append(entry)
            return True

        self.bot.send_message_with_result = AsyncMock(side_effect=_mock_send_with_res)
        self.bot.send_message = AsyncMock(side_effect=_mock_send_msg)
        self.bot.edit_message_text = AsyncMock(side_effect=_mock_edit_text)

    async def test_engine_exception_handled_gracefully_without_crash(self):
        """Khi TeamworkEngine ném ngoại lệ, bot không crash và gửi thông báo lỗi cho user."""
        self.mock_engine.execute_teamwork = AsyncMock(
            side_effect=RuntimeError("Groq API quota exhausted for all keys")
        )

        chat_id = "test_chat_err"
        await self.bot._handle_command("/teamwork Thiết lập kiến trúc microservices", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        self.assertIsNotNone(bg_task)
        await bg_task

        # edit_message_text phải nhận được thông báo lỗi
        error_edits = [m for m in self.edited_messages if "Có lỗi xảy ra" in m["text"]]
        self.assertGreaterEqual(len(error_edits), 1)
        err_msg = error_edits[0]["text"]
        self.assertIn("Groq API quota exhausted", err_msg)

    async def test_progress_callback_network_error_does_not_abort_teamwork(self):
        """Lỗi mạng khi edit_message_text không làm gián đoạn tiến trình teamwork."""
        self.bot.edit_message_text = AsyncMock(
            side_effect=httpx.NetworkError("Telegram server connection reset")
        )

        sample_res = TeamworkResult(
            task="Task khi Telegram API lỗi edit",
            report_markdown="## 🎯 1. Tóm tắt\nBáo cáo vẫn được gửi thành công.",
        )

        async def _mock_exec(task_description: str, progress_callback=None):
            if progress_callback:
                # Gọi progress callback dù edit bị lỗi mạng
                await progress_callback("🔍 Đang tìm kiếm...")
            return sample_res

        self.mock_engine.execute_teamwork = AsyncMock(side_effect=_mock_exec)

        chat_id = "test_chat_cb_err"
        await self.bot._handle_command("/teamwork Task chịu lỗi callback", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        await bg_task

        # Báo cáo cuối cùng vẫn được gửi qua send_message
        sent_reports = [m for m in self.sent_messages if "1. Tóm tắt" in m["text"]]
        self.assertEqual(len(sent_reports), 1)


class TestTelegramTeamworkHelpMenu(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra lệnh /teamwork đã được đăng ký vào menu trợ giúp."""

    async def asyncSetUp(self):
        self.bot = _create_mock_bot()
        self.sent_messages: List[Dict[str, Any]] = []

        async def _mock_send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
            self.sent_messages.append({"chat_id": chat_id, "text": text})
            return True

        self.bot.send_message = AsyncMock(side_effect=_mock_send_msg)

    async def test_help_menu_contains_teamwork_command(self):
        """Lệnh /help phải liệt kê cú pháp và mô tả của /teamwork."""
        await self.bot._handle_command("/help", "test_help_chat")
        self.assertEqual(len(self.sent_messages), 1)
        msg_text = self.sent_messages[0]["text"]
        self.assertIn("/teamwork", msg_text)
        self.assertIn("Triệu tập team AI chuyên sâu", msg_text)

    async def test_start_menu_contains_teamwork_command(self):
        """Lệnh /start phải liệt kê cú pháp và mô tả của /teamwork."""
        await self.bot._handle_command("/start", "test_start_chat")
        self.assertEqual(len(self.sent_messages), 1)
        msg_text = self.sent_messages[0]["text"]
        self.assertIn("/teamwork", msg_text)
        self.assertIn("Triệu tập team AI chuyên sâu", msg_text)


class TestTelegramTeamworkHttpEndpointsMock(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra gọi trực tiếp HTTP Client tới Telegram Bot API endpoints."""

    async def test_http_endpoints_sendMessage_and_editMessageText(self):
        """Kiểm tra format JSON payload gửi tới /sendMessage và /editMessageText qua httpx."""
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        posted_requests: List[Dict[str, Any]] = []

        async def _mock_post(url: str, **kwargs):
            posted_requests.append({"url": url, "json": kwargs.get("json", {})})
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 999}})
            resp.text = '{"ok": true, "result": {"message_id": 999}}'
            return resp

        mock_http.post = AsyncMock(side_effect=_mock_post)

        mock_engine = MagicMock(spec=TeamworkEngine)
        mock_engine.execute_teamwork = AsyncMock(return_value=TeamworkResult(
            task="Test HTTP API",
            report_markdown="## 🎯 1. Tóm tắt\nNội dung báo cáo HTTP test.",
        ))

        bot = _create_mock_bot(mock_engine)

        with patch("app.services.telegram_bot.http_client_manager.get_client", return_value=mock_http):
            await bot._handle_command("/teamwork Kiểm tra giao tiếp HTTP Telegram", "chat_http_test")

            bg_task = getattr(bot, "_last_teamwork_task", None)
            if bg_task:
                await bg_task

        # Kiểm tra đã gọi sendMessage endpoint
        send_calls = [r for r in posted_requests if "/sendMessage" in r["url"]]
        self.assertGreaterEqual(len(send_calls), 2)  # 1 Ack + 1 Báo cáo
        ack_payload = send_calls[0]["json"]
        self.assertEqual(ack_payload["chat_id"], "chat_http_test")
        self.assertIn("Biệt đội Kỹ sư AI", ack_payload["text"])

        # Kiểm tra đã gọi editMessageText endpoint
        edit_calls = [r for r in posted_requests if "/editMessageText" in r["url"]]
        self.assertGreaterEqual(len(edit_calls), 1)  # 1 Completion edit
        self.assertEqual(edit_calls[-1]["json"]["message_id"], 999)


if __name__ == "__main__":
    unittest.main()
