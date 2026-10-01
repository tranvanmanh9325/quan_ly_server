"""
Adversarial Stress Test Suite for AutonomousGoalWorker (Milestone 1 - R1).
Challenger 1 Verification Harness.

Stress-tests:
1. Goal cancellation mid-execution and race condition detection (cancel_goal).
2. Non-standard and unhandled exceptions handling, retry resilience, and loop isolation.
3. Zero State Loss: 5-step goal, 2 steps completed, worker restart, resume from step 3 to completion.
4. Transient failure recovery (step fails twice then succeeds on 3rd attempt).
5. Cancellation of Tier 3 lethal waiting_approval task.
"""

import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.autonomous_goal_worker import AutonomousGoalWorker, InMemoryTaskStore


class TestAutonomousGoalWorkerStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress and verification tests for AutonomousGoalWorker."""

    async def asyncSetUp(self) -> None:
        self.mock_executor = MagicMock()
        self.mock_executor.execute_tool = AsyncMock(return_value="Command output ok")

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_99"
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
    # PART 1: CANCEL GOAL STRESS TESTS
    # =========================================================================

    async def test_stress_cancel_mid_execution_prevents_subsequent_steps(self) -> None:
        """
        Kịch bản 1.1: Hủy goal ở giữa các bước.
        Tạo goal 4 bước. Thực thi bước 1 thành công (current_step=1, status=running).
        Người dùng gọi cancel_goal().
        Kiểm tra:
        - Task chuyển thành status='cancelled'.
        - Thực hiện nhiều chu kỳ polling tiếp theo.
        - Worker TUYỆT ĐỐI KHÔNG chạy tiếp các bước 2, 3, 4.
        - execute_tool chỉ được gọi đúng 1 lần (cho bước 1).
        """
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "echo step1"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "echo step2"}},
            {"step_id": 3, "tool": "run_command", "args": {"command": "echo step3"}},
            {"step_id": 4, "tool": "run_command", "args": {"command": "echo step4"}},
        ]
        task_id = await self.worker.create_goal(goal="Goal 4 bước cần hủy giữa chừng", steps=steps)

        # Chạy bước 1 qua poll_once
        processed = await self.worker.poll_once()
        self.assertEqual(processed, 1)

        task_after_step1 = await self.worker.get_goal_status(task_id)
        self.assertEqual(task_after_step1["status"], "running")
        self.assertEqual(task_after_step1["current_step"], 1)
        self.assertEqual(self.mock_executor.execute_tool.await_count, 1)

        # Người dùng hủy goal
        cancel_success = await self.worker.cancel_goal(task_id, reason="User cancelled after step 1")
        self.assertTrue(cancel_success)

        task_cancelled = await self.worker.get_goal_status(task_id)
        self.assertEqual(task_cancelled["status"], "cancelled")
        self.assertEqual(task_cancelled["error_message"], "User cancelled after step 1")
        self.assertIsNotNone(task_cancelled["completed_at"])

        # Kích hoạt 5 chu kỳ poll_once liên tiếp
        for _ in range(5):
            count = await self.worker.poll_once()
            self.assertEqual(count, 0, "Cancelled task must NOT be picked up by poll_once!")

        # Kích hoạt trực tiếp execute_pending_step với task record cũ
        direct_res = await self.worker.execute_pending_step(task_cancelled)
        self.assertEqual(direct_res["status"], "cancelled")

        # Đảm bảo execute_tool vẫn CHỈ được gọi đúng 1 lần duy nhất từ bước 1
        self.assertEqual(
            self.mock_executor.execute_tool.await_count,
            1,
            "Tool executor must not be called after task cancellation!",
        )

        # Trạng thái cuối cùng trong store vẫn phải là cancelled
        final_task = await self.worker.get_goal_status(task_id)
        self.assertEqual(final_task["status"], "cancelled")
        self.assertEqual(final_task["current_step"], 1)

    async def test_stress_cancel_during_active_step_execution_race_condition(self) -> None:
        """
        Kịch bản 1.2: Stress-test Race Condition khi cancel_goal xảy ra TRONG KHI tool đang thực thi.
        Mô phỏng tool_executor chạy mất một khoảng thời gian (asyncio.sleep).
        Trong lúc đó, cancel_goal được gọi.
        Kiểm tra xem sau khi execute_tool kết thúc:
        - Có bị ghi đè trạng thái 'cancelled' thành 'running' / 'completed' hay không?
        - Nếu có cơ chế kiểm tra trước khi save, status phải là 'cancelled'.
        """
        async def slow_execute(tool_name, tool_args, chat_id=None):
            await asyncio.sleep(0.05)
            return "Slow command finished"

        self.mock_executor.execute_tool = AsyncMock(side_effect=slow_execute)

        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "sleep 1"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "echo step2"}},
        ]
        task_id = await self.worker.create_goal(goal="Slow task with concurrent cancel", steps=steps)

        # Bắt đầu chạy poll_once trong background task
        poll_task = asyncio.create_task(self.worker.poll_once())

        # Chờ 0.01s để poll_once kịp bắt đầu và đang chờ slow_execute
        await asyncio.sleep(0.01)

        # Gửi lệnh cancel_goal ngay trong khi step 1 đang chạy
        cancelled = await self.worker.cancel_goal(task_id, reason="Cancelled during step 1")
        self.assertTrue(cancelled)

        # Chờ poll_task hoàn thành
        await poll_task

        # Kiểm tra trạng thái trong store
        status_after = await self.worker.get_goal_status(task_id)
        print(f"[EMPIRICAL CHALLENGER OBSERVED] Status after concurrent cancel: {status_after['status']}")

        # Nếu polling tiếp tục, bước 2 có bị rò rỉ và chạy tiếp không?
        await self.worker.poll_once()
        status_final = await self.worker.get_goal_status(task_id)
        print(f"[EMPIRICAL CHALLENGER OBSERVED] Step count executed: {self.mock_executor.execute_tool.await_count}, Final status: {status_final['status']}")

        # KỲ VỌNG BẢO MẬT & AN TOÀN VI MẠCH (CHALLENGER ORACLE):
        # 1. Trạng thái task sau khi người dùng hủy phải được bảo toàn là 'cancelled'.
        # 2. Bước 2 tuyệt đối KHÔNG được thực thi (execute_tool chỉ được gọi đúng 1 lần từ bước 1).
        self.assertEqual(
            status_after["status"],
            "cancelled",
            "STATE LEAK BUG: Concurrent cancel_goal was overwritten by active step completion!",
        )
        self.assertEqual(
            self.mock_executor.execute_tool.await_count,
            1,
            "EXECUTION LEAK BUG: Subsequent step was executed despite user cancellation!",
        )

    async def test_stress_cancel_waiting_approval_task(self) -> None:
        """
        Kịch bản 1.3: Hủy task đang bị chặn ở trạng thái waiting_approval (Tier 3 lethal).
        """
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "mkfs.ext4 /dev/sda"}},
        ]
        task_id = await self.worker.create_goal(goal="Format disk", steps=steps)

        # Chạy step 1 -> gặp Tier 3 Lethal -> chuyển sang waiting_approval
        await self.worker.poll_once()
        task = await self.worker.get_goal_status(task_id)
        self.assertEqual(task["status"], "waiting_approval")

        # Hủy task khi đang waiting_approval
        ok = await self.worker.cancel_goal(task_id, reason="Admin rejected dangerous action")
        self.assertTrue(ok)

        task_after = await self.worker.get_goal_status(task_id)
        self.assertEqual(task_after["status"], "cancelled")
        self.assertEqual(task_after["error_message"], "Admin rejected dangerous action")

    # =========================================================================
    # PART 2: UNEXPECTED / NON-STANDARD EXCEPTIONS HANDLING
    # =========================================================================

    async def test_stress_non_standard_exceptions_and_retry_resilience(self) -> None:
        """
        Kịch bản 2.1: Ngoại lệ không lường trước (Non-standard / Unhandled exceptions).
        Mô phỏng tool_executor ném lần lượt:
        - Lần 1: ZeroDivisionError
        - Lần 2: TypeError
        - Lần 3: KeyError
        Kiểm tra:
        - Worker KHÔNG bị sập loop.
        - retry_count tăng chính xác từ 0 -> 1 -> 2 -> 3.
        - Tại lần 1 và 2: status là 'running'.
        - Tại lần 3 (max_retries = 3): status chuyển thành 'failed'.
        - Telegram notify failure được gọi đúng format.
        """
        call_count = 0
        def failing_executor(tool_name, tool_args, chat_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ZeroDivisionError("division by zero in math logic")
            elif call_count == 2:
                raise TypeError("unsupported operand type(s) for +: 'NoneType' and 'int'")
            else:
                raise KeyError("missing_critical_system_metric_key")

        self.mock_executor.execute_tool = AsyncMock(side_effect=failing_executor)

        steps = [{"step_id": 1, "tool": "run_command", "args": {"command": "diagnose_system"}}]
        task_id = await self.worker.create_goal(goal="Non-standard exception test", steps=steps)

        # Vòng 1: ZeroDivisionError
        count1 = await self.worker.poll_once()
        self.assertEqual(count1, 1)
        task1 = await self.worker.get_goal_status(task_id)
        self.assertEqual(task1["status"], "running")
        self.assertEqual(task1["retry_count"], 1)
        self.assertIn("division by zero", task1["steps"][0]["error"])
        self.assertIn("attempt 1/3", task1["error_message"])

        # Vòng 2: TypeError
        count2 = await self.worker.poll_once()
        self.assertEqual(count2, 1)
        task2 = await self.worker.get_goal_status(task_id)
        self.assertEqual(task2["status"], "running")
        self.assertEqual(task2["retry_count"], 2)
        self.assertIn("unsupported operand type", task2["steps"][0]["error"])
        self.assertIn("attempt 2/3", task2["error_message"])

        # Vòng 3: KeyError -> đạt max_retries = 3 -> status='failed'
        count3 = await self.worker.poll_once()
        self.assertEqual(count3, 1)
        task3 = await self.worker.get_goal_status(task_id)
        self.assertEqual(task3["status"], "failed")
        self.assertEqual(task3["retry_count"], 3)
        self.assertIn("missing_critical_system_metric_key", task3["steps"][0]["error"])
        self.assertIn("Failed at step 1", task3["error_message"])
        self.assertIsNotNone(task3["completed_at"])

        # Vòng 4: Task đã failed, poll_once không được nhặt lại
        count4 = await self.worker.poll_once()
        self.assertEqual(count4, 0)

        # Telegram failure alert đã được gửi
        self.mock_telegram.send_message.assert_awaited()
        call_args = self.mock_telegram.send_message.call_args[0]
        self.assertIn("Mục tiêu tự động gặp sự cố", call_args[1])
        self.assertIn("missing_critical_system_metric_key", call_args[1])

    async def test_stress_transient_failure_then_successful_recovery(self) -> None:
        """
        Kịch bản 2.2: Ngoại lệ tạm thời (Transient error) rồi phục hồi thành công.
        Lần 1 & 2 ném ConnectionResetError. Lần 3 thành công.
        Kiểm tra:
        - Sau khi thành công ở lần 3, retry_count được reset về 0.
        - Task hoàn thành hoặc chuyển sang bước kế tiếp trơn tru.
        """
        call_count = 0
        def transient_executor(tool_name, tool_args, chat_id=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionResetError(f"Transient network drop #{call_count}")
            return "Connection re-established and query succeeded"

        self.mock_executor.execute_tool = AsyncMock(side_effect=transient_executor)

        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "curl http://remote-api"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "echo done"}},
        ]
        task_id = await self.worker.create_goal(goal="Transient failure recovery", steps=steps)

        # Lần 1: Lỗi
        await self.worker.poll_once()
        t1 = await self.worker.get_goal_status(task_id)
        self.assertEqual(t1["retry_count"], 1)
        self.assertEqual(t1["current_step"], 0)

        # Lần 2: Lỗi
        await self.worker.poll_once()
        t2 = await self.worker.get_goal_status(task_id)
        self.assertEqual(t2["retry_count"], 2)
        self.assertEqual(t2["current_step"], 0)

        # Lần 3: Thành công bước 1!
        await self.worker.poll_once()
        t3 = await self.worker.get_goal_status(task_id)
        self.assertEqual(t3["current_step"], 1)
        self.assertEqual(t3["retry_count"], 0, "retry_count must be reset to 0 after step success!")
        self.assertEqual(t3["status"], "running")

        # Lần 4: Chạy bước 2 thành công -> completed
        await self.worker.poll_once()
        t4 = await self.worker.get_goal_status(task_id)
        self.assertEqual(t4["current_step"], 2)
        self.assertEqual(t4["status"], "completed")

    async def test_stress_batch_isolation_when_one_task_throws_fatal_error(self) -> None:
        """
        Kịch bản 2.3: Cách ly trong batch polling (Batch Isolation).
        Nếu một task gây lỗi ngoài dự kiến trong _execute_single_step,
        các task khác trong cùng batch vẫn phải được xử lý bình thường mà không bị ảnh hưởng.
        """
        # Tạo 2 tasks
        id_bad = await self.worker.create_goal(goal="Bad task", steps=[{"tool": "bad_tool", "args": {}}])
        id_good = await self.worker.create_goal(goal="Good task", steps=[{"tool": "good_tool", "args": {}}])

        # Mock execute_tool: bad_tool ném SystemError, good_tool thành công
        async def selective_executor(tool_name, tool_args, chat_id=None):
            if tool_name == "bad_tool":
                raise SystemError("Fatal low-level system error")
            return "Good tool executed fine"

        self.mock_executor.execute_tool = AsyncMock(side_effect=selective_executor)

        # Chạy poll_once
        processed = await self.worker.poll_once()
        self.assertEqual(processed, 2, "Both tasks should be attempted in poll_once")

        status_bad = await self.worker.get_goal_status(id_bad)
        status_good = await self.worker.get_goal_status(id_good)

        # Bad task bị lỗi và tăng retry_count
        self.assertEqual(status_bad["retry_count"], 1)
        # Good task đã hoàn thành thành công
        self.assertEqual(status_good["status"], "completed")
        self.assertEqual(status_good["current_step"], 1)

    # =========================================================================
    # PART 3: ZERO STATE LOSS & WORKER RESTART STRESS TESTS
    # =========================================================================

    async def test_stress_zero_state_loss_5_steps_restart_after_step_2(self) -> None:
        """
        Kịch bản 3.1: Kiểm tra tính bền vững: Zero State Loss
        - Tạo goal với 5 bước chi tiết:
          1. df -h (Kiểm tra dung lượng đĩa)
          2. free -m (Kiểm tra bộ nhớ RAM)
          3. uptime (Kiểm tra thời gian hoạt động hệ thống)
          4. docker ps (Kiểm tra container đang chạy)
          5. uname -a (Kiểm tra thông tin kernel OS)
        - Thực thi CHÍNH XÁC 2 bước đầu tiên bằng Worker Instance 1.
          Xác minh: current_step = 2, status = 'running'.
          Bước 1 & 2 đã có result và status = 'completed'.
          Bước 3, 4, 5 vẫn là 'pending'.
        - Mô phỏng Worker Restart:
          Dừng hoàn toàn Worker Instance 1 (worker1.stop()).
          Khởi tạo Worker Instance 2 độc lập trên cùng Task Store.
        - Khôi phục và tiếp tục:
          Worker Instance 2 đọc task từ store:
          Xác minh: current_step = 2 (Zero State Loss).
          Worker 2 tiếp tục thực thi các bước 3, 4, 5.
          Xác minh: Bước 1 và 2 TUYỆT ĐỐI KHÔNG BỊ CHẠY LẠI!
          Trạng thái cuối cùng: status = 'completed', current_step = 5.
          Cả 5 bước đều có đầy đủ result.
        """
        steps = [
            {"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}},
            {"step_id": 2, "tool": "run_command", "args": {"command": "free -m"}},
            {"step_id": 3, "tool": "run_command", "args": {"command": "uptime"}},
            {"step_id": 4, "tool": "run_command", "args": {"command": "docker ps"}},
            {"step_id": 5, "tool": "run_command", "args": {"command": "uname -a"}},
        ]

        executed_commands_worker1 = []
        async def exec_worker1(tool_name, tool_args, chat_id=None):
            cmd = tool_args.get("command", "")
            executed_commands_worker1.append(cmd)
            return f"Worker1 output for {cmd}"

        executor1 = MagicMock()
        executor1.execute_tool = AsyncMock(side_effect=exec_worker1)

        telegram1 = MagicMock()
        telegram1.chat_id = "chat_zero_state"
        telegram1.send_message = AsyncMock(return_value=True)

        # Worker Instance 1
        worker1 = AutonomousGoalWorker(
            tool_executor=executor1,
            telegram_bot=telegram1,
            use_db=False,
            poll_interval_seconds=1,
        )
        worker1._in_memory_store = self.store
        await worker1.ensure_tables()

        task_id = await worker1.create_goal(
            goal="Hạ tầng kiểm tra định kỳ 5 bước",
            steps=steps,
            chat_id="chat_zero_state",
        )

        # Worker 1 chạy bước 1
        p1 = await worker1.poll_once()
        self.assertEqual(p1, 1)
        task_step1 = await worker1.get_goal_status(task_id)
        self.assertEqual(task_step1["current_step"], 1)
        self.assertEqual(task_step1["status"], "running")
        self.assertEqual(executed_commands_worker1, ["df -h"])

        # Worker 1 chạy bước 2
        p2 = await worker1.poll_once()
        self.assertEqual(p2, 1)
        task_step2 = await worker1.get_goal_status(task_id)
        self.assertEqual(task_step2["current_step"], 2)
        self.assertEqual(task_step2["status"], "running")
        self.assertEqual(executed_commands_worker1, ["df -h", "free -m"])

        # Xác thực trạng thái các bước tại thời điểm ngắt:
        self.assertEqual(task_step2["steps"][0]["status"], "completed")
        self.assertEqual(task_step2["steps"][1]["status"], "completed")
        self.assertEqual(task_step2["steps"][2]["status"], "pending")
        self.assertEqual(task_step2["steps"][3]["status"], "pending")
        self.assertEqual(task_step2["steps"][4]["status"], "pending")

        # =====================================================================
        # MÔ PHỎNG WORKER RESTART / CRASH / SERVICE UPGRADE
        # =====================================================================
        await worker1.stop()
        del worker1  # Hủy instance cũ

        # Worker Instance 2 khởi động mới hoàn toàn
        executed_commands_worker2 = []
        async def exec_worker2(tool_name, tool_args, chat_id=None):
            cmd = tool_args.get("command", "")
            executed_commands_worker2.append(cmd)
            return f"Worker2 output for {cmd}"

        executor2 = MagicMock()
        executor2.execute_tool = AsyncMock(side_effect=exec_worker2)

        telegram2 = MagicMock()
        telegram2.chat_id = "chat_zero_state"
        telegram2.send_message = AsyncMock(return_value=True)

        worker2 = AutonomousGoalWorker(
            tool_executor=executor2,
            telegram_bot=telegram2,
            use_db=False,
            poll_interval_seconds=1,
        )
        worker2._in_memory_store = self.store
        await worker2.ensure_tables()

        # Kiểm tra task khi Worker 2 vừa load lên
        task_loaded = await worker2.get_goal_status(task_id)
        self.assertIsNotNone(task_loaded)
        self.assertEqual(task_loaded["current_step"], 2, "Current step must strictly remain 2!")
        self.assertEqual(task_loaded["status"], "running")
        self.assertIn("Worker1 output for df -h", task_loaded["steps"][0]["result"])
        self.assertIn("Worker1 output for free -m", task_loaded["steps"][1]["result"])

        # Worker 2 tiếp tục thực thi:
        # Vòng 1 của Worker 2 -> thực thi bước 3 ('uptime')
        p_w2_1 = await worker2.poll_once()
        self.assertEqual(p_w2_1, 1)
        t_w2_1 = await worker2.get_goal_status(task_id)
        self.assertEqual(t_w2_1["current_step"], 3)
        self.assertEqual(executed_commands_worker2, ["uptime"])

        # Vòng 2 của Worker 2 -> thực thi bước 4 ('docker ps')
        p_w2_2 = await worker2.poll_once()
        self.assertEqual(p_w2_2, 1)
        t_w2_2 = await worker2.get_goal_status(task_id)
        self.assertEqual(t_w2_2["current_step"], 4)
        self.assertEqual(executed_commands_worker2, ["uptime", "docker ps"])

        # Vòng 3 của Worker 2 -> thực thi bước 5 ('uname -a') - bước cuối cùng!
        p_w2_3 = await worker2.poll_once()
        self.assertEqual(p_w2_3, 1)
        final_task = await worker2.get_goal_status(task_id)

        # KIỂM CHỨNG TÍNH TOÀN VẸN (ZERO STATE LOSS):
        # 1. Trạng thái kết thúc:
        self.assertEqual(final_task["status"], "completed")
        self.assertEqual(final_task["current_step"], 5)
        self.assertIsNotNone(final_task["completed_at"])

        # 2. Worker 2 TUYỆT ĐỐI KHÔNG CHẠY LẠI BƯỚC 1 VÀ 2:
        self.assertNotIn("df -h", executed_commands_worker2)
        self.assertNotIn("free -m", executed_commands_worker2)
        self.assertEqual(executed_commands_worker2, ["uptime", "docker ps", "uname -a"])

        # 3. Kết quả các bước:
        steps_res = final_task["steps"]
        self.assertEqual(len(steps_res), 5)
        self.assertIn("Worker1 output for df -h", steps_res[0]["result"])
        self.assertIn("Worker1 output for free -m", steps_res[1]["result"])
        self.assertIn("Worker2 output for uptime", steps_res[2]["result"])
        self.assertIn("Worker2 output for docker ps", steps_res[3]["result"])
        self.assertIn("Worker2 output for uname -a", steps_res[4]["result"])

        # 4. Báo cáo Telegram hoàn thành gửi đúng tiến độ 5/5 bước:
        telegram2.send_message.assert_awaited()
        tg_call = telegram2.send_message.call_args[0]
        self.assertEqual(tg_call[0], "chat_zero_state")
        self.assertIn("Đã hoàn thành 5/5 bước", tg_call[1])
        self.assertIn("df -h", tg_call[1])
        self.assertIn("uname -a", tg_call[1])

        await worker2.stop()

    async def test_stress_restart_preserves_retry_state_on_failing_step(self) -> None:
        """
        Kịch bản 3.2: Bảo toàn retry state khi restart.
        Task bị lỗi ở bước 1, retry_count = 2 (đã thử 2 lần).
        Worker 1 shutdown, Worker 2 khởi động lại.
        Kiểm tra:
        - Worker 2 nạp lên vẫn giữ nguyên retry_count = 2, current_step = 0.
        - Lần thử tiếp theo của Worker 2 nếu thất bại sẽ tăng retry_count = 3 -> chuyển status='failed',
          chứ KHÔNG bị reset retry_count về 0 khiến task bị loop vô hạn!
        """
        failing_executor = MagicMock()
        failing_executor.execute_tool = AsyncMock(side_effect=RuntimeError("Persistent DB error"))

        worker1 = AutonomousGoalWorker(tool_executor=failing_executor, use_db=False)
        worker1._in_memory_store = self.store
        await worker1.ensure_tables()

        task_id = await worker1.create_goal(
            goal="Goal fails twice then restarts",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "test"}}],
        )

        # Thử 2 lần trên Worker 1
        await worker1.poll_once()  # retry 1
        await worker1.poll_once()  # retry 2
        t_pre = await worker1.get_goal_status(task_id)
        self.assertEqual(t_pre["retry_count"], 2)
        self.assertEqual(t_pre["status"], "running")

        # Worker 1 restart
        await worker1.stop()

        worker2 = AutonomousGoalWorker(tool_executor=failing_executor, use_db=False)
        worker2._in_memory_store = self.store
        await worker2.ensure_tables()

        t_post_load = await worker2.get_goal_status(task_id)
        self.assertEqual(t_post_load["retry_count"], 2, "Worker 2 must preserve retry_count=2!")

        # Worker 2 thử lần thứ 3 (chạm max_retries = 3)
        await worker2.poll_once()
        t_final = await worker2.get_goal_status(task_id)
        self.assertEqual(t_final["retry_count"], 3)
        self.assertEqual(t_final["status"], "failed", "Task must transition to failed on 3rd retry across restart!")

        await worker2.stop()


if __name__ == "__main__":
    unittest.main()
