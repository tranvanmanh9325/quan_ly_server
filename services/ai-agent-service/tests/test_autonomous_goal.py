"""
Unit and Integration Tests for AutonomousGoalWorker (Milestone 1 - R1).

Verifies:
1. Empirical Contract from ORIGINAL_REQUEST.md.
2. Goal Creation & Automatic Decomposition.
3. Step-by-step Execution via AgentToolExecutor.
4. Spinal Safety Risk Tri-Tier Gating (Tier 3 Lethal Block & waiting_approval).
5. Retry count & Failure Handling.
6. Goal Cancellation.
7. Proactive Telegram Notifications.
8. Background Polling Loop (poll_once).
9. State Persistence across Worker Restarts (Zero State Loss).
"""

import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.autonomous_goal_worker import AutonomousGoalWorker, InMemoryTaskStore
from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
)


class TestAutonomousGoalWorker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Command executed successfully. Disk usage: 22%")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "12345678"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.mock_llm = MagicMock()
        self.mock_llm.complete = AsyncMock(return_value=None)

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_executor,
            telegram_bot=self.mock_telegram,
            llm_router=self.mock_llm,
            use_db=False,
            poll_interval_seconds=1,
        )
        await self.worker.ensure_tables()

    async def test_01_empirical_contract_from_original_request(self) -> None:
        """
        Khế ước kiểm thử thực nghiệm được quy định trong ORIGINAL_REQUEST.md:
        from app.services.autonomous_goal_worker import AutonomousGoalWorker
        worker = AutonomousGoalWorker()
        task_id = await worker.create_goal(
            goal='Kiểm tra disk usage và báo cáo',
            steps=[{'tool': 'run_command', 'args': {'command': 'df -h'}, 'verify': 'disk_info_obtained'}]
        )
        status = await worker.get_goal_status(task_id)
        """
        task_id = await self.worker.create_goal(
            goal="Kiểm tra disk usage và báo cáo",
            steps=[{"tool": "run_command", "args": {"command": "df -h"}, "verify": "disk_info_obtained"}],
        )
        self.assertIsInstance(task_id, str)
        self.assertTrue(task_id.startswith("task_"))

        status = await self.worker.get_goal_status(task_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["id"], task_id)
        self.assertEqual(status["goal"], "Kiểm tra disk usage và báo cáo")
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["current_step"], 0)
        self.assertEqual(len(status["steps"]), 1)
        self.assertEqual(status["steps"][0]["tool"], "run_command")

    async def test_02_goal_creation_with_llm_decomposition(self) -> None:
        """Goal creation decomposes via LLM when LLM provides structured plan JSON."""
        plan_json = json.dumps([
            {"step_id": 1, "tool": "run_command", "args": {"command": "uptime"}, "verify": "server_up"},
            {"step_id": 2, "tool": "get_system_health_report", "args": {}, "verify": "health_verified"}
        ])
        self.mock_llm.complete.return_value = {
            "choices": [{"message": {"content": f"```json\n{plan_json}\n```"}}]
        }

        task_id = await self.worker.create_goal(goal="Giám sát uptime và báo cáo sức khỏe")
        status = await self.worker.get_goal_status(task_id)

        self.assertIsNotNone(status)
        self.assertEqual(len(status["steps"]), 2)
        self.assertEqual(status["steps"][0]["tool"], "run_command")
        self.assertEqual(status["steps"][1]["tool"], "get_system_health_report")

    async def test_02b_goal_creation_with_heuristic_fallback(self) -> None:
        """Goal creation falls back to heuristic domain decomposition when LLM is unavailable."""
        self.mock_llm.complete.return_value = None

        task_id = await self.worker.create_goal(goal="Kiểm tra dung lượng ổ đĩa và dọn dẹp log")
        status = await self.worker.get_goal_status(task_id)

        self.assertIsNotNone(status)
        self.assertGreater(len(status["steps"]), 0)
        first_step = status["steps"][0]
        self.assertIn("tool", first_step)
        self.assertEqual(first_step["tool"], "run_command")

    async def test_03_execute_single_step_tier1_success(self) -> None:
        """Executing a Tier 1 Safe diagnostic step transitions to completed."""
        task_id = await self.worker.create_goal(
            goal="Kiểm tra RAM",
            steps=[{"tool": "run_command", "args": {"command": "free -m"}}],
            chat_id="999888",
        )
        task_record = await self.worker.get_goal_status(task_id)

        res = await self.worker.execute_pending_step(task_record)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["current_step"], 1)
        self.assertIn("Disk usage", res["steps"][0]["result"])

        # Verify proactive Telegram completion notification sent
        self.mock_telegram.send_message.assert_awaited()
        call_args = self.mock_telegram.send_message.call_args
        self.assertEqual(call_args[0][0], "999888")
        self.assertIn("Hoàn thành mục tiêu tự động", call_args[0][1])

    async def test_04_multi_step_execution_progression(self) -> None:
        """Task with multiple steps progresses sequentially step by step."""
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "free -m"}},
            {"step_id": 3, "tool": "run_command", "args": {"command": "docker ps"}},
        ]
        task_id = await self.worker.create_goal(goal="Health check đa bước", steps=steps)
        task_record = await self.worker.get_goal_status(task_id)

        # Step 1
        res1 = await self.worker.execute_pending_step(task_record)
        self.assertEqual(res1["status"], "running")
        self.assertEqual(res1["current_step"], 1)

        # Step 2
        res2 = await self.worker.execute_pending_step(res1)
        self.assertEqual(res2["status"], "running")
        self.assertEqual(res2["current_step"], 2)

        # Step 3 (Final)
        res3 = await self.worker.execute_pending_step(res2)
        self.assertEqual(res3["status"], "completed")
        self.assertEqual(res3["current_step"], 3)
        self.assertIsNotNone(res3["completed_at"])
        self.assertIn("steps", res3["result_json"])

    async def test_05_tier3_lethal_gating_blocks_execution(self) -> None:
        """Tier 3 Lethal command halts task execution, transitions to waiting_approval, sends Telegram alert."""
        dangerous_step = {
            "step_id": 1,
            "tool": "run_command",
            "args": {"command": "rm -rf /"},
        }
        task_id = await self.worker.create_goal(
            goal="Xóa toàn bộ dữ liệu máy chủ", steps=[dangerous_step], chat_id="111222"
        )
        task_record = await self.worker.get_goal_status(task_id)

        # Execute
        res = await self.worker.execute_pending_step(task_record)

        # Verify tool was NEVER executed
        self.mock_executor.execute_tool.assert_not_awaited()

        # Verify state transitioned to waiting_approval
        self.assertEqual(res["status"], "waiting_approval")
        self.assertEqual(res["current_step"], 0)
        self.assertIn("Tier 3 Lethal", res["error_message"])

        # Verify security warning sent to Telegram
        self.mock_telegram.send_message.assert_awaited()
        call_args = self.mock_telegram.send_message.call_args
        self.assertEqual(call_args[0][0], "111222")
        self.assertIn("CẢNH BÁO AN TOÀN VI MẠCH", call_args[0][1])

    async def test_06_step_failure_and_retry_limits(self) -> None:
        """Step failure increments retry_count; marks failed after max_retries."""
        self.mock_executor.execute_tool = AsyncMock(side_effect=RuntimeError("Connection refused by SSH daemon"))

        task_id = await self.worker.create_goal(
            goal="Nhiệm vụ lỗi",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "invalid-cmd"}}],
            chat_id="333444",
        )
        task_record = await self.worker.get_goal_status(task_id)

        # Retry 1
        res1 = await self.worker.execute_pending_step(task_record)
        self.assertEqual(res1["status"], "running")
        self.assertEqual(res1["retry_count"], 1)

        # Retry 2
        res2 = await self.worker.execute_pending_step(res1)
        self.assertEqual(res2["status"], "running")
        self.assertEqual(res2["retry_count"], 2)

        # Retry 3 (Reaches max_retries = 3)
        res3 = await self.worker.execute_pending_step(res2)
        self.assertEqual(res3["status"], "failed")
        self.assertEqual(res3["retry_count"], 3)
        self.assertIn("Failed at step 1", res3["error_message"])

        # Verify failure notification sent to Telegram
        self.mock_telegram.send_message.assert_awaited()
        call_args = self.mock_telegram.send_message.call_args
        self.assertIn("Mục tiêu tự động gặp sự cố", call_args[0][1])

    async def test_07_cancel_goal(self) -> None:
        """Goals can be cancelled while active; cancelling an already terminated goal returns False."""
        task_id = await self.worker.create_goal(
            goal="Theo dõi log server",
            steps=[{"tool": "run_command", "args": {"command": "journalctl -n 50"}}],
        )

        # Cancel active goal
        ok = await self.worker.cancel_goal(task_id, reason="User cancelled via bot")
        self.assertTrue(ok)

        status = await self.worker.get_goal_status(task_id)
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["error_message"], "User cancelled via bot")

        # Second cancel attempt on already cancelled goal should return False
        ok_second = await self.worker.cancel_goal(task_id)
        self.assertFalse(ok_second)

    async def test_08_list_goals_and_status_filtering(self) -> None:
        """list_goals returns all goals or filtered subset by status."""
        id1 = await self.worker.create_goal(goal="Goal 1", steps=[{"tool": "run_command", "args": {"command": "df"}}])
        id2 = await self.worker.create_goal(goal="Goal 2", steps=[{"tool": "run_command", "args": {"command": "free"}}])
        await self.worker.cancel_goal(id2)

        all_goals = await self.worker.list_goals()
        self.assertGreaterEqual(len(all_goals), 2)

        pending_goals = await self.worker.list_goals(status="pending")
        self.assertTrue(any(g["id"] == id1 for g in pending_goals))
        self.assertFalse(any(g["id"] == id2 for g in pending_goals))

        cancelled_goals = await self.worker.list_goals(status="cancelled")
        self.assertTrue(any(g["id"] == id2 for g in cancelled_goals))

    async def test_09_poll_once_processes_pending_tasks(self) -> None:
        """poll_once picks up all pending goals in batch and executes their current steps."""
        await self.worker.create_goal(goal="Batch Goal A", steps=[{"tool": "run_command", "args": {"command": "df"}}])
        await self.worker.create_goal(goal="Batch Goal B", steps=[{"tool": "run_command", "args": {"command": "uptime"}}])

        processed_count = await self.worker.poll_once()
        self.assertEqual(processed_count, 2)

        goals = await self.worker.list_goals(status="completed")
        self.assertGreaterEqual(len(goals), 2)

    async def test_10_persistence_resumes_from_current_step(self) -> None:
        """Simulate container restart: a new worker instance resumes from current_step without rerunning step 0."""
        store = InMemoryTaskStore()
        worker1 = AutonomousGoalWorker(tool_executor=self.mock_executor, use_db=False)
        worker1._in_memory_store = store

        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "step1"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "step2"}},
        ]
        task_id = await worker1.create_goal(goal="Multi-step across restarts", steps=steps)
        task = await worker1.get_goal_status(task_id)

        # Worker 1 completes step 1
        res1 = await worker1.execute_pending_step(task)
        self.assertEqual(res1["current_step"], 1)
        self.assertEqual(res1["status"], "running")

        # Worker 1 is stopped / container restarts
        await worker1.stop()

        # Worker 2 boots up with the same persistent store
        worker2 = AutonomousGoalWorker(tool_executor=self.mock_executor, use_db=False)
        worker2._in_memory_store = store

        # Worker 2 loads task and runs poll_once
        task_loaded = await worker2.get_goal_status(task_id)
        self.assertEqual(task_loaded["current_step"], 1)

        await worker2.poll_once()

        final_status = await worker2.get_goal_status(task_id)
        self.assertEqual(final_status["status"], "completed")
        self.assertEqual(final_status["current_step"], 2)


if __name__ == "__main__":
    unittest.main()
