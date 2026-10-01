"""
Tier 5 Adversarial Coverage Hardening Test Suite for Milestone 5 (R1 & R2).
Challenger 1 Empirical Verification Harness.

Target Modules:
- R1: services/ai-agent-service/app/services/autonomous_goal_worker.py
- R2: services/ai-agent-service/app/services/ai_agent.py
- R2: services/ai-agent-service/app/services/memory_service.py

Adversarial Stress Surfaces:
1. Concurrent cancel_goal storms and micro-state race conditions.
2. Groq Fast Evaluation response mutations (malformed JSON, missing fields, nested markdown, network errors).
3. Hard ceiling enforcement of MAX_REFLECTION_CYCLES = 2 without bypass.
4. Invariance of terminal states ('completed', 'cancelled') against concurrent stale updates.
5. Resource lifecycle safety and clean task teardown upon abrupt worker stop().
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Optional pytest support without crashing on missing pytest-asyncio
try:
    import pytest

    @pytest.fixture(autouse=True)
    def cleanup_shared_http_clients():
        # Override async conftest fixture to maintain compatibility with pytest 9.1 on Python 3.14
        yield
except ImportError:
    pytest = None

from app.core.brain_core import ArtificialBrain
from app.services.autonomous_goal_worker import (
    AutonomousGoalWorker,
    InMemoryTaskStore,
)
from app.services.ai_agent import (
    AiAgentService,
    MAX_REFLECTION_CYCLES,
    MAX_AGENT_ITERATIONS,
)
from app.services.ai_agent_tools import (
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
)
from app.services.memory_service import AgentMemoryService


def _create_mock_memory() -> MagicMock:
    mock_memory = MagicMock(spec=AgentMemoryService)
    mock_memory.record_reflection_failure = AsyncMock(return_value=999)
    mock_memory.record_tool_outcome = AsyncMock()
    mock_memory.record_causal_transition = AsyncMock()
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
    # Factory to provide isolated AiAgentService instances with controlled mocks
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


class TestChallengerM5AdversarialCoverage(unittest.IsolatedAsyncioTestCase):
    """Tier 5 Adversarial Stress Test Suite for R1 and R2."""

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Command executed successfully. Exit code: 0")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_m5"
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

    # ═════════════════════════════════════════════════════════════════════════
    # PART 1: BÃO HỦY ĐỒNG THỜI & MICRO-STATE RACE CONDITIONS (R1)
    # ═════════════════════════════════════════════════════════════════════════

    async def test_adv_01_concurrent_cancel_storm_during_in_flight_tool_execution(self) -> None:
        # Micro-state: Goal cancelled by 50 concurrent requests while tool I/O is suspended in asyncio.sleep
        tool_started_event = asyncio.Event()

        async def _slow_tool(*args, **kwargs):
            tool_started_event.set()
            await asyncio.sleep(0.08)
            return "Slow tool finished successfully."

        self.mock_executor.execute_tool = AsyncMock(side_effect=_slow_tool)

        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "sleep 1"}, "verify": "completed"},
            {"step_id": 2, "tool": "run_command", "args": {"command": "echo step2"}, "verify": "completed"},
        ]
        task_id = await self.worker.create_goal(goal="Adversarial in-flight cancel storm", steps=steps)

        # Launch step execution in background
        exec_task = asyncio.create_task(self.worker.poll_once())
        await tool_started_event.wait()

        # Fire 50 concurrent cancellation requests
        cancel_tasks = [
            self.worker.cancel_goal(task_id, reason=f"Concurrent cancel request #{i}")
            for i in range(50)
        ]
        results = await asyncio.gather(*cancel_tasks)
        await exec_task

        # Exactly one cancellation must win, others must yield False
        success_count = sum(1 for r in results if r is True)
        self.assertEqual(success_count, 1, f"Expected exactly 1 cancel winner, got {success_count}")

        # The task must be cancelled and not progressed to step 2 or marked running/completed
        status = await self.worker.get_goal_status(task_id)
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["current_step"], 0)
        self.assertIsNotNone(status["completed_at"])

        # Subsequent polling must ignore the cancelled task
        processed_next = await self.worker.poll_once()
        self.assertEqual(processed_next, 0)
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)

    async def test_adv_02_cancel_storm_during_failing_step_exception_handling(self) -> None:
        # Micro-state: Tool throws fatal exception while concurrent cancellation strikes
        tool_started_event = asyncio.Event()

        async def _failing_tool(*args, **kwargs):
            tool_started_event.set()
            await asyncio.sleep(0.05)
            raise RuntimeError("Fatal hardware I/O interrupt")

        self.mock_executor.execute_tool = AsyncMock(side_effect=_failing_tool)

        steps = [{"step_id": 1, "tool": "run_command", "args": {"command": "faulty_cmd"}, "verify": "ok"}]
        task_id = await self.worker.create_goal(goal="Adversarial exception race goal", steps=steps)

        exec_task = asyncio.create_task(self.worker.poll_once())
        await tool_started_event.wait()

        # Cancel while exception is being raised
        cancel_res = await self.worker.cancel_goal(task_id, reason="Emergency abort during failure")
        self.assertTrue(cancel_res)
        await exec_task

        # Invariant: Cancelled status must NOT be overridden by 'failed' or increment retry_count
        status = await self.worker.get_goal_status(task_id)
        self.assertEqual(status["status"], "cancelled")
        self.assertIn("Emergency abort", status["error_message"])
        self.assertEqual(status["retry_count"], 0)

    async def test_adv_03_cancel_vs_completion_race_at_final_step(self) -> None:
        # Micro-state: Cancellation attempts right as final step completes
        task_id = await self.worker.create_goal(
            goal="One-shot final step goal",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "exit 0"}}],
        )

        # Complete the task
        await self.worker.poll_once()
        status_after_poll = await self.worker.get_goal_status(task_id)
        self.assertEqual(status_after_poll["status"], "completed")

        # Attempt to cancel an already completed task
        cancel_res = await self.worker.cancel_goal(task_id, reason="Late cancel attempt")
        self.assertFalse(cancel_res, "Completed task must reject cancellation attempts")

        status_final = await self.worker.get_goal_status(task_id)
        self.assertEqual(status_final["status"], "completed")

    async def test_adv_04_cancel_waiting_approval_task_releases_safely(self) -> None:
        # Micro-state: Task is trapped in waiting_approval due to Tier 3 Lethal gating
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf / --no-preserve-root"}},
        ]
        task_id = await self.worker.create_goal(goal="Lethal command task", steps=steps)

        # Trigger execution -> gets halted by Spinal Safety Gate
        await self.worker.poll_once()
        status_waiting = await self.worker.get_goal_status(task_id)
        self.assertEqual(status_waiting["status"], "waiting_approval")

        # Cancel while in waiting_approval
        cancel_res = await self.worker.cancel_goal(task_id, reason="Rejected lethal action by operator")
        self.assertTrue(cancel_res)

        status_final = await self.worker.get_goal_status(task_id)
        self.assertEqual(status_final["status"], "cancelled")
        self.assertEqual(status_final["error_message"], "Rejected lethal action by operator")

    async def test_adv_05_batch_queue_cancellation_storm(self) -> None:
        # Micro-state: Create 10 pending tasks and blast cancel_goal across all simultaneously
        task_ids = []
        for i in range(10):
            t_id = await self.worker.create_goal(
                goal=f"Batch task #{i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": f"echo {i}"}}],
            )
            task_ids.append(t_id)

        # Cancel all 10 tasks concurrently
        cancel_tasks = [self.worker.cancel_goal(tid, reason="Batch purge") for tid in task_ids]
        results = await asyncio.gather(*cancel_tasks)
        self.assertTrue(all(results))

        # Ensure none are picked up by polling
        processed = await self.worker.poll_once()
        self.assertEqual(processed, 0)

        tasks = await self.worker.list_goals(status="cancelled", limit=20)
        self.assertGreaterEqual(len(tasks), 10)

    # ═════════════════════════════════════════════════════════════════════════
    # PART 2: BIẾN DỊ PHẢN HỒI GROQ FAST EVALUATION (R2)
    # ═════════════════════════════════════════════════════════════════════════

    async def test_adv_06_fast_eval_mutation_malformed_syntax_fuzzing(self) -> None:
        # Groq returns truncated, unbalanced, or completely garbled non-JSON strings
        malformed_payloads = [
            '{"achieved": fals',                                 # Truncated boolean
            '{"achieved": false, "status": "CONTINUE",}',        # Trailing comma
            '<html><body>502 Bad Gateway: Nginx</body></html>',  # Cloudflare / Proxy error
            '<<<NOT_JSON>>> {"achieved": false',                # Binary-like syntax corruption
            '',                                                  # Empty response string
            'null',                                              # Literal null
            '{"achieved": false "status": "CONTINUE"}',          # Missing comma separator
        ]

        agent = _create_mock_agent()

        for payload in malformed_payloads:
            mock_resp = {"choices": [{"message": {"content": payload}}]}
            agent.llm_router.complete = AsyncMock(return_value=mock_resp)

            # Fallback must be achieved=True, status="SUCCESS" to prevent blocking ReAct loop
            eval_result = await agent._evaluate_tool_step(
                goal="Kiểm tra phân vùng ổ đĩa",
                tool_name="run_command",
                tool_args={"command": "df -h"},
                tool_result="/dev/sda1 85% used",
            )
            self.assertIsInstance(eval_result, dict)
            self.assertTrue(eval_result.get("achieved"), f"Failed on payload: {payload}")
            self.assertEqual(eval_result.get("status"), "SUCCESS")

    async def test_adv_07_fast_eval_mutation_missing_fields_and_type_coercion(self) -> None:
        # Groq returns partial JSON or unexpected data types
        mutation_cases = [
            ({}, True, "SUCCESS", ""),
            ({"status": "FATAL_ERROR"}, True, "FATAL_ERROR", ""),
            ({"achieved": False}, False, "SUCCESS", ""),
            ({"achieved": True, "reflection": None}, True, "SUCCESS", "None"),
            ({"achieved": 0, "status": 500, "reflection": 12345}, False, "500", "12345"),
        ]

        agent = _create_mock_agent()

        for payload, exp_achieved, exp_status, exp_reflection in mutation_cases:
            mock_resp = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            agent.llm_router.complete = AsyncMock(return_value=mock_resp)

            eval_result = await agent._evaluate_tool_step(
                goal="Kiểm tra RAM",
                tool_name="run_command",
                tool_args={"command": "free -m"},
                tool_result="Mem: 3200 total, 1500 free",
            )
            self.assertEqual(eval_result["achieved"], exp_achieved)
            self.assertEqual(eval_result["status"], exp_status)
            self.assertEqual(eval_result["reflection"], exp_reflection)

    async def test_adv_08_fast_eval_mutation_nested_markdown_and_prose_embedding(self) -> None:
        # LLM wraps JSON in markdown fences, backticks, or prefix/suffix prose
        noisy_payloads = [
            "```json\n{\"achieved\": false, \"status\": \"CONTINUE\", \"reflection\": \"RAM usage is still above 85%\"}\n```",
            "Dạ thưa anh, kết quả như sau: {\"achieved\": false, \"status\": \"CONTINUE\", \"reflection\": \"Chưa khởi động nginx\"} chúc anh một ngày tốt lành.",
            "```markdown\n```json\n{\"achieved\": true, \"status\": \"SUCCESS\", \"reflection\": \"Mục tiêu đã hoàn thành hoàn hảo.\"}\n```\n```",
        ]

        agent = _create_mock_agent()

        # Case 1: unachieved in code block
        agent.llm_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": noisy_payloads[0]}}]})
        res1 = await agent._evaluate_tool_step(goal="Clear RAM", tool_name="run_command", tool_args={}, tool_result="")
        self.assertFalse(res1["achieved"])
        self.assertEqual(res1["reflection"], "RAM usage is still above 85%")

        # Case 2: unachieved with conversational prose
        agent.llm_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": noisy_payloads[1]}}]})
        res2 = await agent._evaluate_tool_step(goal="Start nginx", tool_name="run_command", tool_args={}, tool_result="")
        self.assertFalse(res2["achieved"])
        self.assertEqual(res2["reflection"], "Chưa khởi động nginx")

        # Case 3: achieved in nested markdown
        agent.llm_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": noisy_payloads[2]}}]})
        res3 = await agent._evaluate_tool_step(goal="Finish test", tool_name="run_command", tool_args={}, tool_result="")
        self.assertTrue(res3["achieved"])
        self.assertEqual(res3["reflection"], "Mục tiêu đã hoàn thành hoàn hảo.")

    async def test_adv_09_fast_eval_network_transient_failure_and_timeout(self) -> None:
        # Network timeouts or connection drops during evaluation must fallback gracefully
        agent = _create_mock_agent()

        network_exceptions = [
            asyncio.TimeoutError("Upstream evaluation call timed out after 90ms"),
            ConnectionResetError("Socket connection reset by Groq edge server"),
            RuntimeError("Groq 429 TPM Rate Limit Exceeded"),
        ]

        for exc in network_exceptions:
            agent.llm_router.complete = AsyncMock(side_effect=exc)
            res = await agent._evaluate_tool_step(
                goal="Mục tiêu khi rớt mạng",
                tool_name="run_command",
                tool_args={},
                tool_result="result",
            )
            self.assertTrue(res["achieved"])
            self.assertEqual(res["status"], "SUCCESS")

    # ═════════════════════════════════════════════════════════════════════════
    # PART 3: NGƯỠNG CHẶN TUYỆT ĐỐI MAX_REFLECTION_CYCLES = 2 (R2)
    # ═════════════════════════════════════════════════════════════════════════

    async def test_adv_10_reflection_cycles_hard_ceiling_enforced_at_2(self) -> None:
        # Stubborn LLM repeatedly tries to execute tools and evaluation repeatedly rejects
        mock_llm = MagicMock()
        mock_memory = _create_mock_memory()
        mock_memory.record_reflection_failure = AsyncMock(return_value=101)

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
                                "id": "call_adv_stubborn",
                                "type": "function",
                                "function": {"name": "run_command", "arguments": '{"command": "try_fix.sh"}'},
                            }
                        ],
                    }
                }
            ]
        }
        synthesis_resp = {
            "choices": [{"message": {"content": "Dạ em đã tổng hợp câu trả lời cuối cùng sau khi chạm trần phản biện."}}]
        }

        eval_fail_resp = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "achieved": False,
                            "status": "CONTINUE",
                            "reflection": "Thử nghiệm sửa lỗi chưa thành công, cần đổi tham số.",
                        })
                    }
                }
            ]
        }

        # Sequence: iter0 LLM -> iter0 eval -> iter1 LLM -> iter1 eval -> iter2 synthesis LLM
        mock_llm.complete = AsyncMock(side_effect=[
            tool_call_resp,
            eval_fail_resp,
            tool_call_resp,
            eval_fail_resp,
            synthesis_resp,
        ])

        final_reply = await agent.chat(
            chat_id="chat_reflection_stress",
            user_message="Hãy theo dõi và tự động khắc phục sự cố dịch vụ nginx",
            goal="Tự động khắc phục sự cố dịch vụ nginx",
        )

        self.assertIn("tổng hợp", final_reply)

        # Verify memory_service.record_reflection_failure was triggered exactly once
        self.assertEqual(mock_memory.record_reflection_failure.call_count, 1)
        kwargs = mock_memory.record_reflection_failure.call_args.kwargs
        self.assertIn("nginx", kwargs["goal"])
        self.assertIn("Thử nghiệm sửa lỗi", kwargs["reflection_summary"])
        self.assertGreaterEqual(len(kwargs["action_history"]), 2)

    async def test_adv_11_adversarial_attempt_to_bypass_cycle_limit_with_pseudo_xml(self) -> None:
        # LLM attempts to emit raw pseudo-XML tool calls after reflection ceiling is reached
        mock_llm = MagicMock()
        mock_memory = _create_mock_memory()
        mock_memory.record_reflection_failure = AsyncMock(return_value=102)

        agent = _create_mock_agent(mock_llm=mock_llm, mock_memory=mock_memory)
        agent.is_configured = MagicMock(return_value=True)
        agent.tools = MagicMock()
        agent.tools.flush_pending_photos = AsyncMock()
        agent.tools.execute_tool = AsyncMock(return_value="Command output")
        agent.tools.build_tools = MagicMock(return_value=[{"type": "function", "function": {"name": "run_command"}}])

        # Iter 0: tool call -> eval fail (cycle 1)
        # Iter 1: tool call -> eval fail (cycle 2)
        # Iter 2: LLM tries to emit pseudo tool call instead of synthesis
        # Iter 3: fallback synthesis
        call_msg = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": '{"command": "check"}'},
                    }],
                }
            }]
        }
        eval_fail = {
            "choices": [{
                "message": {"content": '{"achieved": false, "status": "CONTINUE", "reflection": "Chưa xong"}'}
            }]
        }
        pseudo_xml_leak = {
            "choices": [{
                "message": {
                    "content": '<function=run_command>{"command": "bypass_attempt"}</function>'
                }
            }]
        }
        final_synth = {
            "choices": [{"message": {"content": "Kết luận dứt khoát sau khi chặn pseudo-tool leak."}}]
        }

        mock_llm.complete = AsyncMock(side_effect=[
            call_msg,
            eval_fail,
            call_msg,
            eval_fail,
            pseudo_xml_leak,
            final_synth,
        ])

        reply = await agent.chat(
            chat_id="chat_xml_bypass",
            user_message="Hãy kiểm tra và sửa",
            goal="Sửa lỗi hệ thống",
        )

        self.assertIn("Kết luận dứt khoát", reply)
        # Memory service must still be called exactly once
        self.assertEqual(mock_memory.record_reflection_failure.call_count, 1)

    async def test_adv_12_zero_latency_gating_preserves_zero_cycles_on_simple_chat(self) -> None:
        # System 1 simple query must never increment reflection cycles or invoke evaluator
        mock_llm = MagicMock()
        agent = _create_mock_agent(mock_llm=mock_llm)
        agent._current_complexity = "simple"

        eval_spy = AsyncMock(wraps=agent._evaluate_tool_step)
        agent._evaluate_tool_step = eval_spy

        res = await agent._evaluate_tool_step(
            goal="Tra cứu thông thường",
            tool_name="get_current_time",
            tool_args={},
            tool_result="2026-10-01 12:00:00",
        )

        self.assertTrue(res["achieved"])
        self.assertEqual(res["status"], "SUCCESS")
        mock_llm.complete.assert_not_called()

    # ═════════════════════════════════════════════════════════════════════════
    # PART 4: BẤT BIẾN TRẠNG THÁI TERMINAL TRƯỚC STALE UPDATES (R1 & Persistence)
    # ═════════════════════════════════════════════════════════════════════════

    async def test_adv_13_invariance_cancelled_terminal_state_resists_stale_writes(self) -> None:
        # A task marked cancelled must NEVER accept stale updates transitioning back to active
        task_id = await self.worker.create_goal(
            goal="Cancelled invariance test",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "echo 1"}}],
        )

        cancel_ok = await self.worker.cancel_goal(task_id, reason="Official cancellation")
        self.assertTrue(cancel_ok)

        # Retrieve frozen cancelled record
        cancelled_record = await self.worker.get_goal_status(task_id)
        original_completed_at = cancelled_record["completed_at"]
        self.assertEqual(cancelled_record["status"], "cancelled")

        # Stale update attempt 1: Try to set status back to 'running'
        stale_running = dict(cancelled_record)
        stale_running["status"] = "running"
        stale_running["current_step"] = 1
        await self.worker._in_memory_store.update(stale_running)

        verify1 = await self.worker.get_goal_status(task_id)
        self.assertEqual(verify1["status"], "cancelled", "Cancelled state was overwritten by running!")
        self.assertEqual(verify1["error_message"], "Official cancellation")
        self.assertEqual(verify1["completed_at"], original_completed_at)

        # Stale update attempt 2: Try to set status to 'completed'
        stale_completed = dict(cancelled_record)
        stale_completed["status"] = "completed"
        await self.worker._in_memory_store.update(stale_completed)

        verify2 = await self.worker.get_goal_status(task_id)
        self.assertEqual(verify2["status"], "cancelled", "Cancelled state was overwritten by completed!")

    async def test_adv_14_invariance_completed_terminal_state_resists_stale_writes(self) -> None:
        # A completed task must never be regressed to running, pending, or failed
        task_id = await self.worker.create_goal(
            goal="Completed invariance test",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "echo 1"}}],
        )

        await self.worker.poll_once()
        completed_record = await self.worker.get_goal_status(task_id)
        self.assertEqual(completed_record["status"], "completed")
        comp_time = completed_record["completed_at"]

        # Attempt stale update back to pending
        stale_pending = dict(completed_record)
        stale_pending["status"] = "pending"
        stale_pending["error_message"] = "Fake error"
        await self.worker._in_memory_store.update(stale_pending)

        verify = await self.worker.get_goal_status(task_id)
        self.assertEqual(verify["status"], "completed")
        self.assertEqual(verify["completed_at"], comp_time)

        # Attempt to cancel completed goal via API
        cancel_attempt = await self.worker.cancel_goal(task_id, reason="Should not cancel")
        self.assertFalse(cancel_attempt)

    async def test_adv_15_concurrent_100_stale_updates_race_storm_on_terminal_task(self) -> None:
        # Fire 100 concurrent conflicting updates with random invalid statuses
        task_id = await self.worker.create_goal(
            goal="Stress terminal race task",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "echo 1"}}],
        )
        await self.worker.poll_once()

        task_record = await self.worker.get_goal_status(task_id)
        self.assertEqual(task_record["status"], "completed")

        async def _bad_update(idx: int):
            bad_copy = dict(task_record)
            bad_copy["status"] = "running" if idx % 2 == 0 else "pending"
            bad_copy["current_step"] = idx
            await self.worker._in_memory_store.update(bad_copy)

        update_tasks = [_bad_update(i) for i in range(100)]
        await asyncio.gather(*update_tasks)

        final_status = await self.worker.get_goal_status(task_id)
        self.assertEqual(final_status["status"], "completed", "Status corrupted during concurrent stale writes!")

    # ═════════════════════════════════════════════════════════════════════════
    # PART 5: RÒ RỈ TÀI NGUYÊN & AN TOÀN KHI DỪNG ĐỘT NGỘT STOP() (R1 Worker)
    # ═════════════════════════════════════════════════════════════════════════

    async def test_adv_16_rapid_start_stop_stress_cycles(self) -> None:
        # 25 rapid consecutive start_worker_loop() and stop() cycles
        for cycle in range(25):
            loop_task = self.worker.start_worker_loop()
            self.assertFalse(loop_task.done())
            self.assertTrue(self.worker._running)

            # Micro-wait before cancelling
            await asyncio.sleep(0.005)
            await self.worker.stop()

            self.assertFalse(self.worker._running)
            self.assertIsNone(self.worker._worker_task)
            self.assertTrue(loop_task.done())

    async def test_adv_17_abrupt_stop_during_long_running_io_step_execution(self) -> None:
        # Worker is halted abruptly while poll_once() is awaiting an extended tool command
        step_executing = asyncio.Event()

        async def _hanging_tool(*args, **kwargs):
            step_executing.set()
            await asyncio.sleep(5.0)
            return "Should not finish"

        self.mock_executor.execute_tool = AsyncMock(side_effect=_hanging_tool)

        await self.worker.create_goal(
            goal="Hanging tool goal",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "sleep 5"}}],
        )

        loop_task = self.worker.start_worker_loop()
        await step_executing.wait()

        # Stop worker with active hanging step
        start_stop = time.perf_counter()
        await self.worker.stop()
        stop_duration = time.perf_counter() - start_stop

        # Stop must terminate in under 5.0s timeout and reset state cleanly
        self.assertLess(stop_duration, 5.0)
        self.assertFalse(self.worker._running)
        self.assertIsNone(self.worker._worker_task)
        self.assertTrue(loop_task.done())

    async def test_adv_18_concurrent_multi_caller_stop_storm(self) -> None:
        # 20 coroutines call worker.stop() at the same instant
        self.worker.start_worker_loop()
        await asyncio.sleep(0.01)

        stop_tasks = [self.worker.stop() for _ in range(20)]
        await asyncio.gather(*stop_tasks)

        self.assertFalse(self.worker._running)
        self.assertIsNone(self.worker._worker_task)


if __name__ == "__main__":
    unittest.main()
