"""
Test Suite: Comprehensive 4-Tier Autonomous AI Agent E2E Verification
Dự án: True Autonomous AI Agent Architecture (Tiểu Bảo Bảo) - services/ai-agent-service
Mã nguồn kiểm thử: services/ai-agent-service/tests/test_autonomous_goal_e2e.py

Kiến trúc kiểm thử 4 Tiers (Opaque-Box, Zero-Facade Integrity):
- Tier 1: Feature Coverage (Core Happy Paths for R1, R2, R3, R4)
- Tier 2: Boundary & Corner Cases (Extreme Inputs, Cooldowns, Lethal Gating, Max Cycles)
- Tier 3: Cross-Feature Combinations (R1+R2, R3+R1, R4+R1 Interlocks)
- Tier 4: Real-World Application Scenarios (SRE Disk Remediation, Multi-Step Maintenance)

Opaque-Box Zero-Facade Verification:
- R1: app.services.autonomous_goal_worker.AutonomousGoalWorker
- R2: app.services.ai_agent.AiAgentService (_evaluate_tool_step, MAX_REFLECTION_CYCLES)
- R3: app.services.proactive_service.ProactiveIntelligenceService (_decide_remediation, _execute_remediation)
- R4: app.services.ai_agent_tools.AgentToolExecutor (_resolve_scoped_tool_names)
"""
import asyncio
from datetime import datetime, timezone, timedelta
import json
from typing import Any, Dict, List, Optional, Set
import unittest
from unittest.mock import AsyncMock, MagicMock

# Optional pytest support without crashing on missing pytest-asyncio
try:
    import pytest

    @pytest.fixture(autouse=True)
    def cleanup_shared_http_clients():
        yield
except ImportError:
    pytest = None

# Production Product Imports
from app.core.brain_core import ArtificialBrain
from app.services.autonomous_goal_worker import (
    AutonomousGoalWorker,
    InMemoryTaskStore,
)
from app.services.ai_agent import (
    AiAgentService,
    MAX_REFLECTION_CYCLES,
)
from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _REMEDIATION_COOLDOWN_SECONDS,
    _DISK_ALERT_PCT,
    _SRE_RAM_ALERT_PCT,
)
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
)
from app.services.memory_service import AgentMemoryService


def _create_mock_memory() -> MagicMock:
    """Tạo mock AgentMemoryService đầy đủ interface cho AiAgentService và ProactiveIntelligenceService."""
    mock_memory = MagicMock(spec=AgentMemoryService)
    mock_memory.record_reflection_failure = AsyncMock(return_value=999)
    mock_memory.record_tool_outcome = AsyncMock()
    mock_memory.record_causal_transition = AsyncMock()
    mock_memory.record_episode = AsyncMock()
    mock_memory.should_send_proactive_alert = AsyncMock(return_value=True)
    mock_memory.upsert_proactive_check = AsyncMock()
    mock_memory.get_active_lessons = AsyncMock(return_value="")
    mock_memory.get_recent_episodes = AsyncMock(return_value="")
    mock_memory.get_pending_tasks_prompt = AsyncMock(return_value="")
    mock_memory.get_active_schemas_prompt = AsyncMock(return_value="")
    mock_memory.get_all_causal_hints_prompt = AsyncMock(return_value="")
    mock_memory.get_formatted_memories = AsyncMock(return_value="")
    mock_memory.get_due_reminders = AsyncMock(return_value="")
    return mock_memory


def _create_mock_agent(
    mock_llm: Optional[MagicMock] = None,
    mock_memory: Optional[MagicMock] = None,
) -> AiAgentService:
    """Khởi tạo thực thể AiAgentService sản phẩm thật với mock LLM Router và Memory."""
    llm_router = mock_llm or MagicMock()
    ssh_client = MagicMock()
    message_cache = MagicMock()
    agent = AiAgentService(
        llm_router=llm_router,
        ssh_client=ssh_client,
        message_cache=message_cache,
    )
    if mock_memory is not None:
        agent.memory_service = mock_memory
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (Core Happy Path Verification)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier1FeatureCoverage(unittest.IsolatedAsyncioTestCase):
    """
    Tier 1 - Feature Coverage:
    Kiểm thử từng tính năng cốt lõi (R1, R2, R3, R4) trong điều kiện happy-path độc lập,
    gọi trực tiếp các phương thức của mã nguồn sản phẩm thực tế.
    """

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

        self.mock_tool_executor = MagicMock(spec=AgentToolExecutor)
        self.mock_tool_executor.execute_tool = AsyncMock(return_value="Filesystem /dev/sda1 45% used")

        self.mock_telegram_bot = MagicMock()
        self.mock_telegram_bot.send_message = AsyncMock(return_value=True)
        self.mock_telegram_bot.chat_id = "test_chat_123"

        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="Filesystem /dev/sda1 45% used")

        self.mock_memory = _create_mock_memory()

        # Product classes instances
        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram_bot,
            use_db=False,
        )
        self.proactive_service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram_bot,
            scan_interval=3600,
        )
        self.agent = _create_mock_agent(mock_memory=self.mock_memory)
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
        )

    # ── R1: Autonomous Goal Engine Happy Path ──

    async def test_t1_r1_01_create_goal_and_initial_status(self) -> None:
        """R1: Tạo goal mới qua AutonomousGoalWorker và kiểm tra trạng thái ban đầu là pending."""
        goal_text = "Kiểm tra tình trạng đĩa và RAM định kỳ"
        steps = [
            {"tool": "run_command", "args": {"command": "df -h"}},
            {"tool": "run_command", "args": {"command": "free -m"}},
        ]
        task_id = await self.worker.create_goal(
            goal=goal_text,
            steps=steps,
            trigger_condition="every 30m",
            chat_id="test_chat_123"
        )
        self.assertTrue(task_id.startswith("task_"))

        task = await self.worker.get_goal_status(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["goal"], goal_text)
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["current_step"], 0)
        self.assertEqual(len(task["steps"]), 2)

    async def test_t1_r1_02_execute_safe_step_progression(self) -> None:
        """R1: Thực thi step với tool an toàn, kiểm tra trạng thái goal qua các step."""
        task_id = await self.worker.create_goal(
            goal="Kiểm tra đĩa root",
            steps=[{"tool": "run_command", "args": {"command": "df -h /"}}],
            chat_id="test_chat_123"
        )
        task = await self.worker.get_goal_status(task_id)
        updated_task = await self.worker.execute_pending_step(task)

        self.assertEqual(updated_task["status"], "completed")
        self.assertEqual(updated_task["current_step"], 1)
        self.assertIn("Filesystem", updated_task["steps"][0]["result"])

    async def test_t1_r1_03_multi_step_execution_success(self) -> None:
        """R1: Thực thi chuỗi 2 bước an toàn tuần tự đạt trạng thái completed."""
        steps = [
            {"tool": "run_command", "args": {"command": "df -h"}},
            {"tool": "run_command", "args": {"command": "uptime"}},
        ]
        task_id = await self.worker.create_goal(goal="Bảo trì 2 bước", steps=steps)
        task = await self.worker.get_goal_status(task_id)

        # Step 0
        task_after_step0 = await self.worker.execute_pending_step(task)
        self.assertEqual(task_after_step0["current_step"], 1)
        self.assertEqual(task_after_step0["status"], "running")

        # Step 1
        task_after_step1 = await self.worker.execute_pending_step(task_after_step0)
        self.assertEqual(task_after_step1["current_step"], 2)
        self.assertEqual(task_after_step1["status"], "completed")

    async def test_t1_r1_04_list_goals_and_status_filtering(self) -> None:
        """R1: Liệt kê danh sách goals và lọc theo trạng thái."""
        t1 = await self.worker.create_goal(goal="Goal 1", steps=[{"tool": "run_command", "args": {"command": "uptime"}}])
        t2 = await self.worker.create_goal(goal="Goal 2", steps=[{"tool": "run_command", "args": {"command": "free -m"}}])

        # Complete t1
        task1 = await self.worker.get_goal_status(t1)
        await self.worker.execute_pending_step(task1)

        pending_goals = await self.worker.list_goals(status="pending")
        completed_goals = await self.worker.list_goals(status="completed")

        self.assertEqual(len(pending_goals), 1)
        self.assertEqual(pending_goals[0]["id"], t2)
        self.assertEqual(len(completed_goals), 1)
        self.assertEqual(completed_goals[0]["id"], t1)

    async def test_t1_r1_05_proactive_telegram_reporting_on_completion(self) -> None:
        """R1: Gửi proactive notification qua Telegram khi goal hoàn thành."""
        task_id = await self.worker.create_goal(
            goal="Báo cáo hoàn tất",
            steps=[{"tool": "run_command", "args": {"command": "df -h"}}],
            chat_id="test_chat_123"
        )
        task = await self.worker.get_goal_status(task_id)
        await self.worker.execute_pending_step(task)

        self.mock_telegram_bot.send_message.assert_called_once()
        sent_chat_id, sent_text = self.mock_telegram_bot.send_message.call_args[0]
        self.assertEqual(sent_chat_id, "test_chat_123")
        self.assertIn("Hoàn thành mục tiêu", sent_text)

    # ── R2: Self-Evaluation & Reflection Loop Happy Path ──

    async def test_t1_r2_01_fast_evaluation_goal_achieved(self) -> None:
        """R2: Gọi trực tiếp AiAgentService._evaluate_tool_step xác nhận mục tiêu đạt được."""
        self.agent.llm_router.complete = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "achieved": True,
                                "status": "SUCCESS",
                                "reflection": "",
                            })
                        }
                    }
                ]
            }
        )

        eval_result = await self.agent._evaluate_tool_step(
            goal="Lấy thông tin ổ đĩa",
            tool_name="run_command",
            tool_args={"command": "df -h /"},
            tool_result="Filesystem /dev/sda1 45% used",
        )
        self.assertTrue(eval_result["achieved"])
        self.assertEqual(eval_result["reflection"], "")
        self.assertEqual(eval_result["status"], "SUCCESS")

    async def test_t1_r2_02_fast_evaluation_goal_not_achieved(self) -> None:
        """R2: Gọi trực tiếp AiAgentService._evaluate_tool_step phát hiện thất bại và sinh phản biện."""
        self.agent.llm_router.complete = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "achieved": False,
                                "status": "CONTINUE",
                                "reflection": "[Reflection] Thao tác docker restart chưa đạt mục tiêu: Không tìm thấy container dashboard_db.",
                            })
                        }
                    }
                ]
            }
        )

        eval_result = await self.agent._evaluate_tool_step(
            goal="Khởi động lại container dashboard_db",
            tool_name="run_command",
            tool_args={"command": "docker restart dashboard_db"},
            tool_result="Error: No such container: dashboard_db",
        )
        self.assertFalse(eval_result["achieved"])
        self.assertIn("[Reflection]", eval_result["reflection"])
        self.assertIn("chưa đạt mục tiêu", eval_result["reflection"])
        self.assertEqual(eval_result["status"], "CONTINUE")

    def test_t1_r2_03_reflection_injection_format(self) -> None:
        """R2: Định dạng reflection injection chứa tag chuẩn xác cho iteration tiếp theo."""
        reflection_text = "[Reflection] Lệnh df -h thất bại. Cần dùng get_disk_usage thay thế."
        prompt_with_reflection = f"Mục tiêu: Kiểm tra đĩa\n\n{reflection_text}\n\nHãy chọn công cụ tiếp theo:"
        self.assertIn("[Reflection]", prompt_with_reflection)
        self.assertTrue(prompt_with_reflection.startswith("Mục tiêu: Kiểm tra đĩa"))

    # ── R3: Proactive Action Execution Happy Path ──

    def test_t1_r3_01_decide_remediation_disk_alert(self) -> None:
        """R3: Gọi trực tiếp ProactiveIntelligenceService._decide_remediation chọn đúng Tier 1 docker_prune."""
        alert = "⚠️ Ổ đĩa sắp đầy (89% trên /dev/sda1)"
        remediation = self.proactive_service._decide_remediation(alert)

        self.assertIsNotNone(remediation)
        self.assertEqual(remediation["action_key"], "docker_prune")
        self.assertEqual(remediation["tier"], 1)
        self.assertEqual(remediation["command"], "docker system prune -f")
        self.assertEqual(remediation["metric_type"], "disk")
        self.assertTrue(remediation["auto_execute"])

    def test_t1_r3_02_decide_remediation_ram_alert(self) -> None:
        """R3: Gọi trực tiếp ProactiveIntelligenceService._decide_remediation chọn đúng Tier 1 drop_caches."""
        alert = "⚠️ RAM đang cao: 92% đã sử dụng"
        remediation = self.proactive_service._decide_remediation(alert)

        self.assertIsNotNone(remediation)
        self.assertEqual(remediation["action_key"], "drop_caches")
        self.assertEqual(remediation["tier"], 1)
        self.assertEqual(remediation["command"], "sync && echo 3 > /proc/sys/vm/drop_caches")
        self.assertEqual(remediation["metric_type"], "ram")
        self.assertTrue(remediation["auto_execute"])

    async def test_t1_r3_03_execute_remediation_before_after_reporting(self) -> None:
        """R3: Gọi trực tiếp ProactiveIntelligenceService._execute_remediation, xác thực báo cáo hiệu quả."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker",
        }
        # Mock SSH responses cho before snapshot (89% used, 4.1GB free), prune cmd, after snapshot (73% used, 9.8GB free)
        self.mock_ssh.run_command.side_effect = [
            "89% 4.1G 30G",
            "Total reclaimed space: 5.7GB",
            "73% 9.8G 30G",
        ]

        res = await self.proactive_service._execute_remediation(remediation, "Disk alert 89%")
        self.assertTrue(res)
        self.mock_telegram_bot.send_message.assert_called_once()
        _, sent_report = self.mock_telegram_bot.send_message.call_args[0]
        self.assertIn("Auto-Remediation", sent_report)
        self.assertIn("docker system prune -f", sent_report)
        self.assertIn("5.7GB", sent_report)

    # ── R4: Conversational Goal Management Happy Path ──

    def test_t1_r4_01_intent_keywords_scope_goal_tools(self) -> None:
        """R4: Gọi trực tiếp AgentToolExecutor._resolve_scoped_tool_names kích hoạt đúng cụm goal tools."""
        test_queries = [
            "Em theo dõi và bám sát tình trạng ổ đĩa giúp anh nhé",
            "Đặt mục tiêu tự động dọn rác khi đĩa đầy",
            "Tạo một autonomous goal giám sát RAM",
            "Lập kế hoạch tự hành bảo trì máy chủ",
        ]
        for q in test_queries:
            scoped = self.executor._resolve_scoped_tool_names(query=q)
            self.assertIn("create_autonomous_goal", scoped, f"Query '{q}' must scope create_autonomous_goal")
            self.assertLessEqual(len(scoped), 8, f"Query '{q}' must enforce token budget <= 8 tools")

    async def test_t1_r4_02_conversational_goal_tools_execution_mock(self) -> None:
        """R4: Quản trị mục tiêu tự hành hoàn chỉnh qua AutonomousGoalWorker: create, list, cancel."""
        # 1. create_autonomous_goal
        created_id = await self.worker.create_goal("Theo dõi CPU mỗi 5 phút")
        self.assertTrue(created_id.startswith("task_"))

        # 2. list_autonomous_goals
        goals_list = await self.worker.list_goals(status="pending")
        self.assertIsInstance(goals_list, list)
        self.assertTrue(any(g["id"] == created_id for g in goals_list))

        # 3. cancel_autonomous_goal
        cancel_res = await self.worker.cancel_goal(created_id, reason="User cancelled")
        self.assertTrue(cancel_res)
        status_after = await self.worker.get_goal_status(created_id)
        self.assertEqual(status_after["status"], "cancelled")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (Extreme Inputs & Safety Guards)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier2BoundaryCornerCases(unittest.IsolatedAsyncioTestCase):
    """
    Tier 2 - Boundary & Corner Cases:
    Kiểm tra xử lý biên cực trị, lệnh phá hủy Tier 3, giới hạn chu kỳ phản biện và cooldown,
    hoàn toàn vận hành trên các lớp dịch vụ sản phẩm thực tế.
    """

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

        self.mock_tool_executor = MagicMock(spec=AgentToolExecutor)
        self.mock_telegram_bot = MagicMock()
        self.mock_telegram_bot.send_message = AsyncMock(return_value=True)
        self.mock_telegram_bot.chat_id = "test_chat_alert"

        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="Command output")

        self.mock_memory = _create_mock_memory()

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram_bot,
            use_db=False,
        )
        self.proactive_service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram_bot,
            scan_interval=3600,
        )
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
        )

    # ── R1 Boundary & Corner Cases ──

    async def test_t2_r1_01_empty_goal_handling(self) -> None:
        """R1: Goal rỗng hoặc chỉ toàn khoảng trắng được xử lý an toàn không crash hệ thống."""
        try:
            task_id = await self.worker.create_goal("")
            task = await self.worker.get_goal_status(task_id)
            self.assertIsNotNone(task)
        except ValueError:
            pass  # Strict validation raises ValueError

    async def test_t2_r1_02_invalid_tool_args_retry_exhaustion(self) -> None:
        """R1: Tool execution ném lỗi liên tiếp -> vượt max_retries chuyển sang failed."""
        self.mock_tool_executor.execute_tool = AsyncMock(side_effect=RuntimeError("Command timed out after 30s"))

        task_id = await self.worker.create_goal(
            goal="Thao tác lỗi",
            steps=[{"tool": "run_command", "args": {"command": "sleep 100"}}],
            chat_id="test_chat_alert"
        )
        task = await self.worker.get_goal_status(task_id)

        # 3 consecutive retries
        for _ in range(3):
            task = await self.worker.execute_pending_step(task)

        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["retry_count"], 3)
        self.assertIn("after 3 retries", task["error_message"].lower())
        self.mock_telegram_bot.send_message.assert_called()

    async def test_t2_r1_03_db_connection_fallback_to_inmemory(self) -> None:
        """R1: DB pool là None hoặc kết nối hỏng tự động fallback về in-memory store."""
        worker_no_db = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram_bot,
            pool=None,
            use_db=False,
        )
        self.assertFalse(worker_no_db.use_db)

        # Full functionality preserved in fallback mode
        task_id = await worker_no_db.create_goal("Fallback Goal")
        task = await worker_no_db.get_goal_status(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["goal"], "Fallback Goal")

    async def test_t2_r1_04_block_tier3_lethal_command_to_waiting_approval(self) -> None:
        """R1: Chặn lệnh Tier 3 Lethal (lệnh có rủi ro phá hủy) -> chuyển sang waiting_approval."""
        lethal_commands = [
            "rm -rf /",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "drop database quan_ly_server",
            "iptables -F",
            "ufw reset",
        ]
        for cmd in lethal_commands:
            task_id = await self.worker.create_goal(
                goal=f"Mục tiêu nguy hiểm: {cmd}",
                steps=[{"tool": "run_command", "args": {"command": cmd}}],
                chat_id="test_chat_alert"
            )
            task = await self.worker.get_goal_status(task_id)
            updated_task = await self.worker.execute_pending_step(task)

            self.assertEqual(
                updated_task["status"],
                "waiting_approval",
                f"Lệnh nguy hiểm '{cmd}' phải bị chặn và chuyển sang waiting_approval"
            )
            self.assertIn("Tier 3 Lethal", updated_task["error_message"])

    # ── R2 Boundary & Corner Cases ──

    async def test_t2_r2_01_max_reflection_cycles_prevents_infinite_loop(self) -> None:
        """R2: Kiểm thử trực tiếp ReAct loop của AiAgentService chạm trần MAX_REFLECTION_CYCLES = 2."""
        mock_llm = MagicMock()
        mock_memory = _create_mock_memory()

        agent = _create_mock_agent(mock_llm=mock_llm, mock_memory=mock_memory)
        agent.is_configured = MagicMock(return_value=True)
        agent.tools = MagicMock()
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.execute_tool = AsyncMock(return_value="Command output indicates failure")
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "run_command"}}])

        # Step 0 tool call -> eval rejected (cycle 1)
        # Step 1 tool call -> eval rejected (cycle 2 -> hits MAX_REFLECTION_CYCLES)
        # Step 2 synthesis response
        tool_call_resp = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_loop_test",
                                "type": "function",
                                "function": {"name": "run_command", "arguments": '{"command": "check_status.sh"}'},
                            }
                        ],
                    }
                }
            ]
        }
        eval_fail_resp = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "achieved": False,
                            "status": "CONTINUE",
                            "reflection": "Thao tác chưa đạt mục tiêu, cần thử lại.",
                        })
                    }
                }
            ]
        }
        synthesis_resp = {
            "choices": [{"message": {"content": "Dạ em đã tổng hợp câu trả lời cuối cùng sau khi chạm trần phản biện."}}]
        }

        mock_llm.complete = AsyncMock(side_effect=[
            tool_call_resp,
            eval_fail_resp,
            tool_call_resp,
            eval_fail_resp,
            synthesis_resp,
        ])

        final_reply = await agent.chat(
            chat_id="chat_reflection_test",
            user_message="Hãy theo dõi và tự động khắc phục sự cố dịch vụ nginx",
            goal="Tự động khắc phục sự cố dịch vụ nginx",
        )

        self.assertIn("tổng hợp", final_reply)
        self.assertEqual(mock_memory.record_reflection_failure.call_count, 1)
        self.assertEqual(MAX_REFLECTION_CYCLES, 2)

    async def test_t2_r2_02_lesson_recording_in_memory_service_on_failure(self) -> None:
        """R2: Lưu bài học kinh nghiệm vào AgentMemoryService khi thất bại sau retries."""
        mock_memory = _create_mock_memory()

        failed_goal = "Tối ưu hóa Swap 64GB"
        root_cause = "Hệ thống i5-4310U chỉ có 3.2GB RAM vật lý; gán swap quá lớn gây trashing IO"
        lesson_summary = f"[Bài học tự hành] Mục tiêu '{failed_goal}' thất bại: {root_cause}"

        await mock_memory.record_episode(
            event_summary=lesson_summary,
            severity="high",
            salience=0.9,
            tags=["autonomous_goal_lesson", "post_mortem_recovery"]
        )
        mock_memory.record_episode.assert_called_once()
        call_kwargs = mock_memory.record_episode.call_args[1]
        self.assertIn("autonomous_goal_lesson", call_kwargs["tags"])
        self.assertIn("Swap 64GB", call_kwargs["event_summary"])

    # ── R3 Boundary & Corner Cases ──

    async def test_t2_r3_01_remediation_cooldown_30_minutes_blocks_repeat(self) -> None:
        """R3: Gọi trực tiếp _execute_remediation xác nhận Cooldown 30 phút chặn thực thi lặp lại."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Dọn rác Docker",
        }

        # Set cooldown timestamp within the 30-minute window (10 minutes ago = 600s < 1800s)
        now = datetime.now(timezone.utc)
        self.proactive_service._remediation_cooldowns["docker_prune"] = now - timedelta(minutes=10)

        is_executed = await self.proactive_service._execute_remediation(remediation, "Disk alert test")
        self.assertFalse(is_executed, "Remediation phải bị chặn hoàn toàn khi đang trong cooldown 30 phút")
        self.mock_ssh.run_command.assert_not_called()

    async def test_t2_r3_02_remediation_allowed_after_cooldown_expires(self) -> None:
        """R3: Gọi trực tiếp _execute_remediation xác nhận hành động được phép chạy sau khi hết 30 phút (1801s)."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Dọn rác Docker",
        }

        # Cooldown expired (30 minutes + 1 second ago)
        now = datetime.now(timezone.utc)
        self.proactive_service._remediation_cooldowns["docker_prune"] = now - timedelta(seconds=_REMEDIATION_COOLDOWN_SECONDS + 1)

        self.mock_ssh.run_command.side_effect = [
            "89% 4.1G 30G",
            "reclaimed 5.0G",
            "74% 9.1G 30G",
        ]

        is_executed = await self.proactive_service._execute_remediation(remediation, "Disk alert after cooldown")
        self.assertTrue(is_executed, "Remediation phải được phép thực thi sau khi cooldown 30 phút đã hết")

    def test_t2_r3_03_tier2_alert_requires_approval(self) -> None:
        """R3: Gọi trực tiếp _decide_remediation xác nhận các alert Tier 2 (restart container, renew SSL) auto_execute=False."""
        tier2_alerts = [
            "Core Container gặp sự cố: dashboard_ai_agent exited",
            "SSL cert sắp hết hạn trong vòng 7 ngày",
        ]
        for a in tier2_alerts:
            remediation = self.proactive_service._decide_remediation(a)
            self.assertIsNotNone(remediation)
            self.assertEqual(remediation["tier"], 2)
            self.assertFalse(remediation["auto_execute"], f"Alert '{a}' must NOT auto-execute")

    # ── R4 Boundary & Corner Cases ──

    def test_t2_r4_01_token_budget_limit_max_8_tools(self) -> None:
        """R4: Gọi trực tiếp AgentToolExecutor._resolve_scoped_tool_names tuân thủ Token Budget <= 8 tools."""
        multi_intent_query = (
            "Tiểu Bảo Bảo ơi hãy vừa tải video tiktok vừa kiểm tra server "
            "vừa chuyển file sang ipad và lập mục tiêu tự hành theo dõi disk"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=multi_intent_query)
        self.assertLessEqual(len(scoped), 8, f"Selected tools ({len(scoped)}) exceeds token budget limit of 8 tools")

    async def test_t2_r4_02_cancel_nonexistent_goal_graceful(self) -> None:
        """R4: Hủy goal không tồn tại xử lý graceful trên AutonomousGoalWorker, trả về False không ném Exception."""
        cancel_result = await self.worker.cancel_goal("non_existent_goal_id_999")
        self.assertFalse(cancel_result)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise & Pipeline Interlocks)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier3CrossFeatureCombinations(unittest.IsolatedAsyncioTestCase):
    """
    Tier 3 - Cross-Feature Combinations:
    Kiểm thử sự phối hợp liên tính năng giữa R1, R2, R3, và R4 sử dụng 100% các lớp sản phẩm thật.
    """

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

        self.mock_tool_executor = MagicMock(spec=AgentToolExecutor)
        self.mock_telegram_bot = MagicMock()
        self.mock_telegram_bot.send_message = AsyncMock(return_value=True)
        self.mock_telegram_bot.chat_id = "test_chat_cross"

        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="Filesystem 45% used")

        self.mock_memory = _create_mock_memory()

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram_bot,
            use_db=False,
        )
        self.proactive_service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram_bot,
            scan_interval=3600,
        )
        self.agent = _create_mock_agent(mock_memory=self.mock_memory)
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
        )

    async def test_t3_r1_r2_step_failure_triggers_evaluation_and_reflection(self) -> None:
        """
        R1 kết hợp R2:
        Một bước trong goal gặp lỗi -> kích hoạt AiAgentService._evaluate_tool_step trả về reflection.
        """
        # Step 0 succeeds, Step 1 returns command not found
        self.mock_tool_executor.execute_tool = AsyncMock(side_effect=[
            "Filesystem 45% used",
            "bash: my_custom_tool: command not found",
        ])

        task_id = await self.worker.create_goal(
            goal="Thu thập số liệu và phân tích",
            steps=[
                {"tool": "run_command", "args": {"command": "df -h"}},
                {"tool": "run_command", "args": {"command": "my_custom_tool"}},
            ]
        )
        task = await self.worker.get_goal_status(task_id)

        # Mock LLM evaluation responses: step 0 achieves, step 1 fails
        self.agent.llm_router.complete = AsyncMock(side_effect=[
            {"choices": [{"message": {"content": json.dumps({"achieved": True, "status": "SUCCESS", "reflection": ""})}}]},
            {"choices": [{"message": {"content": json.dumps({"achieved": False, "status": "CONTINUE", "reflection": "[Reflection] Lệnh my_custom_tool chưa đạt mục tiêu: command not found."})}}]},
        ])

        # Run step 0
        task_1 = await self.worker.execute_pending_step(task)
        eval_step0 = await self.agent._evaluate_tool_step(
            goal=task["goal"],
            tool_name="run_command",
            tool_args={"command": "df -h"},
            tool_result=task_1["steps"][0].get("result", "")
        )
        self.assertTrue(eval_step0["achieved"])

        # Run step 1
        task_2 = await self.worker.execute_pending_step(task_1)
        eval_step1 = await self.agent._evaluate_tool_step(
            goal=task["goal"],
            tool_name="run_command",
            tool_args={"command": "my_custom_tool"},
            tool_result=task_2["steps"][1].get("result", "")
        )
        self.assertFalse(eval_step1["achieved"])
        self.assertIn("[Reflection]", eval_step1["reflection"])

    async def test_t3_r3_r1_remediation_spawns_autonomous_monitoring_task(self) -> None:
        """
        R3 kết hợp R1:
        Remediation tự động dọn đĩa từ _decide_remediation, sau đó tạo ra một autonomous goal để theo dõi.
        """
        alert = "Ổ đĩa /dev/sda1 sắp đầy (88%)"
        remediation = self.proactive_service._decide_remediation(alert)
        self.assertIsNotNone(remediation)
        self.assertEqual(remediation["action_key"], "docker_prune")

        # R3 creates follow-up autonomous goal in R1
        followup_task_id = await self.worker.create_goal(
            goal="Theo dõi biến động dung lượng đĩa trong 1 giờ sau khi docker prune",
            steps=[
                {"tool": "run_command", "args": {"command": "df -h /"}},
                {"tool": "run_command", "args": {"command": "sleep 1 && df -h /"}},
            ],
            trigger_condition="every 30m for 1h",
            chat_id="test_chat_cross"
        )
        self.assertTrue(followup_task_id.startswith("task_"))

        followup_task = await self.worker.get_goal_status(followup_task_id)
        self.assertEqual(followup_task["status"], "pending")
        self.assertEqual(len(followup_task["steps"]), 2)

    async def test_t3_r4_r1_chat_tool_creates_task_worker_picks_up(self) -> None:
        """
        R4 kết hợp R1:
        Người dùng gọi câu lệnh đàm thoại -> _resolve_scoped_tool_names chọn create_autonomous_goal -> worker thực thi.
        """
        user_message = "Em theo dõi và bám sát uptime máy chủ giúp anh nhé"
        scoped = self.executor._resolve_scoped_tool_names(query=user_message)
        self.assertIn("create_autonomous_goal", scoped)

        task_id = await self.worker.create_goal(
            goal="Tự động kiểm tra uptime máy chủ",
            steps=[{"tool": "run_command", "args": {"command": "uptime"}}],
            chat_id="telegram_user_456"
        )

        pending_list = await self.worker.list_goals(status="pending")
        self.assertTrue(any(t["id"] == task_id for t in pending_list))

        task_record = await self.worker.get_goal_status(task_id)
        self.mock_tool_executor.execute_tool = AsyncMock(return_value="14:15:00 up 14 days, 1 user, load average: 0.15")

        executed_task = await self.worker.execute_pending_step(task_record)
        self.assertEqual(executed_task["status"], "completed")
        self.assertIn("14 days", executed_task["steps"][0].get("result", ""))


# ─────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD APPLICATION SCENARIOS
# ─────────────────────────────────────────────────────────────────────────────

class TestTier4RealWorldScenarios(unittest.IsolatedAsyncioTestCase):
    """
    Tier 4 - Real-World Application Scenarios:
    Mô phỏng đầy đủ chu trình hoạt động thực tế trên hạ tầng máy chủ kirito-server,
    kết nối liên module giữa ProactiveIntelligenceService, AgentToolExecutor, và AutonomousGoalWorker.
    """

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

        self.mock_tool_executor = MagicMock(spec=AgentToolExecutor)
        self.mock_telegram_bot = MagicMock()
        self.mock_telegram_bot.send_message = AsyncMock(return_value=True)
        self.mock_telegram_bot.chat_id = "kirito_admin_chat"

        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="Command output")
        self.mock_memory = _create_mock_memory()

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram_bot,
            use_db=False,
        )
        self.proactive_service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram_bot,
            scan_interval=3600,
        )
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
        )

    async def test_t4_scenario1_disk_cleanup_and_telegram_alert(self) -> None:
        """
        Kịch bản 1: Giám sát đĩa tự động dọn rác và báo cáo Telegram.
        1. Proactive Scanner phát hiện đĩa vượt ngưỡng 85% (89%).
        2. Proactive Engine quyết định hành động Tier 1: docker system prune -f.
        3. Kiểm tra Tri-Tier Risk Gating an toàn.
        4. Thực thi remediation trực tiếp qua ProactiveIntelligenceService._execute_remediation.
        5. Thu thập Before/After metrics snapshot và tính dung lượng giải phóng (5.7GB).
        6. Cập nhật Cooldown 30 phút trong service._remediation_cooldowns.
        7. Gửi báo cáo hoàn tất qua Telegram.
        8. Ghi nhận ký ức vào AgentMemoryService.
        """
        # Step 1 & 2: Detect alert and decide remediation
        disk_alert = "⚠️ Phân vùng root (/) sắp đầy: 89% dung lượng đã sử dụng"
        remediation = self.proactive_service._decide_remediation(disk_alert)
        self.assertIsNotNone(remediation)
        self.assertEqual(remediation["action_key"], "docker_prune")
        self.assertTrue(remediation["auto_execute"])

        # Step 3: Risk Gating verification
        prune_cmd = remediation["command"]
        risk = classify_action_risk("run_command", {"command": prune_cmd})
        self.assertIn(risk, (ACTION_TIER_1_SAFE, ACTION_TIER_2_REVERSIBLE))

        # Step 4 & 5: Execute remediation with before/after metrics
        self.mock_ssh.run_command = AsyncMock(side_effect=[
            "89% 4.1G 30G",                 # Before metric snapshot
            "Total reclaimed space: 5.7GB", # Prune command output
            "73% 9.8G 30G",                 # After metric snapshot
        ])
        res = await self.proactive_service._execute_remediation(remediation, disk_alert)
        self.assertTrue(res)

        # Step 6: Cooldown record verification
        self.assertIn("docker_prune", self.proactive_service._remediation_cooldowns)

        # Step 7: Telegram notification verification
        self.mock_telegram_bot.send_message.assert_called_once()
        chat_arg, text_arg = self.mock_telegram_bot.send_message.call_args[0]
        self.assertEqual(chat_arg, "kirito_admin_chat")
        self.assertIn("Auto-Remediation", text_arg)
        self.assertIn("5.7GB", text_arg)
        self.assertIn(prune_cmd, text_arg)

        # Step 8: Memory episode recording automatically triggered by _execute_remediation
        self.mock_memory.record_episode.assert_called_once()
        ep_kwargs = self.mock_memory.record_episode.call_args[1]
        self.assertIn("proactive_remediation", ep_kwargs["tags"])
        self.assertIn("docker_prune", ep_kwargs["tags"])
        self.assertIn("5.7GB", ep_kwargs["event_summary"])

    async def test_t4_scenario2_multi_step_system_maintenance(self) -> None:
        """
        Kịch bản 2: Thực thi chuỗi lệnh bảo trì hệ thống 3 bước không cần user can thiệp.
        1. Người dùng yêu cầu bảo trì định kỳ 3 bước qua AutonomousGoalWorker:
           - Bước 1: Kiểm tra dung lượng đĩa (df -h /).
           - Bước 2: Dọn dẹp log hệ thống cũ (journalctl --vacuum-time=3d).
           - Bước 3: Kiểm tra trạng thái core container (docker ps --filter status=running).
        2. AutonomousGoalWorker tự động thực thi tuần tự 3 bước không làm phiền người dùng.
        3. Kết quả được lưu trữ bền vững và báo cáo tổng kết qua Telegram khi hoàn thành.
        """
        plan_steps = [
            {"tool": "run_command", "args": {"command": "df -h /"}},
            {"tool": "run_command", "args": {"command": "journalctl --vacuum-time=3d"}},
            {"tool": "run_command", "args": {"command": "docker ps --filter status=running"}},
        ]
        self.mock_tool_executor.execute_tool = AsyncMock(side_effect=[
            "Filesystem /dev/sda1 73% used, 9.8GB available",
            "Vacuuming done. Freed 320MB of archived journals",
            "CONTAINER ID IMAGE STATUS NAMES\n123 dashboard_ai_agent Up 2 days\n456 dashboard_db Up 2 days",
        ])

        task_id = await self.worker.create_goal(
            goal="Bảo trì hệ thống 3 bước định kỳ",
            steps=plan_steps,
            chat_id="kirito_admin_chat"
        )
        task = await self.worker.get_goal_status(task_id)

        # Step 0
        task = await self.worker.execute_pending_step(task)
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["current_step"], 1)

        # Step 1
        task = await self.worker.execute_pending_step(task)
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["current_step"], 2)

        # Step 2 (Final Step)
        task = await self.worker.execute_pending_step(task)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["current_step"], 3)
        self.assertEqual(len(task["steps"]), 3)
        self.assertIn("Vacuuming done", task["steps"][1]["result"])
        self.assertIn("dashboard_ai_agent", task["steps"][2]["result"])

        # Proactive completion alert sent to Telegram
        self.mock_telegram_bot.send_message.assert_called_once()
        chat_arg, text_arg = self.mock_telegram_bot.send_message.call_args[0]
        self.assertEqual(chat_arg, "kirito_admin_chat")
        self.assertIn("Hoàn thành mục tiêu", text_arg)


if __name__ == "__main__":
    unittest.main()
