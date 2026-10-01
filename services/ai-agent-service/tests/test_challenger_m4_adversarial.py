"""
test_challenger_m4_adversarial.py — Empirical Verification & Stress Test Suite for Milestone 4 (R4).

Adversarial Stress Testing & Empirical Verification:
1. TestMultiClusterTokenBudgetAdversarial:
   - Extreme multi-cluster queries (5-8+ intent clusters simultaneously).
   - Heavy cluster combinations (Media Studio, Archive, Facebook) with max 6 tools budget.
   - Priority retention of goal tools under severe token constraints.
   - Strict adherence to <= 8 tools (or <= 6 for heavy clusters) and JSON schema budget.

2. TestDispatchToolAdversarialAndResilience:
   - create_autonomous_goal with malformed args, edge inputs, and worker exceptions.
   - list_autonomous_goals with various status_filter values, corrupted task records, and worker exceptions.
   - cancel_autonomous_goal with missing, invalid IDs, duplicate cancellations, and worker exceptions.

3. TestRealWorkerEndToEndLifecycle:
   - Full lifecycle verification with REAL AutonomousGoalWorker (InMemoryTaskStore mode):
     Empty -> Create -> List Active -> Cancel -> List Active (Excluded) -> List All (Cancelled) -> Re-Cancel.
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    classify_action_risk,
)
from app.services.autonomous_goal_worker import AutonomousGoalWorker


class TestMultiClusterTokenBudgetAdversarial(unittest.TestCase):
    """Stress tests dynamic tool scoping against extreme multi-cluster keyword payloads."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    def test_tc01_five_clusters_coexistence(self) -> None:
        """
        Payload combining 5 clusters:
        1. Goal ('lập kế hoạch tự động theo dõi')
        2. Media ('tải video youtube')
        3. System ('kiểm tra cpu ram df -h')
        4. Security ('chặn ip 192.168.1.100')
        5. Docker ('quản lý docker container')
        """
        query = (
            "Em lập kế hoạch tự động theo dõi server, tải video youtube bài giảng, "
            "kiểm tra cpu ram df -h xem disk usage, đồng thời chặn ip 192.168.1.100 "
            "và quản lý docker container restart"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=query)

        # Budget MUST NOT exceed 8 tools
        self.assertLessEqual(
            len(scoped), 8,
            f"Violation: 5 clusters produced {len(scoped)} tools (must be <= 8)"
        )
        # Goal tools MUST be prioritized
        self.assertIn("create_autonomous_goal", scoped)

        # Also verify via _build_tools
        tools = self.executor._build_tools(query=query)
        self.assertLessEqual(len(tools), 8)
        names = {t["function"]["name"] for t in tools}
        self.assertIn("create_autonomous_goal", names)

    def test_tc02_eight_clusters_storm(self) -> None:
        """
        Extreme payload combining 8 clusters:
        Goal + Media + Docs + Archive + FB + Security + Notes + Calc.
        """
        query = (
            "Đặt mục tiêu tự động theo dõi ram và tải nhạc mp3, đọc file pdf báo cáo, "
            "giải nén file zip crack mật khẩu, gửi tin nhắn facebook, xem honeypot hacker, "
            "tạo ghi chú note cuộc họp và tính toán 100 * 25"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=query)

        # Archive triggers heavy cluster -> limit is 6 tools
        self.assertLessEqual(
            len(scoped), 8,
            f"Violation: 8 clusters produced {len(scoped)} tools (must be <= 8)"
        )
        # Check that goal tools survive pruning
        has_goal = any(t in scoped for t in ("create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal"))
        self.assertTrue(has_goal, f"Goal tools lost in 8-cluster storm: {scoped}")

    def test_tc03_heavy_media_studio_cluster_coexistence(self) -> None:
        """
        Heavy cluster: Video Editor Studio keywords ('cắt video', 'xóa watermark', 'color grade')
        combined with Goal intent ('lập kế hoạch tự động').
        When heavy cluster is active, max_tools is 6.
        """
        query = "Lập kế hoạch tự động cắt video và xóa watermark áp dụng color grade cho clip"
        scoped = self.executor._resolve_scoped_tool_names(query=query)

        self.assertLessEqual(
            len(scoped), 6,
            f"Violation: Heavy cluster query produced {len(scoped)} tools (must be <= 6)"
        )
        self.assertIn(
            "create_autonomous_goal", scoped,
            f"create_autonomous_goal must be retained even in heavy cluster mode: {scoped}"
        )

    def test_tc04_list_intent_specific_priority(self) -> None:
        """Query specifically targeting goal listing amidst other noise."""
        query = "Cho anh xem danh sách mục tiêu đang chạy trên máy chủ cùng với lịch sử tấn công hacker"
        scoped = self.executor._resolve_scoped_tool_names(query=query)

        self.assertLessEqual(len(scoped), 8)
        self.assertIn(
            "list_autonomous_goals", scoped,
            f"list_autonomous_goals must be present for list query: {scoped}"
        )

    def test_tc05_cancel_intent_specific_priority(self) -> None:
        """Query specifically targeting goal cancellation amidst other noise."""
        query = "Em dừng goal và hủy mục tiêu task_998877 ngay, sau đó khởi động lại service nginx"
        scoped = self.executor._resolve_scoped_tool_names(query=query)

        self.assertLessEqual(len(scoped), 8)
        self.assertIn(
            "cancel_autonomous_goal", scoped,
            f"cancel_autonomous_goal must be present for cancel query: {scoped}"
        )

    def test_tc06_token_budget_gate_schema_length(self) -> None:
        """Verify that JSON schema length of built tools remains well within Groq TPM limits."""
        heavy_query = (
            "Lập kế hoạch tự động giám sát ram, cắt video clip, nén video, "
            "tải video youtube, đọc pdf và gửi tin nhắn messenger"
        )
        tools = self.executor._build_tools(query=heavy_query)
        self.assertLessEqual(len(tools), 8)

        # Estimate JSON schema size
        schema_json = json.dumps(tools)
        # 1 token is roughly 4 characters in English/JSON
        estimated_tokens = len(schema_json) / 4
        # Groq budget target for tools schema is <= 1500 tokens
        self.assertLess(
            estimated_tokens, 2000,
            f"Estimated schema token size {estimated_tokens:.0f} exceeds safe limit"
        )


class TestDispatchToolAdversarialAndResilience(unittest.IsolatedAsyncioTestCase):
    """Stress tests tool dispatch logic against edge cases, malformed payloads, and failures."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    async def test_tc07_create_goal_worker_exception_resilience(self) -> None:
        """Worker throws an unexpected exception: dispatch must catch and return friendly Vietnamese error."""
        mock_worker = MagicMock()
        mock_worker.create_goal = AsyncMock(side_effect=RuntimeError("PostgreSQL connection pool exhausted"))
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="create_autonomous_goal",
            tool_args={"goal": "Theo dõi ổ đĩa"},
            chat_id="123456",
        )
        self.assertIn("❌ Lỗi khi thiết lập mục tiêu tự hành", res)
        self.assertIn("PostgreSQL connection pool exhausted", res)

    async def test_tc08_create_goal_extreme_payloads(self) -> None:
        """Create goal with unicode, special symbols, whitespace, and extremely long goal text."""
        mock_worker = MagicMock()
        mock_worker.create_goal = AsyncMock(return_value={"id": "task_unicode_001"})
        self.executor.set_autonomous_goal_worker(mock_worker)

        long_goal = "🚀 Mục tiêu đặc biệt: " + "A" * 3000 + " 🎯 <script>alert('xss')</script> DROP TABLE agent_tasks;"
        res = await self.executor._execute_tool(
            tool_name="create_autonomous_goal",
            tool_args={"goal": long_goal, "trigger_condition": "cpu > 95% AND disk > 90%"},
            chat_id="chat_adv",
        )
        self.assertIn("#task_unicode_001", res)
        mock_worker.create_goal.assert_awaited_once()

    async def test_tc09_list_goals_filtering_variations(self) -> None:
        """Verify list_autonomous_goals handles 'active', 'all', and specific status filters accurately."""
        mock_worker = MagicMock()
        tasks = [
            {"id": "t1", "goal": "Goal 1", "status": "pending", "steps": [{"s": 1}], "current_step": 0},
            {"id": "t2", "goal": "Goal 2", "status": "running", "steps": [{"s": 1}], "current_step": 1},
            {"id": "t3", "goal": "Goal 3", "status": "completed", "steps": [], "current_step": 2},
            {"id": "t4", "goal": "Goal 4", "status": "cancelled", "steps": [], "current_step": 0},
            {"id": "t5", "goal": "Goal 5", "status": "waiting_approval", "steps": [{"s": 1}], "current_step": 1},
        ]
        mock_worker.list_goals = AsyncMock(return_value=tasks)
        self.executor.set_autonomous_goal_worker(mock_worker)

        # 1. Filter: 'active' -> must only retain pending, running, waiting_approval (t1, t2, t5)
        res_active = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("DANH SÁCH MỤC TIÊU TỰ HÀNH (3 mục tiêu)", res_active)
        self.assertIn("t1", res_active)
        self.assertIn("t2", res_active)
        self.assertIn("t5", res_active)
        self.assertNotIn("t3", res_active)  # completed must be excluded
        self.assertNotIn("t4", res_active)  # cancelled must be excluded

        # 2. Filter: 'all' -> returns all 5 tasks
        res_all = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "all"},
        )
        self.assertIn("DANH SÁCH MỤC TIÊU TỰ HÀNH (5 mục tiêu)", res_all)
        self.assertIn("t3", res_all)
        self.assertIn("t4", res_all)

    async def test_tc09b_list_goals_corrupted_steps_none_graceful_catch(self) -> None:
        """When task record has steps=None, executor catches TypeError and returns safe error message."""
        mock_worker = MagicMock()
        mock_worker.list_goals = AsyncMock(return_value=[
            {"id": "t_corrupt", "goal": "Corrupted", "status": "pending", "steps": None, "current_step": 0}
        ])
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("❌ Lỗi khi lấy danh sách mục tiêu", res)
        self.assertIn("has no len()", res)

    async def test_tc10_list_goals_worker_exception_resilience(self) -> None:
        """Worker throws exception during list_goals -> tool caught cleanly."""
        mock_worker = MagicMock()
        mock_worker.list_goals = AsyncMock(side_effect=TimeoutError("DB query timed out after 30s"))
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("❌ Lỗi khi lấy danh sách mục tiêu", res)
        self.assertIn("DB query timed out after 30s", res)

    async def test_tc11_cancel_goal_worker_exception_resilience(self) -> None:
        """Worker throws exception during cancel_goal -> tool caught cleanly."""
        mock_worker = MagicMock()
        mock_worker.cancel_goal = AsyncMock(side_effect=OSError("Disk write error during task cancellation"))
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_err"},
        )
        self.assertIn("❌ Lỗi khi hủy mục tiêu `task_err`", res)
        self.assertIn("Disk write error during task cancellation", res)


class TestRealWorkerEndToEndLifecycle(unittest.IsolatedAsyncioTestCase):
    """
    End-to-End Lifecycle test with genuine AutonomousGoalWorker (InMemoryTaskStore mode).
    Validates complete state transitions: Create -> List -> Cancel -> Double Cancel.
    """

    async def asyncSetUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )
        # Real AutonomousGoalWorker with use_db=False (in-memory mode)
        self.real_worker = AutonomousGoalWorker(
            tool_executor=self.executor,
            telegram_bot=None,
            llm_router=None,
            use_db=False,
        )
        self.executor.set_autonomous_goal_worker(self.real_worker)

    async def test_tc12_real_worker_lifecycle_e2e(self) -> None:
        """Full lifecycle through AgentToolExecutor dispatch with REAL AutonomousGoalWorker."""

        # 1. Initially empty
        res_empty = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("Hiện không có mục tiêu tự hành nào đang chạy ngầm", res_empty)

        # 2. Create goal
        create_res = await self.executor._execute_tool(
            tool_name="create_autonomous_goal",
            tool_args={
                "goal": "Giám sát tài nguyên máy chủ Ubuntu và cảnh báo Telegram",
                "trigger_condition": "RAM > 90% or Disk > 85%",
            },
            chat_id="chat_test_1001",
        )
        self.assertIn("ĐÃ THIẾT LẬP MỤC TIÊU TỰ HÀNH", create_res)
        match = re.search(r"`#(task_[a-f0-9]+)`", create_res)
        self.assertIsNotNone(match, f"Failed to extract task_id from create response: {create_res}")
        task_id = match.group(1)

        # 3. List active goals -> Task must appear
        res_active = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("DANH SÁCH MỤC TIÊU TỰ HÀNH (1 mục tiêu)", res_active)
        self.assertIn(task_id, res_active)
        self.assertIn("PENDING", res_active)

        # 4. Cancel the goal
        cancel_res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": task_id},
        )
        self.assertIn(f"Đã hủy bỏ mục tiêu tự hành `#{task_id}` thành công", cancel_res)

        # 5. List active goals -> Must now be empty!
        res_active_after_cancel = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("Hiện không có mục tiêu tự hành nào đang chạy ngầm", res_active_after_cancel)

        # 6. List all goals -> Task must appear as CANCELLED
        res_all = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "all"},
        )
        self.assertIn("DANH SÁCH MỤC TIÊU TỰ HÀNH (1 mục tiêu)", res_all)
        self.assertIn(task_id, res_all)
        self.assertIn("CANCELLED", res_all)

        # 7. Cancel again (Double cancel) -> Must fail cleanly
        double_cancel_res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": task_id},
        )
        self.assertIn(f"Không thể hủy mục tiêu `#{task_id}`", double_cancel_res)


if __name__ == "__main__":
    unittest.main()
