"""
test_tool_r1_scheduler.py — Unit & Adversarial Tests for SchedulerService (R1).

Validates Smart Calendar & Scheduler interface contracts:
- schedule_reminder(message, delay_minutes, repeat)
- list_scheduled_reminders()
- cancel_reminder(reminder_id)
- InMemoryReminderStore fallback & thread safety
- Input validation (delay <= 0, invalid repeat, empty message)
"""

import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scheduler_service import (
    InMemoryReminderStore,
    SchedulerService,
    cancel_reminder,
    list_scheduled_reminders,
    schedule_reminder,
)


class TestSchedulerService(unittest.IsolatedAsyncioTestCase):
    """Test suite for SchedulerService (R1)."""

    async def asyncSetUp(self):
        # Use an isolated in-memory service for pure deterministic tests
        self.service = SchedulerService(use_db=False)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. schedule_reminder validation tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_schedule_reminder_success(self):
        res = await self.service.schedule_reminder("Nhắc uống nước", 15)
        self.assertEqual(res["status"], "success")
        self.assertIn("reminder_id", res)
        self.assertEqual(res["message"], "Nhắc uống nước")
        self.assertEqual(res["delay_minutes"], 15)
        self.assertEqual(res["repeat"], "none")
        self.assertEqual(res["storage"], "memory")
        self.assertIn("remind_at", res)
        self.assertIn("remind_at_vn", res)

    async def test_schedule_reminder_negative_delay(self):
        res = await self.service.schedule_reminder("Nhắc họp", -10)
        self.assertEqual(res["status"], "error")
        self.assertIn("phải lớn hơn 0", res["message"])

    async def test_schedule_reminder_zero_delay(self):
        res = await self.service.schedule_reminder("Nhắc ngay", 0)
        self.assertEqual(res["status"], "error")
        self.assertIn("phải lớn hơn 0", res["message"])

    async def test_schedule_reminder_invalid_delay_type(self):
        res = await self.service.schedule_reminder("Nhắc test", "mười_phút")
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])

    async def test_schedule_reminder_large_delay(self):
        # 1 year in minutes
        res = await self.service.schedule_reminder("Nhắc gia hạn domain", 525600)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["delay_minutes"], 525600)
        self.assertIsNotNone(datetime.fromisoformat(res["remind_at"]))

    async def test_schedule_reminder_repeat_daily(self):
        res = await self.service.schedule_reminder("Uống vitamin", 60, repeat="daily")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["repeat"], "daily")

    async def test_schedule_reminder_repeat_weekly(self):
        res = await self.service.schedule_reminder("Báo cáo tuần", 120, repeat="weekly")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["repeat"], "weekly")

    async def test_schedule_reminder_repeat_case_insensitive(self):
        res_d = await self.service.schedule_reminder("Họp daily", 10, repeat="DAILY")
        self.assertEqual(res_d["status"], "success")
        self.assertEqual(res_d["repeat"], "daily")

        res_w = await self.service.schedule_reminder("Họp weekly", 20, repeat="Weekly ")
        self.assertEqual(res_w["status"], "success")
        self.assertEqual(res_w["repeat"], "weekly")

    async def test_schedule_reminder_invalid_repeat(self):
        res = await self.service.schedule_reminder("Nhắc việc", 30, repeat="monthly")
        self.assertEqual(res["status"], "error")
        self.assertIn("Tần suất lặp 'monthly' không hợp lệ", res["message"])

    async def test_schedule_reminder_empty_message(self):
        res1 = await self.service.schedule_reminder("", 10)
        self.assertEqual(res1["status"], "error")

        res2 = await self.service.schedule_reminder("   ", 10)
        self.assertEqual(res2["status"], "error")

        res3 = await self.service.schedule_reminder(None, 10)
        self.assertEqual(res3["status"], "error")

    # ──────────────────────────────────────────────────────────────────────────
    # 2. list_scheduled_reminders tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_list_scheduled_reminders_empty(self):
        res = await self.service.list_scheduled_reminders()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["reminders"], [])

    async def test_list_scheduled_reminders_sorted(self):
        await self.service.schedule_reminder("Việc 2", 30)
        await self.service.schedule_reminder("Việc 1", 10)
        await self.service.schedule_reminder("Việc 3", 60)

        res = await self.service.list_scheduled_reminders()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["reminders"][0]["message"], "Việc 1")
        self.assertEqual(res["reminders"][1]["message"], "Việc 2")
        self.assertEqual(res["reminders"][2]["message"], "Việc 3")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. cancel_reminder tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_cancel_reminder_success(self):
        created = await self.service.schedule_reminder("Test hủy", 20)
        rem_id = created["reminder_id"]

        cancel_res = await self.service.cancel_reminder(rem_id)
        self.assertEqual(cancel_res["status"], "success")
        self.assertEqual(cancel_res["reminder_id"], rem_id)

        # After cancellation, list should be empty
        list_res = await self.service.list_scheduled_reminders()
        self.assertEqual(list_res["total"], 0)

    async def test_cancel_nonexistent_reminder(self):
        res = await self.service.cancel_reminder(999999)
        self.assertEqual(res["status"], "not_found")
        self.assertEqual(res["reminder_id"], 999999)

    async def test_cancel_invalid_id(self):
        res = await self.service.cancel_reminder("not-an-id")
        self.assertEqual(res["status"], "error")

    async def test_cancel_already_cancelled_reminder(self):
        created = await self.service.schedule_reminder("Test double cancel", 20)
        rem_id = created["reminder_id"]

        first_cancel = await self.service.cancel_reminder(rem_id)
        self.assertEqual(first_cancel["status"], "success")

        second_cancel = await self.service.cancel_reminder(rem_id)
        self.assertEqual(second_cancel["status"], "not_found")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Dispatching & Auto-Reschedule (daily / weekly)
    # ──────────────────────────────────────────────────────────────────────────

    async def test_mark_dispatched_reschedules_daily(self):
        created = await self.service.schedule_reminder("Daily ping", 10, repeat="daily")
        rem_id = created["reminder_id"]

        res = await self.service.mark_reminder_dispatched(rem_id)
        self.assertTrue(res)

        # Should still be pending with a future date
        pending = await self.service.list_scheduled_reminders()
        self.assertEqual(pending["total"], 1)
        self.assertEqual(pending["reminders"][0]["id"], rem_id)

    async def test_mark_dispatched_completes_non_repeating(self):
        created = await self.service.schedule_reminder("Single ping", 10, repeat="none")
        rem_id = created["reminder_id"]

        res = await self.service.mark_reminder_dispatched(rem_id)
        self.assertTrue(res)

        # Should no longer be pending
        pending = await self.service.list_scheduled_reminders()
        self.assertEqual(pending["total"], 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Concurrency & Thread-Safety
    # ──────────────────────────────────────────────────────────────────────────

    async def test_concurrent_scheduling(self):
        tasks = [
            self.service.schedule_reminder(f"Task #{i}", i + 1)
            for i in range(30)
        ]
        results = await asyncio.gather(*tasks)
        ids = [r["reminder_id"] for r in results]
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)  # All IDs must be unique

        listing = await self.service.list_scheduled_reminders()
        self.assertEqual(listing["total"], 30)


if __name__ == "__main__":
    unittest.main()
