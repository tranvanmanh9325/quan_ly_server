"""
Comprehensive Unit & Integration Test Suite for Milestone 4: Conversational Goal Management (R4).

Verifies:
1. Registration and schema integrity of 3 goal tools in _build_tools().
2. Action Risk Tri-Tier classification: Tier 1 (list) and Tier 2 (create, cancel).
3. NLP Dynamic Scoping (Gorilla RAT): 15+ Vietnamese / English / unaccented queries,
   ensuring goal tools cluster selection and strict token budget gate (<= 8 tools).
4. Tool dispatch and execution:
   - create_autonomous_goal with worker and fallback
   - list_autonomous_goals with worker filtering (active, all) and fallback
   - cancel_autonomous_goal with success, failure, and fallback
5. Dependency Injection: set_autonomous_goal_worker on AgentToolExecutor and AIAgent.
6. System Prompt integrity: Section 2u Autonomous Goal Management Protocol and Constitutional Rule 9.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    classify_action_risk,
)
from app.services.ai_agent import AIAgent


class TestConversationalGoals(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )

    def test_01_build_tools_has_3_goal_tools(self) -> None:
        """Kiểm tra 3 tools quản trị mục tiêu tự hành được đăng ký đầy đủ trong _build_tools(force_all=True)."""
        tools = self.executor._build_tools(force_all=True)
        tool_names = {t["function"]["name"] for t in tools if "function" in t}

        self.assertIn("create_autonomous_goal", tool_names)
        self.assertIn("list_autonomous_goals", tool_names)
        self.assertIn("cancel_autonomous_goal", tool_names)

        # Kiểm tra chi tiết schema của từng tool
        tool_map = {t["function"]["name"]: t["function"] for t in tools if "function" in t}

        # 1. create_autonomous_goal
        create_fn = tool_map["create_autonomous_goal"]
        self.assertIn("goal", create_fn["parameters"]["properties"])
        self.assertIn("trigger_condition", create_fn["parameters"]["properties"])
        self.assertEqual(create_fn["parameters"]["required"], ["goal"])

        # 2. list_autonomous_goals
        list_fn = tool_map["list_autonomous_goals"]
        self.assertIn("status_filter", list_fn["parameters"]["properties"])
        self.assertIn("enum", list_fn["parameters"]["properties"]["status_filter"])

        # 3. cancel_autonomous_goal
        cancel_fn = tool_map["cancel_autonomous_goal"]
        self.assertIn("goal_id", cancel_fn["parameters"]["properties"])
        self.assertEqual(cancel_fn["parameters"]["required"], ["goal_id"])

    def test_02_classify_action_risk_tiers(self) -> None:
        """Xác nhận chuẩn phân loại Action Risk Tri-Tier: Tier 1 cho list, Tier 2 cho create và cancel."""
        # Tier 1 Safe Read-only
        self.assertEqual(
            classify_action_risk("list_autonomous_goals", {}),
            ACTION_TIER_1_SAFE,
        )
        self.assertEqual(
            classify_action_risk("list_autonomous_goals", {"status_filter": "active"}),
            ACTION_TIER_1_SAFE,
        )

        # Tier 2 Reversible
        self.assertEqual(
            classify_action_risk("create_autonomous_goal", {"goal": "Theo dõi RAM máy chủ"}),
            ACTION_TIER_2_REVERSIBLE,
        )
        self.assertEqual(
            classify_action_risk("cancel_autonomous_goal", {"goal_id": "goal_12345"}),
            ACTION_TIER_2_REVERSIBLE,
        )

    def test_03_dynamic_scoping_goal_queries_and_token_budget(self) -> None:
        """
        Thử nghiệm 20 câu query tiếng Việt (có dấu, không dấu, viết tắt, tiếng Anh)
        đảm bảo Gorilla RAT chọn đúng cụm công cụ mục tiêu và luôn giữ tổng số tools <= 8.
        """
        test_queries = [
            "Em lập kế hoạch theo dõi RAM máy chủ mỗi 10 phút giúp anh",
            "lap ke hoach theo doi server neu ram > 90%",
            "Đặt mục tiêu tự động dọn dẹp ổ đĩa khi đầy trên 85%",
            "dat muc tieu tu dong don dep o dia",
            "Tạo autonomous goal kiểm tra container dashboard_metrics_service",
            "create goal monitor cpu load every 5m",
            "Danh sách mục tiêu tự hành đang chạy",
            "danh sach muc tieu dang chay tren server",
            "Xem các goal tự động đang theo dõi",
            "list goals active",
            "Hủy mục tiêu #task_abc123 giúp anh",
            "huy muc tieu goal_98765",
            "cancel goal task_554433",
            "Dừng tiến trình tự động theo dõi ram",
            "dung tien trinh tu dong theo doi ram",
            "Em theo dõi và bám sát tình trạng ổ đĩa giúp anh nhé",
            "theo doi va bam sat suc khoe may chu",
            "Kế hoạch tự động restart service khi bị crash",
            "ke hoach tu dong kiem tra container",
            "Xóa mục tiêu tự hành đang chạy ngầm",
            "huy task tu dong",
            "hủy task tự động",
            "task tự động",
            "task tu dong",
            "các task tự động đang chạy",
            "cac task tu dong dang chay",
            "đang theo dõi những gì",
            "dang theo doi nhung gi",
            "dừng task tự động",
            "xóa task tự động",
        ]

        for q in test_queries:
            scoped = self.executor._resolve_scoped_tool_names(query=q)
            self.assertLessEqual(
                len(scoped),
                8,
                f"Token budget violated for query '{q}': {len(scoped)} tools returned",
            )
            # Phải chứa ít nhất 1 trong các goal tools
            has_goal_tool = any(
                t in scoped
                for t in ("create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal")
            )
            self.assertTrue(
                has_goal_tool,
                f"Dynamic scoping failed to include any goal tools for query: '{q}'. Scoped: {scoped}",
            )

    def test_04_dynamic_scoping_heavy_cluster_coexistence(self) -> None:
        """
        Kiểm tra khi câu lệnh kết hợp cả mục tiêu tự hành và thao tác hệ thống/đa phương tiện,
        hệ thống vẫn giữ được goal tools và tôn trọng trần <= 8 tools.
        """
        combined_query = "Lập kế hoạch dọn dẹp ổ đĩa df -h và kiểm tra sức khỏe server get_system_health_report"
        scoped = self.executor._resolve_scoped_tool_names(query=combined_query)
        self.assertLessEqual(len(scoped), 8)
        self.assertIn("create_autonomous_goal", scoped)

        # Kiểm tra qua _build_tools với token budget gate
        tools = self.executor._build_tools(query=combined_query)
        self.assertLessEqual(len(tools), 8)
        names = {t["function"]["name"] for t in tools}
        self.assertIn("create_autonomous_goal", names)

    async def test_05_execute_create_goal_with_worker(self) -> None:
        """Kiểm tra thực thi create_autonomous_goal chuyển giao thành công cho AutonomousGoalWorker."""
        mock_worker = MagicMock()
        mock_worker.create_goal = AsyncMock(return_value="task_123456789abc")
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="create_autonomous_goal",
            tool_args={"goal": "Theo dõi RAM mỗi 10 phút", "trigger_condition": "every 10m"},
            chat_id="tg_12345",
        )

        mock_worker.create_goal.assert_awaited_once_with(
            goal="Theo dõi RAM mỗi 10 phút",
            trigger_condition="every 10m",
            chat_id="tg_12345",
        )
        self.assertIn("#task_123456789abc", res)
        self.assertIn("Theo dõi RAM mỗi 10 phút", res)
        self.assertIn("every 10m", res)

    async def test_06_execute_create_goal_fallback_when_worker_none(self) -> None:
        """Kiểm tra fallback mượt mà khi worker chưa khởi tạo (offline/standalone mode)."""
        self.executor.set_autonomous_goal_worker(None)
        with unittest.mock.patch.object(self.executor, "_autonomous_goal_worker", None):
            res = await self.executor._execute_tool(
                tool_name="create_autonomous_goal",
                tool_args={"goal": "Kiểm tra swap tự động"},
                chat_id="tg_999",
            )
            self.assertIn("ĐÃ THIẾT LẬP MỤC TIÊU TỰ HÀNH", res)
            self.assertIn("Kiểm tra swap tự động", res)

    async def test_07_execute_list_goals_with_worker(self) -> None:
        """Kiểm tra list_autonomous_goals định dạng danh sách chuẩn xác từ worker."""
        mock_worker = MagicMock()
        mock_worker.list_goals = AsyncMock(
            return_value=[
                {
                    "id": "task_ram_01",
                    "goal": "Theo dõi RAM và dọn dẹp",
                    "status": "pending",
                    "current_step": 1,
                    "steps": [{"step_id": 1}, {"step_id": 2}],
                    "trigger_condition": "ram > 85%",
                },
                {
                    "id": "task_disk_02",
                    "goal": "Dọn rác Docker hàng tuần",
                    "status": "running",
                    "current_step": 2,
                    "steps": [{"step_id": 1}, {"step_id": 2}],
                    "trigger_condition": "weekly",
                },
            ]
        )
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )

        mock_worker.list_goals.assert_awaited_once()
        self.assertIn("DANH SÁCH MỤC TIÊU TỰ HÀNH", res)
        self.assertIn("task_ram_01", res)
        self.assertIn("task_disk_02", res)
        self.assertIn("Bước 1/2", res)

    async def test_08_execute_list_goals_empty(self) -> None:
        """Kiểm tra thông báo khi không có mục tiêu nào hoạt động."""
        mock_worker = MagicMock()
        mock_worker.list_goals = AsyncMock(return_value=[])
        self.executor.set_autonomous_goal_worker(mock_worker)

        res = await self.executor._execute_tool(
            tool_name="list_autonomous_goals",
            tool_args={"status_filter": "active"},
        )
        self.assertIn("Hiện không có mục tiêu tự hành nào đang chạy ngầm", res)

    async def test_09_execute_cancel_goal(self) -> None:
        """Kiểm tra cancel_autonomous_goal cả trường hợp thành công và thất bại."""
        mock_worker = MagicMock()
        # Thành công
        mock_worker.cancel_goal = AsyncMock(return_value=True)
        self.executor.set_autonomous_goal_worker(mock_worker)

        res_ok = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_ram_01"},
        )
        mock_worker.cancel_goal.assert_awaited_with(goal_id="task_ram_01")
        self.assertIn("Đã hủy bỏ mục tiêu tự hành `#task_ram_01` thành công", res_ok)

        # Thất bại (không tìm thấy hoặc đã kết thúc)
        mock_worker.cancel_goal = AsyncMock(return_value=False)
        res_fail = await self.executor._execute_tool(
            tool_name="cancel_autonomous_goal",
            tool_args={"goal_id": "task_non_existent"},
        )
        self.assertIn("Không thể hủy mục tiêu `#task_non_existent`", res_fail)

        # Fallback khi worker là None (M4 It2 fix: không báo thành công sai lệch)
        self.executor.set_autonomous_goal_worker(None)
        with unittest.mock.patch.object(self.executor, "_autonomous_goal_worker", None):
            res_no_worker = await self.executor._execute_tool(
                tool_name="cancel_autonomous_goal",
                tool_args={"goal_id": "task_no_worker"},
            )
            self.assertIn("Autonomous Goal Worker chưa sẵn sàng", res_no_worker)
            self.assertIn("Không thể hủy mục tiêu `#task_no_worker`", res_no_worker)

    def test_10_ai_agent_set_autonomous_goal_worker_injection(self) -> None:
        """Kiểm tra setter trên AIAgent truyền sâu xuống AgentToolExecutor."""
        mock_ssh = MagicMock()
        mock_cache = MagicMock()
        mock_llm = MagicMock()
        mock_llm.has_active_providers = True

        agent = AIAgent(
            llm_router=mock_llm,
            ssh_client=mock_ssh,
            message_cache=mock_cache,
        )

        dummy_worker = MagicMock()
        agent.set_autonomous_goal_worker(dummy_worker)

        self.assertIs(agent.autonomous_goal_worker, dummy_worker)
        self.assertIs(agent.tools.autonomous_goal_worker, dummy_worker)

    def test_11_system_prompt_section_2u_and_tri_tier(self) -> None:
        """Kiểm tra Section 2u và Điều 9 Hiến pháp hành vi trong _STATIC_SYSTEM_PREFIX."""
        prefix = AIAgent._STATIC_SYSTEM_PREFIX

        # 1. Kiểm tra Section 2u tồn tại
        self.assertIn("━━━ 2u. GIAO THỨC QUẢN LÝ MỤC TIÊU TỰ HÀNH & KẾ HOẠCH DÀI HẠN", prefix)
        self.assertIn("create_autonomous_goal", prefix)
        self.assertIn("list_autonomous_goals", prefix)
        self.assertIn("cancel_autonomous_goal", prefix)
        self.assertIn("TOOL-FIRST IMPERATIVE", prefix)

        # 2. Kiểm tra Hiến pháp hành vi Điều 9
        self.assertIn("Quản lý mục tiêu tự hành: list_autonomous_goals", prefix)
        self.assertIn("Quản trị mục tiêu tự hành: create_autonomous_goal, cancel_autonomous_goal", prefix)


if __name__ == "__main__":
    unittest.main()
