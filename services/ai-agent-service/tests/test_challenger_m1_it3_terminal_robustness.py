"""
Empirical Challenger Test Suite: Milestone 1 Iteration 3
Terminal States Robustness & Adversarial Concurrency Harness.

Author: Challenger 1 (Milestone 1 Iteration 3)
Verification Scope:
1. Terminal State Guard Matrix (cancelled, failed, waiting_approval).
2. Thundering Herd Concurrent Cancellation (Race Conditions).
3. Phantom Completion Notification Elimination on Late Cancel.
4. Error Message and Completed_at Nullification Immunization.
5. Extreme Exception Fuzzing and Batch Polling Resilience.
6. Empirical Verification of Adversarial Edge Cases.
"""

import asyncio
from datetime import datetime, timezone
import json
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.autonomous_goal_worker import (
    AutonomousGoalWorker,
    InMemoryTaskStore,
)


class TestTerminalStatesRobustnessChallenger(unittest.IsolatedAsyncioTestCase):
    """Deep stress tests for terminal states robustness in AutonomousGoalWorker."""

    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Command output ok")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_challenger"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.mock_llm = MagicMock()
        self.mock_llm.complete = AsyncMock(return_value=None)

        self.store = InMemoryTaskStore()
        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_executor,
            telegram_bot=self.mock_telegram,
            llm_router=self.mock_llm,
            use_db=False,
            poll_interval_seconds=1,
        )
        self.worker._in_memory_store = self.store
        await self.worker.ensure_tables()

    # =========================================================================
    # 1. TERMINAL STATE GUARD MATRIX & NULLIFICATION IMMUNIZATION
    # =========================================================================

    async def test_terminal_state_guard_cross_overwrite_matrix(self) -> None:
        """
        Verify that guarded terminal states (cancelled, failed, waiting_approval)
        CANNOT be overwritten by stale updates or conflicting transitions.
        """
        task_id = "task_matrix_001"
        base_task = {
            "id": task_id,
            "goal": "Test matrix robustness",
            "steps": [{"step_id": 1, "tool": "run_command", "args": {"command": "echo 1"}}],
            "current_step": 0,
            "status": "cancelled",
            "error_message": "User initiated cancellation token #123",
            "completed_at": "2026-10-01T12:00:00Z",
            "retry_count": 0,
            "max_retries": 3,
        }
        await self.store.insert(base_task)

        # 1. Attempt to overwrite 'cancelled' with 'failed' (stale worker failure)
        stale_failed = dict(base_task)
        stale_failed["status"] = "failed"
        await self.store.update(stale_failed)

        curr = await self.store.get(task_id)
        self.assertEqual(curr["status"], "cancelled", "Cancelled task must NOT become failed!")

        # 2. Attempt to overwrite 'cancelled' with 'running' (stale worker resume)
        stale_running = dict(base_task)
        stale_running["status"] = "running"
        stale_running["error_message"] = None
        stale_running["completed_at"] = None
        await self.store.update(stale_running)

        curr = await self.store.get(task_id)
        self.assertEqual(curr["status"], "cancelled", "Cancelled task must NOT become running!")
        self.assertEqual(curr["error_message"], "User initiated cancellation token #123", "Error message must NOT be wiped by None!")
        self.assertEqual(curr["completed_at"], "2026-10-01T12:00:00Z", "completed_at must NOT be wiped by None!")

        # 3. Attempt to overwrite 'cancelled' with 'completed'
        stale_completed = dict(base_task)
        stale_completed["status"] = "completed"
        await self.store.update(stale_completed)

        curr = await self.store.get(task_id)
        self.assertEqual(curr["status"], "cancelled", "Cancelled task must NOT become completed!")

    async def test_failed_state_nullification_and_overwrite_protection(self) -> None:
        """
        Verify that a 'failed' task cannot be reverted to 'running' and its
        audit fields (error_message, completed_at) are preserved when updated with None.
        """
        task_id = "task_failed_002"
        task = {
            "id": task_id,
            "goal": "Test failed protection",
            "steps": [{"step_id": 1, "tool": "run_command", "args": {}}],
            "current_step": 1,
            "status": "failed",
            "error_message": "Kernel panic simulated: Out of Memory",
            "completed_at": "2026-10-01T13:00:00Z",
        }
        await self.store.insert(task)

        # Stale update sending status='running' and empty error_message
        stale_update = {
            "id": task_id,
            "status": "running",
            "error_message": None,
            "completed_at": None,
        }
        await self.store.update(stale_update)

        curr = await self.store.get(task_id)
        self.assertEqual(curr["status"], "failed")
        self.assertEqual(curr["error_message"], "Kernel panic simulated: Out of Memory")
        self.assertEqual(curr["completed_at"], "2026-10-01T13:00:00Z")

    async def test_waiting_approval_cannot_be_hijacked_by_worker(self) -> None:
        """
        Verify that a task in 'waiting_approval' cannot be set to 'running' or 'completed'
        by worker steps without explicit approval.
        """
        task_id = "task_tier3_003"
        task = {
            "id": task_id,
            "goal": "Tier 3 Lethal Task",
            "steps": [{"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf /"}}],
            "current_step": 0,
            "status": "waiting_approval",
            "error_message": "Action requires confirmation token (Tier 3 Lethal)",
        }
        await self.store.insert(task)

        # Worker step attempts to update to running
        stale_update = dict(task)
        stale_update["status"] = "running"
        await self.store.update(stale_update)

        curr = await self.store.get(task_id)
        self.assertEqual(curr["status"], "waiting_approval", "waiting_approval must NOT revert to running!")

    # =========================================================================
    # 2. CONCURRENT THUNDERING HERD CANCELLATION
    # =========================================================================

    async def test_stress_thundering_herd_concurrent_cancellation(self) -> None:
        """
        Stress-test: 20 concurrent coroutines attempting to cancel the exact same goal
        while a slow execution step is running in the background.
        Ensures thread/coroutine safety, no deadlock, and consistent terminal state.
        """
        async def slow_exec(tool, args, chat_id=None):
            await asyncio.sleep(0.08)
            return "Slow finish"

        self.mock_executor.execute_tool = AsyncMock(side_effect=slow_exec)

        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "slow_job_1"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "slow_job_2"}},
        ]
        task_id = await self.worker.create_goal(goal="Thundering herd cancel", steps=steps)

        # Launch background polling
        poll_future = asyncio.create_task(self.worker.poll_once())
        await asyncio.sleep(0.02)  # Let step 1 start

        # 20 concurrent cancel attempts with different reasons
        async def cancel_worker(idx: int):
            return await self.worker.cancel_goal(task_id, reason=f"Concurrent cancel request #{idx}")

        results = await asyncio.gather(*[cancel_worker(i) for i in range(20)])
        await poll_future

        # At least one cancellation must succeed
        self.assertTrue(any(results), "At least one cancellation coroutine must return True")

        # Verify final state is strictly cancelled
        final_task = await self.worker.get_goal_status(task_id)
        self.assertEqual(final_task["status"], "cancelled")
        self.assertIsNotNone(final_task["completed_at"])
        self.assertTrue(final_task["error_message"].startswith("Concurrent cancel request #"))

        # Subsequent poll must NOT run step 2
        count_after = await self.worker.poll_once()
        self.assertEqual(count_after, 0)
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)

    # =========================================================================
    # 3. PHANTOM COMPLETION NOTIFICATION ELIMINATION
    # =========================================================================

    async def test_stress_phantom_completion_notification_eliminated_on_late_cancel(self) -> None:
        """
        Adversarial Scenario:
        Task has 1 step.
        During step execution, cancel_goal is triggered.
        When step execution completes, worker checks persisted status before notifying.
        Because status is 'cancelled', Telegram completion notification MUST BE BLOCKED!
        """
        gate = asyncio.Event()

        async def gated_executor(tool, args, chat_id=None):
            await gate.wait()
            return "Final step execution done"

        self.mock_executor.execute_tool = AsyncMock(side_effect=gated_executor)

        steps = [{"step_id": 1, "tool": "run_command", "args": {"command": "echo done"}}]
        task_id = await self.worker.create_goal(goal="One-step goal late cancel", steps=steps)

        # Start poll
        poll_task = asyncio.create_task(self.worker.poll_once())
        await asyncio.sleep(0.02)

        # Cancel the goal while tool is still executing
        cancel_res = await self.worker.cancel_goal(task_id, reason="Late cancellation right before completion")
        self.assertTrue(cancel_res)

        # Release the gate so tool finishes
        gate.set()
        await poll_task

        # Verify task in store
        final_task = await self.worker.get_goal_status(task_id)
        self.assertEqual(final_task["status"], "cancelled")

        # Telegram bot must NOT have sent completion message ("Đã hoàn thành")
        for call in self.mock_telegram.send_message.call_args_list:
            msg_text = call[0][1]
            self.assertNotIn("Đã hoàn thành", msg_text, "PHANTOM NOTIFICATION DETECTED! Sent completion for cancelled task!")

    # =========================================================================
    # 4. EXTREME EXCEPTION FUZZING & BATCH POLL RESILIENCE
    # =========================================================================

    async def test_stress_extreme_exceptions_fuzzing(self) -> None:
        """
        Test resilience against unexpected exceptions:
        - MemoryError (standard fatal exception)
        - UnicodeDecodeError
        - RecursionError
        Worker must catch errors gracefully, increment retry_count, and isolate batches.
        """
        exceptions_to_test = [
            MemoryError("Simulated memory allocation failure"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
            RecursionError("Maximum recursion depth exceeded in sub-tool"),
        ]

        for exc in exceptions_to_test:
            with self.subTest(exc=type(exc).__name__):
                self.mock_executor.execute_tool = AsyncMock(side_effect=exc)
                t_id = await self.worker.create_goal(
                    goal=f"Fuzzing with {type(exc).__name__}",
                    steps=[{"step_id": 1, "tool": "run_command", "args": {}}],
                )

                # Poll 1
                await self.worker.poll_once()
                t1 = await self.worker.get_goal_status(t_id)
                self.assertEqual(t1["status"], "running")
                self.assertEqual(t1["retry_count"], 1)

                # Poll 2
                await self.worker.poll_once()
                t2 = await self.worker.get_goal_status(t_id)
                self.assertEqual(t2["retry_count"], 2)

                # Poll 3 -> transition to failed
                await self.worker.poll_once()
                t3 = await self.worker.get_goal_status(t_id)
                self.assertEqual(t3["status"], "failed")
                self.assertEqual(t3["retry_count"], 3)
                self.assertIsNotNone(t3["completed_at"])

    async def test_stress_large_output_payload_and_step_volume(self) -> None:
        """
        Stress test with 10-step goal and large 100KB command output payloads.
        Verifies memory store and serialization stability.
        """
        large_payload = "A" * (100 * 1024)  # 100 KB text
        self.mock_executor.execute_tool = AsyncMock(return_value=large_payload)

        steps = [
            {"step_id": i + 1, "tool": "run_command", "args": {"command": f"echo payload_{i}"}}
            for i in range(10)
        ]
        task_id = await self.worker.create_goal(goal="Large volume 10 steps", steps=steps)

        for step_idx in range(10):
            p = await self.worker.poll_once()
            self.assertEqual(p, 1)
            status_snap = await self.worker.get_goal_status(task_id)
            if step_idx < 9:
                self.assertEqual(status_snap["status"], "running")
                self.assertEqual(status_snap["current_step"], step_idx + 1)
            else:
                self.assertEqual(status_snap["status"], "completed")
                self.assertEqual(status_snap["current_step"], 10)

        final_task = await self.worker.get_goal_status(task_id)
        self.assertEqual(final_task["status"], "completed")
        self.assertEqual(len(final_task["steps"]), 10)
        for s in final_task["steps"]:
            self.assertEqual(s["status"], "completed")
            self.assertEqual(len(s["result"]), 100 * 1024)

    # =========================================================================
    # 5. WAITING_APPROVAL CANCELLATION & COMPLETED PROTECTION VERIFICATION
    # =========================================================================

    async def test_waiting_approval_can_be_cancelled_with_reason(self) -> None:
        """
        Verify that a task trapped in 'waiting_approval' can be successfully cancelled
        via cancel_goal() and the cancellation reason is properly retained.
        """
        task_id = "task_waiting_cancel_001"
        task = {
            "id": task_id,
            "goal": "Lethal action requiring approval",
            "steps": [{"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf /tmp"}}],
            "current_step": 0,
            "status": "waiting_approval",
            "error_message": "Action run_command requires confirmation token (Tier 3 Lethal)",
            "completed_at": None,
        }
        await self.store.insert(task)

        # Cancel the task
        success = await self.worker.cancel_goal(task_id, reason="Admin rejected execution token")
        self.assertTrue(success, "cancel_goal must succeed for waiting_approval task")

        updated = await self.worker.get_goal_status(task_id)
        self.assertEqual(updated["status"], "cancelled")
        self.assertEqual(updated["error_message"], "Admin rejected execution token")
        self.assertIsNotNone(updated["completed_at"])

    async def test_completed_task_protected_against_stale_running_and_failed(self) -> None:
        """
        Verify that a completed task cannot be downgraded to 'running' or 'failed'
        and that stale failure messages do not contaminate the completed state.
        """
        task_id = "task_completed_protect_002"
        task = {
            "id": task_id,
            "goal": "Finished task",
            "steps": [{"step_id": 1, "tool": "run_command", "args": {}}],
            "current_step": 1,
            "status": "completed",
            "error_message": None,
            "completed_at": "2026-10-01T12:00:00Z",
        }
        await self.store.insert(task)

        # 1. Stale running update
        stale_running = dict(task)
        stale_running["status"] = "running"
        await self.store.update(stale_running)

        cur = await self.store.get(task_id)
        self.assertEqual(cur["status"], "completed")
        self.assertEqual(cur["completed_at"], "2026-10-01T12:00:00Z")

        # 2. Stale failed update
        stale_failed = dict(task)
        stale_failed["status"] = "failed"
        stale_failed["error_message"] = "Delayed network error"
        stale_failed["completed_at"] = "2026-10-01T13:00:00Z"
        await self.store.update(stale_failed)

        cur = await self.store.get(task_id)
        self.assertEqual(cur["status"], "completed")
        self.assertIsNone(cur["error_message"], "Completed task error_message must not be contaminated")
        self.assertEqual(cur["completed_at"], "2026-10-01T12:00:00Z")

    async def test_sql_upsert_logic_empirical_simulation(self) -> None:
        """
        Empirically simulate the exact PostgreSQL ON CONFLICT DO UPDATE CASE WHEN statement
        using SQLite in-memory to prove database-level state machine correctness.
        """
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE agent_tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                error_message TEXT,
                completed_at TEXT
            );
        """)

        upsert_query = """
        INSERT INTO agent_tasks (id, status, error_message, completed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            status = CASE 
                WHEN agent_tasks.status IN ('cancelled', 'completed') THEN agent_tasks.status 
                WHEN agent_tasks.status = 'failed' AND EXCLUDED.status != 'cancelled' THEN agent_tasks.status 
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') THEN agent_tasks.status 
                ELSE EXCLUDED.status 
            END,
            error_message = CASE
                WHEN agent_tasks.status = 'completed' THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'cancelled' AND agent_tasks.error_message IS NOT NULL THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'failed' AND agent_tasks.error_message IS NOT NULL AND EXCLUDED.status != 'cancelled' THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') AND agent_tasks.error_message IS NOT NULL THEN agent_tasks.error_message
                ELSE EXCLUDED.error_message
            END,
            completed_at = CASE
                WHEN agent_tasks.status IN ('cancelled', 'completed') AND agent_tasks.completed_at IS NOT NULL THEN agent_tasks.completed_at
                WHEN agent_tasks.status = 'failed' AND agent_tasks.completed_at IS NOT NULL AND EXCLUDED.status != 'cancelled' THEN agent_tasks.completed_at
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') AND agent_tasks.completed_at IS NOT NULL THEN agent_tasks.completed_at
                ELSE EXCLUDED.completed_at
            END;
        """

        # Scenario A: waiting_approval cancelled by user/admin
        cur.execute("INSERT INTO agent_tasks VALUES ('task_A', 'waiting_approval', 'Token required', NULL)")
        cur.execute(upsert_query, ('task_A', 'cancelled', 'User cancelled via UI', '2026-10-01T14:00:00Z'))
        res_a = cur.execute("SELECT status, error_message, completed_at FROM agent_tasks WHERE id = 'task_A'").fetchone()
        self.assertEqual(res_a[0], "cancelled")
        self.assertEqual(res_a[1], "User cancelled via UI")
        self.assertEqual(res_a[2], "2026-10-01T14:00:00Z")

        # Scenario B: waiting_approval stale update to running (must be rejected)
        cur.execute("INSERT INTO agent_tasks VALUES ('task_B', 'waiting_approval', 'Token required', NULL)")
        cur.execute(upsert_query, ('task_B', 'running', None, None))
        res_b = cur.execute("SELECT status, error_message, completed_at FROM agent_tasks WHERE id = 'task_B'").fetchone()
        self.assertEqual(res_b[0], "waiting_approval")
        self.assertEqual(res_b[1], "Token required")
        self.assertIsNone(res_b[2])

        # Scenario C: completed task with stale update to failed (must be rejected and clean)
        cur.execute("INSERT INTO agent_tasks VALUES ('task_C', 'completed', NULL, '2026-10-01T12:00:00Z')")
        cur.execute(upsert_query, ('task_C', 'failed', 'Stale timeout error', '2026-10-01T13:00:00Z'))
        res_c = cur.execute("SELECT status, error_message, completed_at FROM agent_tasks WHERE id = 'task_C'").fetchone()
        self.assertEqual(res_c[0], "completed")
        self.assertIsNone(res_c[1])
        self.assertEqual(res_c[2], "2026-10-01T12:00:00Z")

        # Scenario D: cancelled task with stale update to failed (must stay cancelled)
        cur.execute("INSERT INTO agent_tasks VALUES ('task_D', 'cancelled', 'Cancel reason', '2026-10-01T11:00:00Z')")
        cur.execute(upsert_query, ('task_D', 'failed', 'Stale tool failure', '2026-10-01T11:05:00Z'))
        res_d = cur.execute("SELECT status, error_message, completed_at FROM agent_tasks WHERE id = 'task_D'").fetchone()
        self.assertEqual(res_d[0], "cancelled")
        self.assertEqual(res_d[1], "Cancel reason")
        self.assertEqual(res_d[2], "2026-10-01T11:00:00Z")

        conn.close()

    async def test_empty_steps_no_phantom_notification_if_pre_cancelled(self) -> None:
        """
        Verify that if a task with empty steps is cancelled in store before execution
        checks persisted status, _notify_completion is NOT invoked.
        """
        task_id = "task_empty_pre_cancelled"
        task = {
            "id": task_id,
            "goal": "Empty steps goal",
            "steps": [],
            "current_step": 0,
            "status": "pending",
        }
        await self.store.insert(task)

        # Cancel the task in the store
        await self.worker.cancel_goal(task_id, reason="Cancelled prior to empty steps completion")

        # Now execute pending step on task_record that thought it was pending
        task_record = {
            "id": task_id,
            "goal": "Empty steps goal",
            "steps": [],
            "current_step": 0,
            "status": "pending",
        }
        res = await self.worker.execute_pending_step(task_record)

        self.assertEqual(res["status"], "cancelled")
        # Ensure telegram completion notification was not sent
        for call in self.mock_telegram.send_message.call_args_list:
            msg_text = call[0][1]
            self.assertNotIn("Đã hoàn thành", msg_text)


if __name__ == "__main__":
    unittest.main()
