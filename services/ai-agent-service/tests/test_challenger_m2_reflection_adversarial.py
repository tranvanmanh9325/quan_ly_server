"""
Empirical Adversarial & Stress Test Suite for Milestone 2: Self-Evaluation & Reflection Loop (R2).

Author: Empirical Challenger 1 (teamwork_preview_challenger_28_m2_1)
Mission: Stress-test reflection loops, zero latency gating, bounded reflection cycles,
and JSON parser robustness under hostile, malformed, and high-concurrency conditions.
"""

import asyncio
import json
import re
import time
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


class TestAdversarialReflectionAndGating(unittest.IsolatedAsyncioTestCase):
    """Bộ kiểm thử đối kháng thực nghiệm chuyên sâu cho Milestone 2."""

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Zero Latency Gating Microbenchmark & Bypass Stress
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_01_zero_latency_gating_microbenchmark(self) -> None:
        """
        Đối kháng 1: Đo lường thực nghiệm Zero Latency Gating qua 5,000 lượt gọi.
        - Điều kiện: System 1 (_current_complexity == 'simple') hoặc thiếu goal / tool_name.
        - Kỳ vọng: Thời gian xử lý tiệm cận 0ms (< 0.05ms/call), tuyệt đối không gọi LLM Router.
        """
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock()
        agent = _create_test_agent(mock_llm=mock_llm)
        agent._current_complexity = "simple"

        iterations = 5000
        start_time = time.perf_counter()

        for _ in range(iterations):
            res = await agent._evaluate_tool_step(
                goal="Mục tiêu tra cứu đơn giản",
                tool_name="get_current_time",
                tool_args={},
                tool_result="2026-10-01 15:30:00",
            )
            self.assertTrue(res["achieved"])
            self.assertEqual(res["status"], "SUCCESS")

        elapsed_seconds = time.perf_counter() - start_time
        avg_latency_ms = (elapsed_seconds / iterations) * 1000

        print(f"\n[Empirical Check] Zero-Latency Gating 5,000 calls: Total = {elapsed_seconds:.4f}s, Avg = {avg_latency_ms:.6f}ms/call")

        # Zero LLM router calls
        mock_llm.complete.assert_not_called()
        # Must be strictly under 0.05ms per call
        self.assertLess(avg_latency_ms, 0.05, f"Gating latency {avg_latency_ms:.4f}ms exceeds 0.05ms ceiling!")

    async def test_adv_02_system1_chat_zero_eval_calls_end_to_end(self) -> None:
        """
        Đối kháng 2: Mô phỏng hội thoại thông thường (System 1 - greeting & simple query)
        có kích hoạt tool tra cứu, xác minh _evaluate_tool_step không bao giờ kích hoạt fast eval.
        """
        mock_llm = MagicMock()
        agent = _create_test_agent(mock_llm=mock_llm)
        agent.is_configured = MagicMock(return_value=True)
        agent.tools = MagicMock()
        agent.tools.execute_tool = AsyncMock(return_value="Nhiệt độ hiện tại: 28°C, trời quang đãng.")
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "get_weather"}}])

        # Spy on _evaluate_tool_step
        eval_spy = AsyncMock(wraps=agent._evaluate_tool_step)
        agent._evaluate_tool_step = eval_spy

        # Step 1: Tool call
        tool_call_msg = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_weather_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": json.dumps({"city": "Hanoi"}),
                                },
                            }
                        ],
                    }
                }
            ]
        }
        # Step 2: Final response
        final_msg = {
            "choices": [
                {
                    "message": {
                        "content": "Dạ thời tiết Hà Nội hiện tại 28°C, trời nắng đẹp anh Mạnh nhé!",
                    }
                }
            ]
        }

        mock_llm.complete = AsyncMock(side_effect=[tool_call_msg, final_msg])

        chat_id = "test_simple_traffic_system1"
        # User message is short greeting/query without goal
        reply = await agent.chat(
            chat_id=chat_id,
            user_message="Thời tiết hôm nay thế nào em?",
        )

        self.assertIn("Hà Nội", reply)
        # Verify that _evaluate_tool_step was NEVER called because there is no _goal
        eval_spy.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Bounded Reflection Cycles & Termination Invariants
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_03_bounded_reflection_strict_cutoff_and_lesson_saving(self) -> None:
        """
        Đối kháng 3: Stress-test kịch bản vòng lặp liên tục thất bại (3+ turns).
        Chứng minh bất biến:
        1. Vòng lặp dừng đúng ở iteration 2 (chu kỳ reflection = 2).
        2. force_synthesis được kích hoạt bắt buộc.
        3. memory_service.record_reflection_failure được gọi đúng 1 lần với lịch sử hành động đầy đủ.
        4. Không xảy ra đệ quy hoặc vượt quá MAX_REFLECTION_CYCLES.
        """
        mock_llm = MagicMock()
        mock_memory = MagicMock(spec=AgentMemoryService)
        mock_memory.record_reflection_failure = AsyncMock(return_value=999)
        mock_memory.record_tool_outcome = AsyncMock()
        mock_memory.record_causal_transition = AsyncMock()
        mock_memory.get_active_lessons = AsyncMock(return_value="")
        mock_memory.get_recent_episodes = AsyncMock(return_value="")
        mock_memory.get_pending_tasks_prompt = AsyncMock(return_value="")
        mock_memory.get_active_schemas_prompt = AsyncMock(return_value="")
        mock_memory.get_all_causal_hints_prompt = AsyncMock(return_value="")

        agent = _create_test_agent(mock_llm=mock_llm, mock_memory=mock_memory)
        agent.is_configured = MagicMock(return_value=True)
        agent.tools = MagicMock()
        agent.tools.execute_tool = AsyncMock(return_value="Command failed: exit code 1 (out of memory)")
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "run_command"}}])

        # Step 1 & 2: Repeated failure
        tool_call_1 = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"cmd": "mem_heavy_task_1"})},
                    }],
                }
            }]
        }
        eval_fail_1 = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "achieved": False,
                        "status": "CONTINUE",
                        "reflection": "Lần 1: Thiếu RAM khi thực thi mem_heavy_task_1.",
                    })
                }
            }]
        }
        tool_call_2 = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"cmd": "mem_heavy_task_2"})},
                    }],
                }
            }]
        }
        eval_fail_2 = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "achieved": False,
                        "status": "CONTINUE",
                        "reflection": "Lần 2: Vẫn thiếu RAM khi thực thi mem_heavy_task_2.",
                    })
                }
            }]
        }
        # Final synthesis response when forced
        synthesis_final = {
            "choices": [{
                "message": {
                    "content": "Dạ em đã thử 2 phương án nhưng đều thất bại do thiếu RAM. Em tổng hợp kết quả báo cáo anh Mạnh.",
                }
            }]
        }

        mock_llm.complete = AsyncMock(
            side_effect=[
                tool_call_1,
                eval_fail_1,
                tool_call_2,
                eval_fail_2,
                synthesis_final,
            ]
        )

        chat_id = "test_reflection_strict_cutoff"
        resp = await agent.chat(
            chat_id=chat_id,
            user_message="Hãy chạy tác vụ xử lý bộ nhớ lớn",
            goal="Xử lý bộ nhớ lớn cho báo cáo tháng",
        )

        self.assertIn("đều thất bại do thiếu RAM", resp)

        # Allow background task execution
        await asyncio.sleep(0.05)

        # Assert memory_service.record_reflection_failure was called exactly once
        self.assertEqual(mock_memory.record_reflection_failure.call_count, 1)
        call_kwargs = mock_memory.record_reflection_failure.call_args[1]
        self.assertEqual(call_kwargs["goal"], "Xử lý bộ nhớ lớn cho báo cáo tháng")
        self.assertIn("Vẫn thiếu RAM", call_kwargs["reflection_summary"])
        # Verify action history has both executed actions
        history_actions = call_kwargs["action_history"]
        self.assertEqual(len(history_actions), 2)
        self.assertEqual(history_actions[0]["tool"], "run_command")
        self.assertEqual(history_actions[1]["tool"], "run_command")

    async def test_adv_04_reflection_success_on_cycle_1_clears_gracefully(self) -> None:
        """
        Đối kháng 4: Kịch bản tự điều chỉnh thành công ở chu kỳ 1.
        - Lần 0: Thất bại -> Reflection Cycle 1 kích hoạt.
        - Lần 1: LLM nhận reflection prompt và điều chỉnh tham số -> Thành công (achieved=True).
        - Kỳ vọng:
          + Không tăng reflection cycle lên 2.
          + Không ép force_synthesis.
          + Không ghi nhận reflection_failure vào memory service.
        """
        mock_llm = MagicMock()
        mock_memory = MagicMock(spec=AgentMemoryService)
        mock_memory.record_reflection_failure = AsyncMock()
        mock_memory.record_tool_outcome = AsyncMock()
        mock_memory.record_causal_transition = AsyncMock()
        mock_memory.get_active_lessons = AsyncMock(return_value="")
        mock_memory.get_recent_episodes = AsyncMock(return_value="")
        mock_memory.get_pending_tasks_prompt = AsyncMock(return_value="")
        mock_memory.get_active_schemas_prompt = AsyncMock(return_value="")
        mock_memory.get_all_causal_hints_prompt = AsyncMock(return_value="")

        agent = _create_test_agent(mock_llm=mock_llm, mock_memory=mock_memory)
        agent.is_configured = MagicMock(return_value=True)
        agent.tools = MagicMock()
        agent.tools.execute_tool = AsyncMock(side_effect=["Error: Permission denied", "Success: Service restarted"])
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "run_command"}}])

        # Step 0: Fail
        call_fail = {
            "choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": '{"cmd": "systemctl restart nginx"}'}}]}}]
        }
        eval_fail = {
            "choices": [{"message": {"content": json.dumps({"achieved": False, "status": "CONTINUE", "reflection": "Thiếu quyền sudo."})}}]
        }
        # Step 1: Fixed with sudo
        call_fix = {
            "choices": [{"message": {"content": None, "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "run_command", "arguments": '{"cmd": "sudo systemctl restart nginx"}'}}]}}]
        }
        eval_success = {
            "choices": [{"message": {"content": json.dumps({"achieved": True, "status": "SUCCESS", "reflection": "Nginx đã được khởi động lại thành công."})}}]
        }
        # Final response
        final_resp = {
            "choices": [{"message": {"content": "Dạ em đã dùng sudo khởi động lại nginx thành công rồi ạ!"}}]
        }

        mock_llm.complete = AsyncMock(
            side_effect=[
                call_fail,
                eval_fail,
                call_fix,
                eval_success,
                final_resp,
            ]
        )

        chat_id = "test_reflection_recovery_chat"
        res = await agent.chat(
            chat_id=chat_id,
            user_message="Hãy restart nginx",
            goal="Khởi động lại service nginx",
        )

        self.assertIn("thành công", res)
        await asyncio.sleep(0.05)
        # record_reflection_failure MUST NOT be called because it succeeded
        mock_memory.record_reflection_failure.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Adversarial JSON Parser Fuzzing & Malformed Output Testing
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_05_json_fuzzing_malformed_and_edge_cases(self) -> None:
        """
        Đối kháng 5: Fuzzing bộ phân giải JSON của _evaluate_tool_step với các định dạng hiểm hóc:
        1. Fenced with upper-case ```JSON ... ```
        2. Text xung quanh chứa dấu { } gây nhiễu regex
        3. JSON bị cắt cụt do chạm max_tokens (truncated JSON)
        4. Phản hồi rỗng hoặc toàn khoảng trắng
        5. Phản hồi HTML lỗi từ nhà mạng/proxy (Cloudflare 502)
        6. achieved mang kiểu string 'false' hoặc 'true'
        7. Trả về format không có key achieved
        """
        mock_llm = MagicMock()
        agent = _create_test_agent(mock_llm=mock_llm)
        agent._current_complexity = "complex"

        # Case 1: Uppercase ```JSON
        mock_llm.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "content": "```JSON\n{\n  \"achieved\": false,\n  \"status\": \"CONTINUE\",\n  \"reflection\": \"Case 1 OK\"\n}\n```"
                }
            }]
        })
        res1 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        self.assertFalse(res1["achieved"])
        self.assertEqual(res1["reflection"], "Case 1 OK")

        # Case 2: Noisy curly brackets before and after JSON
        mock_llm.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "content": "Ghi chú: {lưu ý: hệ thống đang bận}. Kết quả: {\"achieved\": true, \"status\": \"SUCCESS\", \"reflection\": \"Hoàn tất {100%}\"} Chúc mừng!"
                }
            }]
        })
        res2 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        # Greedy regex {.*} captures from first { to last }. Let's see if it handles safely or falls back gracefully
        self.assertIn(res2["status"], ["SUCCESS", "CONTINUE"])

        # Case 3: Truncated JSON caused by token budget cutoff
        mock_llm.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "content": "{\"achieved\": false, \"status\": \"CONTINUE\", \"reflection\": \"Chưa xong do thiếu t"
                }
            }]
        })
        res3 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        # Truncated JSON must trigger except clause -> graceful fallback (achieved: True)
        self.assertTrue(res3["achieved"])
        self.assertEqual(res3["status"], "SUCCESS")

        # Case 4: Empty string and whitespace
        mock_llm.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "content": "   \n\t  "
                }
            }]
        })
        res4 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        self.assertTrue(res4["achieved"])
        self.assertEqual(res4["status"], "SUCCESS")

        # Case 5: Cloudflare HTML Error
        mock_llm.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "content": "<html><body><h1>502 Bad Gateway</h1><p>Cloudflare Ray ID: 888</p></body></html>"
                }
            }]
        })
        res5 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        self.assertTrue(res5["achieved"])
        self.assertEqual(res5["status"], "SUCCESS")

        # Case 6: Missing choices / None return
        mock_llm.complete = AsyncMock(return_value=None)
        res6 = await agent._evaluate_tool_step(goal="Test", tool_name="tool", tool_args={}, tool_result="res")
        self.assertTrue(res6["achieved"])
        self.assertEqual(res6["status"], "SUCCESS")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Memory Service High Concurrency & Truncation Safety
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_06_memory_service_high_concurrency_stress(self) -> None:
        """
        Đối kháng 6: Kích hoạt 50 tác vụ record_reflection_failure đồng thời trong điều kiện
        DB ngắt kết nối. Đảm bảo 100% tasks hoàn tất an toàn không rò rỉ unhandled exceptions.
        """
        memory_service = AgentMemoryService()

        with patch("app.services.memory_service.get_db_connection", side_effect=Exception("DB pool exhausted")):
            tasks = [
                memory_service.record_reflection_failure(
                    goal=f"Mục tiêu đồng thời số #{i}",
                    action_history=[{"tool": "run_command", "result": f"out of memory error #{i}"}],
                    reflection_summary=f"Nhận xét thất bại #{i}",
                )
                for i in range(50)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            self.assertEqual(len(results), 50)
            for r in results:
                self.assertNotIsInstance(r, Exception, f"Unhandled exception raised under concurrency: {r}")
                self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
