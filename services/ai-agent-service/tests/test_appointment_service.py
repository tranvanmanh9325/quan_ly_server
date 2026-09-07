import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.appointment_service import AppointmentService
from app.core.llm_router import LlmRouter


class TestAppointmentService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = MagicMock(spec=LlmRouter)
        self.service = AppointmentService(self.router)

    def test_fast_keyword_filter(self):
        # Positive cases (Vietnamese appointment / scheduling triggers)
        self.assertTrue(self.service._fast_keyword_filter("Mai anh em mình đi cà phê nhé"))
        self.assertTrue(self.service._fast_keyword_filter("Chiều nay 3h họp bàn việc"))
        self.assertTrue(self.service._fast_keyword_filter("Tối mai bạn có rảnh không"))
        self.assertTrue(self.service._fast_keyword_filter("Thứ 6 tuần sau anh rảnh k?"))
        self.assertTrue(self.service._fast_keyword_filter("Ghé qua nhà em ăn cơm"))

        # Negative cases (General non-appointment text)
        self.assertFalse(self.service._fast_keyword_filter("Chào bạn, sản phẩm này giá bao nhiêu?"))
        self.assertFalse(self.service._fast_keyword_filter("Cảm ơn shop đã gửi hàng nhanh"))
        self.assertFalse(self.service._fast_keyword_filter(""))
        self.assertFalse(self.service._fast_keyword_filter(None))

    async def test_check_and_dispatch_reminders_no_bot(self):
        count = await self.service.check_and_dispatch_reminders(None)
        self.assertEqual(count, 0)

        bot_without_chat_id = MagicMock()
        bot_without_chat_id.chat_id = None
        count = await self.service.check_and_dispatch_reminders(bot_without_chat_id)
        self.assertEqual(count, 0)

    @patch("app.services.appointment_service.get_db_dict_cursor")
    async def test_check_and_dispatch_reminders_no_rows(self, mock_get_cur):
        mock_cur = AsyncMock()
        mock_cur.fetchall.return_value = []
        
        # Async context manager mock for get_db_dict_cursor
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_cm.__aexit__.return_value = None
        mock_get_cur.return_value = mock_cm

        mock_bot = MagicMock()
        mock_bot.chat_id = "123456"

        count = await self.service.check_and_dispatch_reminders(mock_bot)
        self.assertEqual(count, 0)
        mock_cur.execute.assert_called_once()
        self.assertIn("SELECT id, thread_href", mock_cur.execute.call_args[0][0])

    @patch("app.services.appointment_service.get_db_dict_cursor")
    async def test_check_and_dispatch_reminders_with_appointment(self, mock_get_cur):
        mock_cur = AsyncMock()
        mock_cur.fetchall.return_value = [
            {
                "id": 42,
                "thread_href": "/t/10001",
                "sender_name": "Nguyễn Văn A",
                "summary": "Gặp mặt trao đổi dự án",
                "proposed_time": "14:00 hôm nay",
                "location": "Highlands Coffee Landmark 81",
                "scheduled_at": "2026-09-08 14:00:00+07",
            }
        ]

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_cm.__aexit__.return_value = None
        mock_get_cur.return_value = mock_cm

        mock_bot = MagicMock()
        mock_bot.chat_id = "123456"
        mock_bot.send_message = AsyncMock(return_value=True)

        count = await self.service.check_and_dispatch_reminders(mock_bot)
        self.assertEqual(count, 1)

        # Verify telegram message was sent with reminder content
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args[1]
        self.assertEqual(call_kwargs["chat_id"], "123456")
        self.assertIn("Nguyễn Văn A", call_kwargs["text"])
        self.assertIn("Highlands Coffee Landmark 81", call_kwargs["text"])
        self.assertIn("Gặp mặt trao đổi dự án", call_kwargs["text"])

        # Verify database UPDATE was executed to mark reminder_sent = TRUE
        self.assertEqual(mock_cur.execute.call_count, 2)
        update_call = mock_cur.execute.call_args_list[1]
        self.assertIn("UPDATE facebook_appointments SET reminder_sent = TRUE", update_call[0][0])
        self.assertEqual(update_call[0][1], (42,))


if __name__ == "__main__":
    unittest.main()
