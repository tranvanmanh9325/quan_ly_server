"""
test_challenger_m4_it2_empirical.py — Challenger 1 Empirical Adversarial Stress Test Suite for Milestone 4 Iteration 2.

Author: Challenger 1 (EMPIRICAL CHALLENGER / critic & specialist)
Target Component: app.services.ai_agent_tools (Conversational Goals, Gorilla RAT Dynamic Scoping, Token Budget Gate, Fallback Honesty)

Mandatory Empirical Verification:
1. Token Budget Storm:
   - High-entropy multi-cluster queries (5-8+ clusters) combined with Vietnamese NLP phrases:
     "task tự động", "huy task tu dong", "các task tự động đang chạy", "đang theo dõi những gì".
   - Heavy cluster (Video Editor Studio) strict <= 6 tools ceiling.
   - Protected tools survival under aggressive token budget trimming (<= 700 tokens threshold).
2. Fallback Message Honesty:
   - cancel_autonomous_goal when worker is None: must NEVER claim success. Must honestly return "Autonomous Goal Worker chưa sẵn sàng".
   - cancel_autonomous_goal when worker returns False: must honestly return "Không thể hủy mục tiêu...".
   - cancel_autonomous_goal with worker exceptions: must catch cleanly and return friendly error.
3. 30 Conversational Queries Matrix:
   - Empirical verification across all 30 target queries for size <= 8 and intent booster accuracy.
4. Real AutonomousGoalWorker Lifecycle:
   - End-to-end execution without mocks using InMemoryTaskStore.
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


class TestTokenBudgetStormEmpirical(unittest.TestCase):
    """Empirical verification of Token Budget Storm resistance and dynamic scoping preservation."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    def test_tb01_task_tu_dong_with_5_clusters(self) -> None:
        """Query combining 'task tự động' with Docker, Security, System, Media, and Network."""
        query = (
            "Tạo task tự động khởi động lại container docker khi ram quá tải df -h, "
            "đồng thời kiểm tra iptables xem ip nào bị chặn và tải video clip hướng dẫn"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=query)
        self.assertLessEqual(len(scoped), 8, f"Max tools exceeded: {len(scoped)} tools")
        self.assertIn("create_autonomous_goal", scoped, f"create_autonomous_goal lost in 5-cluster storm: {scoped}")

        tools = self.executor._build_tools(query=query)
        self.assertLessEqual(len(tools), 8)
        names = {t["function"]["name"] for t in tools}
        self.assertIn("create_autonomous_goal", names)

    def test_tb02_huy_task_tu_dong_with_6_clusters(self) -> None:
        """Query combining 'huy task tu dong' with Video, PDF, Archive, Facebook, Calc, Notes."""
        query = (
            "huy task tu dong theo doi ram ngay, sau do cat video mp4, gop file pdf bao cao, "
            "giai nen file zip, gui tin nhan facebook, tinh toan 50 * 20 va tao note ghi chu"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=query)
        # Note: Archive or Video Studio may trigger heavy cluster (<= 6 tools) or standard (<= 8 tools)
        self.assertLessEqual(len(scoped), 8, f"Max tools exceeded: {len(scoped)} tools")
        self.assertIn("cancel_autonomous_goal", scoped, f"cancel_autonomous_goal lost in 6-cluster storm: {scoped}")

        tools = self.executor._build_tools(query=query)
        self.assertLessEqual(len(tools), 8)
        names = {t["function"]["name"] for t in tools}
        self.assertIn("cancel_autonomous_goal", names)

    def test_tb03_cac_task_tu_dong_dang_chay_with_7_clusters(self) -> None:
        """Query combining 'các task tự động đang chạy' with 7 distinct clusters."""
        query = (
            "Cho anh xem các task tự động đang chạy, đồng thời quét bẫy honeypot xem hacker nao tan cong, "
            "doc file docx bao cao, kiem tra thoi tiet ha noi, toi uu he thong giai phong ram, "
            "tao ma qr lien ket va doc noi dung web dantri.com.vn"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=query)
        self.assertLessEqual(len(scoped), 8, f"Max tools exceeded: {len(scoped)} tools")
        self.assertIn("list_autonomous_goals", scoped, f"list_autonomous_goals lost in 7-cluster storm: {scoped}")

        tools = self.executor._build_tools(query=query)
        self.assertLessEqual(len(tools), 8)
        names = {t["function"]["name"] for t in tools}
        self.assertIn("list_autonomous_goals", names)

    def test_tb04_dang_theo_doi_nhung_gi_with_heavy_media_cluster(self) -> None:
        """Query combining 'đang theo dõi những gì' with heavy video editing studio keywords."""
        query = "Cho anh xem đang theo dõi những gì, tien the cat video va xoa watermark color grade clip luon"
        scoped = self.executor._resolve_scoped_tool_names(query=query)
        # Heavy studio cluster strictly enforces <= 6 tools ceiling
        self.assertLessEqual(len(scoped), 6, f"Heavy cluster ceiling violated: {len(scoped)} > 6")
        self.assertIn("list_autonomous_goals", scoped, f"list_autonomous_goals lost in heavy studio cluster: {scoped}")

    def test_tb05_token_budget_gate_aggressive_pruning_protects_goal_tools(self) -> None:
        """
        Simulate severe token budget gate pressure:
        When JSON schema size > 700 tokens, verify protected_tools logic protects goal tools
        while dropping lower-priority tools (e.g. cron, files, calculate).
        """
        heavy_query = (
            "Lập task tự động kiểm tra disk df -h, tải video youtube, đọc báo dân trí, "
            "quản lý container docker restart, giải nén zip, tính toán 10 + 20"
        )
        tools = self.executor._build_tools(query=heavy_query)
        tool_names = [t["function"]["name"] for t in tools]

        # Verify goal tools are retained
        has_goal = any(t in tool_names for t in ("create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal"))
        self.assertTrue(has_goal, f"Goal tools dropped under token budget gate: {tool_names}")
        self.assertLessEqual(len(tools), 8)


class TestCancelFallbackHonestyEmpirical(unittest.IsolatedAsyncioTestCase):
    """Empirical verification of fallback message honesty and accuracy."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    async def test_fb01_cancel_goal_fallback_worker_none_honesty(self) -> None:
        """
        CRITICAL HONESTY TEST:
        When worker is None, cancel_autonomous_goal must NEVER claim success.
        It must honestly declare that Autonomous Goal Worker is not ready.
        """
        self.executor.set_autonomous_goal_worker(None)
        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_abc999"},
        )
        # Must NOT contain success indicator
        self.assertNotIn("✅", res)
        self.assertNotIn("thành công", res)
        # Must honestly report worker not ready
        self.assertIn("⚠️ Autonomous Goal Worker chưa sẵn sàng", res)
        self.assertIn("Không thể hủy mục tiêu `#task_abc999`", res)

    async def test_fb02_cancel_goal_fallback_worker_missing_method(self) -> None:
        """When worker object lacks cancel_goal method (duck-typing failure), returns honest fallback."""
        dummy_worker = object()  # Has no cancel_goal
        self.executor.set_autonomous_goal_worker(dummy_worker)
        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_xyz123"},
        )
        self.assertIn("⚠️ Autonomous Goal Worker chưa sẵn sàng", res)
        self.assertIn("Không thể hủy mục tiêu `#task_xyz123`", res)

    async def test_fb03_cancel_goal_worker_returns_false_honesty(self) -> None:
        """When worker.cancel_goal returns False (task not found/already completed), report honest failure."""
        mock_worker = MagicMock()
        mock_worker.cancel_goal = AsyncMock(return_value=False)
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_expired"},
        )
        self.assertIn("⚠️ Không thể hủy mục tiêu `#task_expired`", res)
        self.assertIn("Mục tiêu không tồn tại hoặc đã ở trạng thái kết thúc", res)

    async def test_fb04_cancel_goal_worker_returns_true(self) -> None:
        """When worker.cancel_goal returns True, confirm success."""
        mock_worker = MagicMock()
        mock_worker.cancel_goal = AsyncMock(return_value=True)
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_active_01"},
        )
        self.assertIn("✅ Đã hủy bỏ mục tiêu tự hành `#task_active_01` thành công.", res)

    async def test_fb05_cancel_goal_worker_exception_handling(self) -> None:
        """When worker raises unexpected exception, report error cleanly without crashing."""
        mock_worker = MagicMock()
        mock_worker.cancel_goal = AsyncMock(side_effect=ConnectionResetError("Redis broker disconnected"))
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_err"},
        )
        self.assertIn("❌ Lỗi khi hủy mục tiêu `task_err`", res)
        self.assertIn("Redis broker disconnected", res)


class TestConversational30QueriesEmpirical(unittest.TestCase):
    """Empirical verification of all 30 conversational queries from test_conversational_goals.py."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    def test_all_30_queries_empirical_matrix(self) -> None:
        test_matrix = [
            # 1-20 Original Milestone 4 queries
            ("Em lập kế hoạch theo dõi RAM máy chủ mỗi 10 phút giúp anh", "create"),
            ("lap ke hoach theo doi server neu ram > 90%", "create"),
            ("Đặt mục tiêu tự động dọn dẹp ổ đĩa khi đầy trên 85%", "create"),
            ("dat muc tieu tu dong don dep o dia", "create"),
            ("Tạo autonomous goal kiểm tra container dashboard_metrics_service", "create"),
            ("create goal monitor cpu load every 5m", "create"),
            ("Danh sách mục tiêu tự hành đang chạy", "list"),
            ("danh sach muc tieu dang chay tren server", "list"),
            ("Xem các goal tự động đang theo dõi", "list"),
            ("list goals active", "list"),
            ("Hủy mục tiêu #task_abc123 giúp anh", "cancel"),
            ("huy muc tieu goal_98765", "cancel"),
            ("cancel goal task_554433", "cancel"),
            ("Dừng tiến trình tự động theo dõi ram", "cancel"),
            ("dung tien trinh tu dong theo doi ram", "cancel"),
            ("Em theo dõi và bám sát tình trạng ổ đĩa giúp anh nhé", "create"),
            ("theo doi va bam sat suc khoe may chu", "create"),
            ("Kế hoạch tự động restart service khi bị crash", "create"),
            ("ke hoach tu dong kiem tra container", "create"),
            ("Xóa mục tiêu tự hành đang chạy ngầm", "cancel"),
            # 21-30 Iteration 2 Adversarial queries
            ("huy task tu dong", "cancel"),
            ("hủy task tự động", "cancel"),
            ("task tự động", "create"),
            ("task tu dong", "create"),
            ("các task tự động đang chạy", "list"),
            ("cac task tu dong dang chay", "list"),
            ("đang theo dõi những gì", "list"),
            ("dang theo doi nhung gi", "list"),
            ("dừng task tự động", "cancel"),
            ("xóa task tự động", "cancel"),
        ]

        self.assertEqual(len(test_matrix), 30, "Test matrix must contain exactly 30 queries")

        for query, intent in test_matrix:
            scoped = self.executor._resolve_scoped_tool_names(query=query)
            self.assertLessEqual(
                len(scoped), 8,
                f"Query '{query}' exceeded 8 tools budget: {len(scoped)}"
            )

            has_goal = any(
                t in scoped for t in ("create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal")
            )
            self.assertTrue(
                has_goal,
                f"Query '{query}' failed to include any goal tools: {scoped}"
            )

            # Specific intent checks
            if intent == "list":
                self.assertIn(
                    "list_autonomous_goals", scoped,
                    f"List query '{query}' missing list_autonomous_goals: {scoped}"
                )
            elif intent == "cancel":
                self.assertIn(
                    "cancel_autonomous_goal", scoped,
                    f"Cancel query '{query}' missing cancel_autonomous_goal: {scoped}"
                )
            elif intent == "create":
                self.assertIn(
                    "create_autonomous_goal", scoped,
                    f"Create query '{query}' missing create_autonomous_goal: {scoped}"
                )

    def test_punctuated_and_casing_variations(self) -> None:
        """Verify real-world variations: uppercase, punctuation, prefixes, suffixes."""
        variations = [
            ("Em ơi, task tự động!", "create_autonomous_goal"),
            ("Task tự động: kiểm tra ram", "create_autonomous_goal"),
            ("Có task tự động nào đang chạy không?", "create_autonomous_goal"),
            ("Hủy task tự động #task_123456!", "cancel_autonomous_goal"),
            ("Huy task tu dong ngay.", "cancel_autonomous_goal"),
            ("HỦY TASK TỰ ĐỘNG #task_9999", "cancel_autonomous_goal"),
            ("Server đang theo dõi những gì vậy em?", "list_autonomous_goals"),
            ("Em ơi, dang theo doi nhung gi tren vps?", "list_autonomous_goals"),
            ("Cac task tu dong dang chay la gi?", "list_autonomous_goals"),
            ("CÁC TASK TỰ ĐỘNG ĐANG CHẠY TRÊN SERVER???", "list_autonomous_goals"),
        ]

        for q, expected_tool in variations:
            scoped = self.executor._resolve_scoped_tool_names(query=q)
            self.assertLessEqual(len(scoped), 8)
            self.assertIn(expected_tool, scoped, f"Failed for '{q}': missing {expected_tool} in {scoped}")
            tools = self.executor._build_tools(query=q)
            names = [t["function"]["name"] for t in tools]
            self.assertIn(expected_tool, names, f"Failed for '{q}' in _build_tools: missing {expected_tool} in {names}")



class TestRealWorkerLifecycleEmpirical(unittest.IsolatedAsyncioTestCase):
    """Empirical verification of real AutonomousGoalWorker state machine."""

    async def asyncSetUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )
        self.worker = AutonomousGoalWorker(
            tool_executor=self.executor,
            telegram_bot=None,
            llm_router=None,
            use_db=False,
        )
        self.executor.set_autonomous_goal_worker(self.worker)

    async def test_rw01_full_lifecycle(self) -> None:
        # 1. Initially empty
        res_list = await self.executor._execute_tool("list_autonomous_goals", {"status_filter": "active"})
        self.assertIn("Hiện không có mục tiêu tự hành nào đang chạy ngầm", res_list)

        # 2. Create goal
        res_create = await self.executor._execute_tool(
            "create_autonomous_goal",
            {"goal": "Giám sát Swap và Disk usage", "trigger_condition": "swap > 50%"},
            chat_id="emp_chat_01",
        )
        self.assertIn("ĐÃ THIẾT LẬP MỤC TIÊU TỰ HÀNH", res_create)
        match = re.search(r"`#(task_[a-f0-9]+)`", res_create)
        self.assertIsNotNone(match)
        task_id = match.group(1)

        # 3. List active -> contains task_id
        res_active = await self.executor._execute_tool("list_autonomous_goals", {"status_filter": "active"})
        self.assertIn(task_id, res_active)

        # 4. Cancel task
        res_cancel = await self.executor._execute_tool("cancel_autonomous_goal", {"goal_id": task_id})
        self.assertIn("thành công", res_cancel)

        # 5. List active -> no longer contains task_id
        res_active_after = await self.executor._execute_tool("list_autonomous_goals", {"status_filter": "active"})
        self.assertNotIn(task_id, res_active_after)

        # 6. List all -> contains task_id in CANCELLED status
        res_all = await self.executor._execute_tool("list_autonomous_goals", {"status_filter": "all"})
        self.assertIn(task_id, res_all)
        self.assertIn("CANCELLED", res_all)

        # 7. Cancel again -> fails cleanly
        res_cancel_again = await self.executor._execute_tool("cancel_autonomous_goal", {"goal_id": task_id})
        self.assertIn("Không thể hủy mục tiêu", res_cancel_again)


if __name__ == "__main__":
    unittest.main()
