"""
Empirical Verification & Stress Test Suite for Milestone 1: Autonomous Goal Engine (R1).

Conducted by Challenger 2 (Empirical Challenger):
- SECTION A: Spinal Safety Gating verification (Strict interception of Tier 3 Lethal actions -> waiting_approval, 0 execution, Telegram alerts).
- SECTION B: Concurrency & Stress Harness (Massive concurrent goal creation, race conditions, mixed workload batch resolution, and atomic cancellation).
"""

import asyncio
import html
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.services.autonomous_goal_worker import AutonomousGoalWorker, InMemoryTaskStore
from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
)


class TestSpinalSafetyGatingEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial verification of Spinal Safety Gating:
    Ensures absolute zero bypass for Tier 3 Lethal operations.
    """

    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Output: Success")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_99"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_executor,
            telegram_bot=self.mock_telegram,
            use_db=False,
            poll_interval_seconds=1,
        )
        await self.worker.ensure_tables()

    async def test_01_all_tier3_lethal_commands_blocked_at_spinal_gate(self) -> None:
        """
        Comprehensive test matrix of Tier 3 Lethal commands:
        Verify every single lethal command triggers waiting_approval and NEVER calls tool_executor.
        """
        lethal_commands = [
            "rm -rf /",
            "rm -fr /",
            "rm -rf /*",
            "rm -rf .",
            "rm -rf ~",
            "rm --recursive --force /",
            "rm -rf --no-preserve-root /",
            "mkfs.ext4 /dev/sda1",
            "mkfs /dev/sdb",
            "dd if=/dev/zero of=/dev/sda",
            "> /dev/sda",
            "drop table users",
            "drop database test_db",
            "truncate table orders",
            "truncate users;",
            "docker system prune -a -f",
            "docker rm -f $(docker ps -aq)",
            "docker kill `docker ps -q`",
            "iptables -F",
            "ufw reset",
            "ufw disable",
            "ip link set eth0 down",
            "chmod -R 777 /",
            "chmod 777 -R /var",
            "chown -R nobody /etc",
            "systemctl stop sshd",
            "systemctl disable ssh",
            "rm -rf ~/.ssh",
            "rm -f /root/.ssh/authorized_keys",
            "> ~/.ssh/authorized_keys",
            "truncate -s 0 /var/log/syslog",
            ":(){ :|:& };:",
            "find / -delete",
        ]

        for idx, cmd in enumerate(lethal_commands):
            with self.subTest(command=cmd):
                self.mock_executor.execute_tool.reset_mock()
                self.mock_telegram.send_message.reset_mock()

                risk = classify_command_risk(cmd)
                self.assertEqual(
                    risk,
                    ACTION_TIER_3_LETHAL,
                    f"Command '{cmd}' must be classified as ACTION_TIER_3_LETHAL, got '{risk}'",
                )

                task_id = await self.worker.create_goal(
                    goal=f"Test lethal command {idx}",
                    steps=[{"step_id": 1, "tool": "run_command", "args": {"command": cmd}}],
                    chat_id="test_chat_99",
                )
                task_record = await self.worker.get_goal_status(task_id)

                res = await self.worker.execute_pending_step(task_record)

                # Tool executor MUST NEVER be called
                self.mock_executor.execute_tool.assert_not_awaited()

                # Status must be waiting_approval
                self.assertEqual(res["status"], "waiting_approval")
                self.assertEqual(res["current_step"], 0)
                self.assertIn("Tier 3 Lethal", res["error_message"])

                # Telegram alert must be triggered
                self.mock_telegram.send_message.assert_awaited()
                call_args = self.mock_telegram.send_message.call_args[0]
                self.assertEqual(call_args[0], "test_chat_99")
                self.assertIn("CẢNH BÁO AN TOÀN VI MẠCH (Tier 3 Lethal Action)", call_args[1])
                self.assertTrue(
                    cmd in call_args[1] or html.escape(cmd) in call_args[1] or cmd in html.unescape(call_args[1]),
                    f"Expected command {cmd} to be in telegram notification: {call_args[1]}"
                )

    async def test_02_obfuscated_and_chained_lethal_commands_blocked(self) -> None:
        """
        Adversarial attack scenarios:
        Attempting to smuggle Tier 3 lethal commands through chaining (&&, ;, ||, |) or casing/spacing.
        """
        smuggle_commands = [
            "echo 'hello' && rm -rf /",
            "ls -la ; rm -rf /",
            "uptime | rm -rf /",
            "false || rm -rf /",
            "   RM   -RF   /   ",
            "sudo rm -rf /",
            "echo 123; mkfs.ext4 /dev/sda",
            "cat /dev/null && docker system prune -a",
            "find /tmp -type f && truncate -s 0 /var/log/syslog",
        ]

        for cmd in smuggle_commands:
            with self.subTest(smuggle_cmd=cmd):
                self.mock_executor.execute_tool.reset_mock()
                self.mock_telegram.send_message.reset_mock()

                risk = classify_command_risk(cmd)
                self.assertEqual(
                    risk,
                    ACTION_TIER_3_LETHAL,
                    f"Smuggled command '{cmd}' failed to be caught as ACTION_TIER_3_LETHAL",
                )

                task_id = await self.worker.create_goal(
                    goal=f"Smuggle test: {cmd}",
                    steps=[{"step_id": 1, "tool": "run_command", "args": {"command": cmd}}],
                )
                task_record = await self.worker.get_goal_status(task_id)
                res = await self.worker.execute_pending_step(task_record)

                self.mock_executor.execute_tool.assert_not_awaited()
                self.assertEqual(res["status"], "waiting_approval")

    async def test_03_execute_system_script_safety_gating(self) -> None:
        """
        Verifies execute_system_script risk classification and execution gating.
        - Dangerous script without confirmation -> Tier 3 Lethal, blocked.
        - Dangerous script with CONFIRM_DANGEROUS_ACTION -> Tier 2 Reversible, allowed.
        """
        # 1. Unconfirmed lethal script
        task_id = await self.worker.create_goal(
            goal="Execute dangerous system script unconfirmed",
            steps=[{
                "step_id": 1,
                "tool": "execute_system_script",
                "args": {"script_code": "rm -rf /", "confirm": ""},
            }],
        )
        task = await self.worker.get_goal_status(task_id)
        res = await self.worker.execute_pending_step(task)

        self.mock_executor.execute_tool.assert_not_awaited()
        self.assertEqual(res["status"], "waiting_approval")

        # 2. Confirmed dangerous script
        self.mock_executor.execute_tool.reset_mock()
        task_id_confirmed = await self.worker.create_goal(
            goal="Execute dangerous system script confirmed",
            steps=[{
                "step_id": 1,
                "tool": "execute_system_script",
                "args": {"script_code": "rm -rf /", "confirm": "CONFIRM_DANGEROUS_ACTION"},
            }],
        )
        task_conf = await self.worker.get_goal_status(task_id_confirmed)
        res_conf = await self.worker.execute_pending_step(task_conf)

        self.mock_executor.execute_tool.assert_awaited_once()
        self.assertEqual(res_conf["status"], "completed")

    async def test_04_multi_step_containment_boundary(self) -> None:
        """
        Ensures that in a multi-step goal:
        - Step 1 (Safe) executes successfully.
        - Step 2 (Lethal) is intercepted immediately.
        - Step 3 (Safe) is NEVER reached.
        - current_step stays anchored at 1.
        - Subsequent poll_once calls DO NOT re-execute or bypass Step 2.
        """
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "rm -rf /"}},
            {"step_id": 3, "tool": "run_command", "args": {"command": "uptime"}},
        ]
        task_id = await self.worker.create_goal(goal="Sandwich lethal step", steps=steps)
        task = await self.worker.get_goal_status(task_id)

        # Execute Step 1 (Safe)
        res1 = await self.worker.execute_pending_step(task)
        self.assertEqual(res1["status"], "running")
        self.assertEqual(res1["current_step"], 1)
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)

        # Execute Step 2 (Lethal) -> Halt
        res2 = await self.worker.execute_pending_step(res1)
        self.assertEqual(res2["status"], "waiting_approval")
        self.assertEqual(res2["current_step"], 1)
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)  # Still 1, NOT incremented

        # Subsequent attempts via poll_once or execute_pending_step must do nothing
        processed = await self.worker.poll_once()
        self.assertEqual(processed, 0)

        res3 = await self.worker.execute_pending_step(res2)
        self.assertEqual(res3["status"], "waiting_approval")
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)

    async def test_05_safe_tier1_and_tier2_commands_execute_freely(self) -> None:
        """
        Ensures Spinal Safety Gating DOES NOT falsely flag safe commands (False Positive check).
        """
        safe_commands = [
            ("free -m", ACTION_TIER_1_SAFE),
            ("df -h", ACTION_TIER_1_SAFE),
            ("uptime", ACTION_TIER_1_SAFE),
            ("docker ps", ACTION_TIER_1_SAFE),
            ("journalctl -n 20", ACTION_TIER_1_SAFE),
            ("docker restart nginx", ACTION_TIER_2_REVERSIBLE),
            ("touch /tmp/marker.txt", ACTION_TIER_2_REVERSIBLE),
            ("mkdir -p /tmp/backup", ACTION_TIER_2_REVERSIBLE),
        ]

        for cmd, expected_tier in safe_commands:
            with self.subTest(command=cmd):
                self.mock_executor.execute_tool.reset_mock()
                risk = classify_command_risk(cmd)
                self.assertEqual(risk, expected_tier)

                task_id = await self.worker.create_goal(
                    goal=f"Run {cmd}",
                    steps=[{"step_id": 1, "tool": "run_command", "args": {"command": cmd}}],
                )
                task = await self.worker.get_goal_status(task_id)
                res = await self.worker.execute_pending_step(task)

                self.mock_executor.execute_tool.assert_awaited_once()
                self.assertEqual(res["status"], "completed")


class TestConcurrencyAndStressHarness(unittest.IsolatedAsyncioTestCase):
    """
    Stress-testing concurrency, throughput, race conditions, and mixed-workload resilience.
    """

    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        # Simulated variable network latency between 1ms and 5ms
        async def mock_exec(tool, args, **kwargs):
            await asyncio.sleep(0.002)
            if tool == "fail_tool":
                raise RuntimeError("Service temporarily unavailable")
            return f"Success: {tool}"

        self.mock_executor.execute_tool = AsyncMock(side_effect=mock_exec)

        self.mock_telegram = MagicMock()
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_executor,
            telegram_bot=self.mock_telegram,
            use_db=False,
            poll_interval_seconds=1,
        )
        await self.worker.ensure_tables()

    async def test_06_high_volume_concurrent_goal_creation(self) -> None:
        """
        Stress test: 100 goals created concurrently via asyncio.gather.
        Verifies:
        - 100 unique UUID task IDs.
        - Zero collisions.
        - Thread-safe / coroutine-safe in-memory task registration.
        """
        num_goals = 100
        start_time = time.perf_counter()

        tasks = [
            self.worker.create_goal(
                goal=f"Concurrent Goal #{i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "uptime"}}],
            )
            for i in range(num_goals)
        ]

        task_ids = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start_time

        self.assertEqual(len(task_ids), num_goals)
        self.assertEqual(len(set(task_ids)), num_goals, "All task IDs must be strictly unique!")
        self.assertLess(elapsed, 2.0, f"Creating 100 goals took {elapsed:.2f}s, expected < 2.0s")

        all_stored = await self.worker.list_goals(limit=200)
        self.assertEqual(len(all_stored), num_goals)

    async def test_07_concurrent_poll_lock_mutual_exclusion(self) -> None:
        """
        Verifies that multiple concurrent calls to poll_once() serialize cleanly via _poll_lock
        without duplicate execution of the same task step.
        """
        # Create 5 pending tasks
        for i in range(5):
            await self.worker.create_goal(
                goal=f"Batch task {i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "uptime"}}],
            )

        # Launch 5 poll_once calls concurrently
        poll_results = await asyncio.gather(
            self.worker.poll_once(),
            self.worker.poll_once(),
            self.worker.poll_once(),
            self.worker.poll_once(),
            self.worker.poll_once(),
        )

        total_processed = sum(poll_results)
        self.assertEqual(total_processed, 5, "Exactly 5 tasks should have been processed across all concurrent polls")

        # Verify all tasks are completed
        completed = await self.worker.list_goals(status="completed")
        self.assertEqual(len(completed), 5)
        # Ensure execute_tool was called exactly 5 times, NOT duplicated
        self.assertEqual(self.mock_executor.execute_tool.await_count, 5)

    async def test_08_mixed_workload_heterogeneous_stress(self) -> None:
        """
        Stress test with 80 mixed goals under continuous poll cycles:
        - 40 Single-step Tier 1 Safe goals.
        - 20 Multi-step (2 steps) Tier 1 Safe goals.
        - 10 Tier 3 Lethal goals.
        - 10 Failing goals (reaching max_retries = 3).
        Total: 80 goals.
        """
        # 1. 40 Single-step safe
        for i in range(40):
            await self.worker.create_goal(
                goal=f"Safe Goal Single {i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}}],
            )

        # 2. 20 Multi-step safe (2 steps)
        for i in range(20):
            await self.worker.create_goal(
                goal=f"Safe Goal Multi {i}",
                steps=[
                    {"step_id": 1, "tool": "run_command", "args": {"command": "free -m"}},
                    {"step_id": 2, "tool": "run_command", "args": {"command": "uptime"}},
                ],
            )

        # 3. 10 Tier 3 Lethal
        for i in range(10):
            await self.worker.create_goal(
                goal=f"Lethal Goal {i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf /"}}],
            )

        # 4. 10 Failing goals
        for i in range(10):
            await self.worker.create_goal(
                goal=f"Failing Goal {i}",
                steps=[{"step_id": 1, "tool": "fail_tool", "args": {}}],
            )

        # Run poll cycles until no more active tasks remain
        cycles = 0
        max_cycles = 50
        while cycles < max_cycles:
            cycles += 1
            processed = await self.worker.poll_once()
            if processed == 0:
                break

        # Verification of final states
        completed_tasks = await self.worker.list_goals(status="completed", limit=100)
        waiting_tasks = await self.worker.list_goals(status="waiting_approval", limit=100)
        failed_tasks = await self.worker.list_goals(status="failed", limit=100)
        pending_tasks = await self.worker.list_goals(status="pending", limit=100)
        running_tasks = await self.worker.list_goals(status="running", limit=100)

        self.assertEqual(len(pending_tasks), 0, "No tasks should remain pending")
        self.assertEqual(len(running_tasks), 0, "No tasks should remain running")

        self.assertEqual(len(completed_tasks), 60, "Expected 60 completed tasks (40 single + 20 multi)")
        self.assertEqual(len(waiting_tasks), 10, "Expected 10 waiting_approval lethal tasks")
        self.assertEqual(len(failed_tasks), 10, "Expected 10 failed tasks")

        # Check lethal tasks never called tool_executor
        for task in waiting_tasks:
            self.assertEqual(task["current_step"], 0)
            self.assertIn("Tier 3 Lethal", task["error_message"])

        # Check failed tasks reached max_retries = 3
        for task in failed_tasks:
            self.assertEqual(task["retry_count"], 3)

        # Total expected successful tool calls: 40 (single) + 20*2 (multi) = 80 successful tool calls
        # Plus 10*3 = 30 failed tool calls = 110 total calls
        self.assertEqual(self.mock_executor.execute_tool.await_count, 110)

    async def test_09_concurrent_cancellation_during_execution(self) -> None:
        """
        Tests cancellation safety under concurrent activity:
        Tasks cancelled mid-flight must transition to 'cancelled' and cease progression.
        """
        task_ids = []
        for i in range(10):
            tid = await self.worker.create_goal(
                goal=f"Cancellable Goal {i}",
                steps=[
                    {"step_id": 1, "tool": "run_command", "args": {"command": "uptime"}},
                    {"step_id": 2, "tool": "run_command", "args": {"command": "free -m"}},
                ],
            )
            task_ids.append(tid)

        # Advance step 1 for all tasks
        await self.worker.poll_once()

        # Cancel half of them concurrently
        cancel_futures = [self.worker.cancel_goal(task_ids[i], reason=f"Aborted #{i}") for i in range(5)]
        results = await asyncio.gather(*cancel_futures)
        self.assertTrue(all(results))

        # Advance next cycle
        await self.worker.poll_once()

        # Check cancelled tasks
        for i in range(5):
            st = await self.worker.get_goal_status(task_ids[i])
            self.assertEqual(st["status"], "cancelled")
            self.assertEqual(st["current_step"], 1, "Cancelled tasks should NOT advance to step 2")

        # Check remaining tasks completed
        for i in range(5, 10):
            st = await self.worker.get_goal_status(task_ids[i])
            self.assertEqual(st["status"], "completed")
            self.assertEqual(st["current_step"], 2)


class TestAdversarialSpinalSafetyEdgeCases(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial edge-case mining and boundary testing:
    Tests malformed payloads, injection vectors, fault injection (Telegram failure),
    and extreme load scalability.
    """

    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Command executed successfully")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_edge"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.worker = AutonomousGoalWorker(
            tool_executor=self.mock_executor,
            telegram_bot=self.mock_telegram,
            use_db=False,
            poll_interval_seconds=1,
        )
        await self.worker.ensure_tables()

    async def test_10_empty_and_malformed_tool_args_safety(self) -> None:
        """
        Verify system gracefully handles empty, None, and unexpected tool arguments
        without unhandled crashes.
        """
        malformed_steps = [
            {"step_id": 1, "tool": "run_command", "args": {}},
            {"step_id": 2, "tool": "run_command", "args": None},
            {"step_id": 3, "tool": "run_command", "args": {"command": ""}},
            {"step_id": 4, "tool": "unknown_tool", "args": {"foo": "bar"}},
            {"step_id": 5, "command": "uptime"},  # Implicit tool_name inference
        ]

        for s in malformed_steps:
            with self.subTest(step=s):
                tid = await self.worker.create_goal(goal="Malformed step", steps=[s])
                task = await self.worker.get_goal_status(tid)
                res = await self.worker.execute_pending_step(task)
                self.assertIn(res["status"], ("completed", "running", "failed", "waiting_approval"))

    async def test_11_newline_and_command_substitution_injection(self) -> None:
        """
        Verify dangerous commands hidden inside command substitutions or newlines are neutralized.
        """
        injections = [
            "echo 1\nrm -rf /",
            "echo $(rm -rf /)",
            "echo `rm -rf /`",
            "eval 'rm -rf /'",
            "sh -c 'rm -rf /'",
            "bash -c 'rm -rf /'",
        ]

        for inj in injections:
            with self.subTest(injection=inj):
                risk = classify_command_risk(inj)
                self.assertEqual(risk, ACTION_TIER_3_LETHAL, f"Injection '{inj}' bypassed risk classifier!")

                tid = await self.worker.create_goal(
                    goal=f"Injection: {inj}",
                    steps=[{"step_id": 1, "tool": "run_command", "args": {"command": inj}}],
                )
                task = await self.worker.get_goal_status(tid)
                res = await self.worker.execute_pending_step(task)

                self.assertEqual(res["status"], "waiting_approval")
                self.mock_executor.execute_tool.assert_not_awaited()

    async def test_12_goal_with_empty_steps_transitions_completed(self) -> None:
        """A goal created with 0 steps transitions cleanly to completed upon execution."""
        tid = await self.worker.create_goal(goal="Empty steps goal", steps=[])
        task = await self.worker.get_goal_status(tid)

        res = await self.worker.execute_pending_step(task)
        self.assertEqual(res["status"], "completed")
        self.assertIsNotNone(res["completed_at"])

    async def test_13_telegram_failure_does_not_unblock_tier3(self) -> None:
        """
        Fault Injection: Even if Telegram notification fails or times out,
        the task MUST REMAIN strictly halted in 'waiting_approval' (Fail-Safe Principle).
        """
        self.mock_telegram.send_message = AsyncMock(side_effect=RuntimeError("Telegram network timeout"))

        tid = await self.worker.create_goal(
            goal="Lethal with broken telegram",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf /"}}],
        )
        task = await self.worker.get_goal_status(tid)
        res = await self.worker.execute_pending_step(task)

        # Still waiting_approval, never executed!
        self.assertEqual(res["status"], "waiting_approval")
        self.mock_executor.execute_tool.assert_not_awaited()

    async def test_14_rapid_concurrency_high_payload(self) -> None:
        """
        High concurrency scale test: 200 goals generated simultaneously with large goal descriptions.
        """
        num_goals = 200
        large_desc = "Khảo sát và tối ưu máy chủ Ubuntu " + ("X" * 500)
        start_t = time.perf_counter()

        tasks = [
            self.worker.create_goal(
                goal=f"{large_desc} #{i}",
                steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "uptime"}}],
            )
            for i in range(num_goals)
        ]
        tids = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start_t

        self.assertEqual(len(tids), num_goals)
        self.assertEqual(len(set(tids)), num_goals)
        self.assertLess(elapsed, 3.0, f"Creating 200 goals took {elapsed:.2f}s, expected < 3.0s")


if __name__ == "__main__":
    unittest.main()
