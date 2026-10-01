"""
Unit and Integration Tests for R2: Self-Evaluation & Reflection Loop.

Verifies:
1. Fast LLM Goal Evaluation via Groq pool (llama-3.1-8b-instant) and robust JSON parsing.
2. Zero Latency Gating: bypasses fast evaluation for normal simple chat.
3. Bounded Reflection Cycles: stops at MAX_REFLECTION_CYCLES = 2 and forces synthesis.
4. Memory Service Lesson Recording: saves episodic memory and procedural lesson upon reaching reflection limit.
5. Graceful Fallback: handles LLM router errors without crashing agent loop.
6. Behavioral verification of process_message alias and MAX_REFLECTION_CYCLES constant.
"""

import asyncio
import json
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent import AiAgentService, MAX_REFLECTION_CYCLES
from app.services.memory_service import AgentMemoryService, RootCauseCategory
from app.core.brain_core import ArtificialBrain


def _create_test_agent(
    mock_llm: Optional[MagicMock] = None,
    mock_memory: Optional[MagicMock] = None,
) -> AiAgentService:
    """Helper to create AiAgentService with mocked dependencies."""
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


class TestReflectionLoop(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

    async def test_01_constant_max_reflection_cycles(self) -> None:
        """Kiểm tra hằng số trần phản biện bắt buộc MAX_REFLECTION_CYCLES = 2."""
        self.assertEqual(MAX_REFLECTION_CYCLES, 2)

    async def test_02_evaluate_tool_step_success_and_json_parsing(self) -> None:
        """
        Kiểm tra parse JSON từ phản hồi của Fast LLM (Groq llama-3.1-8b-instant):
        - JSON chuẩn không markdown
        - JSON bọc trong markdown code fence ```json ... ```
        - JSON nằm bên trong chuỗi text có giải thích
        """
        mock_llm = MagicMock()
        agent = _create_test_agent(mock_llm=mock_llm)

        # 1. Standard valid JSON
        mock_llm.complete = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "achieved": True,
                                "status": "SUCCESS",
                                "reflection": "Dung lượng đĩa đã được thu thập đầy đủ.",
                            })
                        }
                    }
                ]
            }
        )
        res1 = await agent._evaluate_tool_step(
            goal="Kiểm tra dung lượng đĩa",
            tool_name="run_command",
            tool_args={"command": "df -h"},
            tool_result="Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 50G 20G 30G 40% /",
        )
        self.assertTrue(res1["achieved"])
        self.assertEqual(res1["status"], "SUCCESS")
        self.assertEqual(res1["reflection"], "Dung lượng đĩa đã được thu thập đầy đủ.")

        # 2. Markdown fenced JSON
        mock_llm.complete = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n" + json.dumps({
                                "achieved": False,
                                "status": "CONTINUE",
                                "reflection": "Chưa có thông tin RAM, chỉ mới có thông tin CPU.",
                            }) + "\n```"
                        }
                    }
                ]
            }
        )
        res2 = await agent._evaluate_tool_step(
            goal="Kiểm tra toàn diện CPU và RAM",
            tool_name="run_command",
            tool_args={"command": "lscpu"},
            tool_result="Architecture: x86_64, CPU(s): 2",
        )
        self.assertFalse(res2["achieved"])
        self.assertEqual(res2["status"], "CONTINUE")
        self.assertEqual(res2["reflection"], "Chưa có thông tin RAM, chỉ mới có thông tin CPU.")

        # 3. Embedded JSON inside text
        mock_llm.complete = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "Phân tích kết quả: " + json.dumps({
                                "achieved": False,
                                "status": "FATAL_ERROR",
                                "reflection": "Tài nguyên server không khả dụng.",
                            })
                        }
                    }
                ]
            }
        )
        res3 = await agent._evaluate_tool_step(
            goal="Khởi động service mysql",
            tool_name="run_command",
            tool_args={"command": "systemctl start mysql"},
            tool_result="Job for mysql.service failed because of OOM.",
        )
        self.assertFalse(res3["achieved"])
        self.assertEqual(res3["status"], "FATAL_ERROR")
        self.assertEqual(res3["reflection"], "Tài nguyên server không khả dụng.")

    async def test_03_zero_latency_gating_bypasses_simple_chat(self) -> None:
        """
        Kiểm tra Zero Latency Gating:
        - Khi câu hỏi thuộc System 1 (simple) và không có goal: không bao giờ gọi fast LLM evaluation.
        - Gọi _evaluate_tool_step trực tiếp khi _current_complexity == 'simple' trả về ngay lập tức.
        """
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock()
        agent = _create_test_agent(mock_llm=mock_llm)

        # Set complexity to simple
        agent._current_complexity = "simple"

        # Direct call to _evaluate_tool_step should bypass immediately
        res = await agent._evaluate_tool_step(
            goal="Chào hỏi đơn giản",
            tool_name="some_tool",
            tool_args={},
            tool_result="Xin chào!",
        )
        self.assertTrue(res["achieved"])
        self.assertEqual(res["status"], "SUCCESS")
        # LLM complete should NOT have been called
        mock_llm.complete.assert_not_called()

        # Missing goal or tool_name also bypasses immediately
        res_empty = await agent._evaluate_tool_step(
            goal="",
            tool_name="run_command",
            tool_args={},
            tool_result="ok",
        )
        self.assertTrue(res_empty["achieved"])
        mock_llm.complete.assert_not_called()

    async def test_04_bounded_reflection_cycles_stops_at_max(self) -> None:
        """
        Kiểm tra Bounded Reflection Injection và giới hạn dừng:
        - Tool thất bại ngữ nghĩa -> sinh Reflection Note inject vào prompt vòng sau.
        - Giới hạn đúng MAX_REFLECTION_CYCLES = 2 -> ép force_synthesis = True.
        - Gọi memory_service.record_reflection_failure khi chạm trần.
        """
        mock_llm = MagicMock()
        mock_memory = MagicMock(spec=AgentMemoryService)
        mock_memory.record_reflection_failure = AsyncMock(return_value=123)
        mock_memory.record_tool_outcome = AsyncMock()
        mock_memory.record_causal_transition = AsyncMock()
        mock_memory.get_active_lessons = AsyncMock(return_value="")
        mock_memory.get_recent_episodes = AsyncMock(return_value="")
        mock_memory.get_pending_tasks_prompt = AsyncMock(return_value="")
        mock_memory.get_active_schemas_prompt = AsyncMock(return_value="")
        mock_memory.get_all_causal_hints_prompt = AsyncMock(return_value="")

        agent = _create_test_agent(mock_llm=mock_llm, mock_memory=mock_memory)
        # Mock is_configured to True
        agent.is_configured = MagicMock(return_value=True)
        # Mock tool executor to simulate a tool execution
        agent.tools = MagicMock()
        agent.tools.execute_tool = AsyncMock(return_value="Error: port 8080 already in use")
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "run_command"}}])

        # Step 1 LLM response: emit tool call
        tool_call_msg = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": json.dumps({"command": "start_app"}),
                                },
                            }
                        ],
                    }
                }
            ]
        }

        # Step 2 LLM response: fast evaluation LLM response (Groq llama-3.1-8b-instant)
        eval_failed_msg = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "achieved": False,
                            "status": "CONTINUE",
                            "reflection": "Cổng 8080 bị chiếm dụng, cần kiểm tra process đang giữ cổng.",
                        })
                    }
                }
            ]
        }

        # Step 3 LLM response: final synthesis response
        synthesis_msg = {
            "choices": [
                {
                    "message": {
                        "content": "Dạ em đã kiểm tra và thấy cổng 8080 bị chiếm dụng. Em đã dừng thử lại và tổng hợp báo cáo cho anh Mạnh.",
                    }
                }
            ]
        }

        # Sequentially return:
        # Turn 1: tool_call -> eval_failed
        # Turn 2: tool_call -> eval_failed (hits MAX_REFLECTION_CYCLES = 2) -> synthesis
        mock_llm.complete = AsyncMock(
            side_effect=[
                tool_call_msg,    # iter 0 main LLM
                eval_failed_msg,  # iter 0 fast eval (cycle 1)
                tool_call_msg,    # iter 1 main LLM
                eval_failed_msg,  # iter 1 fast eval (cycle 2 -> hits MAX_REFLECTION_CYCLES)
                synthesis_msg,    # iter 2 main LLM (forced synthesis)
            ]
        )

        chat_id = "test_reflection_chat_1"
        response = await agent.chat(
            chat_id=chat_id,
            user_message="Khởi động service backend",
            goal="Khởi động service backend",
        )

        self.assertIn("cổng 8080", response)

        # Verify that reflection note was injected into history
        history = agent._history_map.get(chat_id, [])
        reflection_notes = [
            m["content"] for m in history
            if m.get("role") == "user" and "[Reflection:" in str(m.get("content", ""))
        ]
        self.assertGreaterEqual(len(reflection_notes), 1)
        self.assertIn("Cổng 8080 bị chiếm dụng", reflection_notes[0])

        # Verify that memory_service.record_reflection_failure was triggered
        await asyncio.sleep(0.05)  # Allow background task to execute
        mock_memory.record_reflection_failure.assert_called()

    async def test_05_memory_service_record_reflection_failure(self) -> None:
        """
        Kiểm tra AgentMemoryService.record_reflection_failure:
        - Khi không có DB: trả về None an toàn, không văng exception.
        - Khi có DB (mocked): ghi nhận episodic memory ('reflection_failure') và lesson ('reflection_lesson').
        """
        memory_service = AgentMemoryService()

        # 1. Fallback without DB (DB connection raises exception)
        with patch("app.services.memory_service.get_db_connection", side_effect=Exception("Database connection refused")):
            mem_id = await memory_service.record_reflection_failure(
                goal="Dọn dẹp swap memory",
                action_history=[{"tool": "run_command", "result": "permission denied"}],
                reflection_summary="Thiếu quyền sudo khi swapoff",
                root_cause=RootCauseCategory.TOOL_FAILURE,
            )
            self.assertIsNone(mem_id)

        # 2. Successful DB record with mocked connection and cursor
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(side_effect=[(101,), (202,)])  # memory_id=101, lesson_id=202
        mock_cursor.execute = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock()
        mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_conn.commit = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.memory_service.get_db_connection", return_value=mock_cm):
            memory_id = await memory_service.record_reflection_failure(
                goal="Dọn dẹp swap memory",
                action_history=[{"tool": "run_command", "result": "permission denied"}],
                reflection_summary="Thiếu quyền sudo khi swapoff",
                root_cause=RootCauseCategory.TOOL_FAILURE,
            )
            self.assertEqual(memory_id, 101)

            # Verify SQL execution contains expected event types
            executed_sqls = [call.args[0] for call in mock_cursor.execute.call_args_list if call.args]
            self.assertTrue(any("INSERT INTO agent_memories" in sql for sql in executed_sqls))
            self.assertTrue(any("INSERT INTO agent_lessons" in sql for sql in executed_sqls))
            self.assertTrue(any("UPDATE agent_memories SET lesson_id" in sql for sql in executed_sqls))

    async def test_06_fallback_on_llm_evaluation_error(self) -> None:
        """
        Kiểm tra khi Fast LLM gặp lỗi (TimeoutError / network drop / JSON hỏng):
        - _evaluate_tool_step bắt ngoại lệ và trả về graceful fallback.
        - Agent ReAct loop không bị crash.
        """
        mock_llm = MagicMock()
        # Simulate network timeout on fast evaluation
        mock_llm.complete = AsyncMock(side_effect=asyncio.TimeoutError("Groq endpoint timeout"))
        agent = _create_test_agent(mock_llm=mock_llm)

        res = await agent._evaluate_tool_step(
            goal="Kiểm tra trạng thái nginx",
            tool_name="run_command",
            tool_args={"command": "systemctl status nginx"},
            tool_result="nginx is running",
        )
        self.assertTrue(res["achieved"])
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["reflection"], "")

    async def test_07_process_message_alias_behavior(self) -> None:
        """Kiểm tra alias process_message chuyển hướng trực tiếp và minh bạch sang chat()."""
        agent = _create_test_agent()
        agent.chat = AsyncMock(return_value="Dạ em chào anh Mạnh!")

        reply = await agent.process_message("chat_test", "Xin chào", goal="Test Goal")
        self.assertEqual(reply, "Dạ em chào anh Mạnh!")
        agent.chat.assert_called_once_with("chat_test", "Xin chào", goal="Test Goal")


if __name__ == "__main__":
    unittest.main()
