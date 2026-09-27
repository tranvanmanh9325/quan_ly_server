import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.system_mastery_service import (
    SystemMasteryService,
    run_command_unrestricted,
    execute_system_script,
    manage_docker_containers,
    optimize_system_resources,
    _parse_memory_mb,
    _parse_disk_mb,
)


class MockSshClient:
    def __init__(self):
        self.executed_commands = []
        self.responses = {}
        self.default_response = "Command executed successfully."

    async def execute_command(self, command: str, timeout=None, max_output_chars=None, unrestricted=False, allow_admin=False):
        self.executed_commands.append({
            "command": command,
            "timeout": timeout,
            "unrestricted": unrestricted or allow_admin,
        })
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


class TestSystemMasteryService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_ssh = MockSshClient()
        self.service = SystemMasteryService(ssh_client=self.mock_ssh)

    def test_parse_memory_and_disk(self):
        sample_free = """
                      total        used        free      shared  buff/cache   available
        Mem:           3180        1500         800         120         880        1560
        Swap:          2048         100        1948
        """
        mem = _parse_memory_mb(sample_free)
        self.assertEqual(mem["total"], 3180)
        self.assertEqual(mem["used"], 1500)
        self.assertEqual(mem["available"], 1560)

        sample_df = """
        Filesystem     1M-blocks  Used Available Use% Mounted on
        /dev/sda1          48000 24000     22000  53% /
        """
        disk = _parse_disk_mb(sample_df)
        self.assertEqual(disk["total"], 48000)
        self.assertEqual(disk["used"], 24000)
        self.assertEqual(disk["available"], 22000)

    async def test_run_command_unrestricted_allowed_admin_commands(self):
        self.mock_ssh.default_response = "Container stopped"
        res = await self.service.run_command_unrestricted("docker stop my_app")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["output"], "Container stopped")

        # Verify command was executed with unrestricted=True
        last_call = self.mock_ssh.executed_commands[-1]
        self.assertEqual(last_call["command"], "docker stop my_app")
        self.assertTrue(last_call["unrestricted"])

    async def test_run_command_unrestricted_hardware_destruction_blocked(self):
        # Even with unrestricted=True, spinal safety veto must block mkfs or rm -rf /
        from app.core.security import find_security_violation
        violation = find_security_violation("mkfs /dev/sda", unrestricted=True)
        self.assertIsNotNone(violation)
        self.assertIn("destructive hardware pattern", violation)

        violation_rm = find_security_violation("rm -rf /", unrestricted=True)
        self.assertIsNotNone(violation_rm)
        self.assertIn("destructive hardware pattern", violation_rm)

        # Mock SshClient returning BLOCKED message when hardware destructive pattern is found
        self.mock_ssh.responses["mkfs /dev/sda"] = "BLOCKED: contains destructive hardware pattern 'mkfs'"
        res = await self.service.run_command_unrestricted("mkfs /dev/sda")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("chặn bởi cơ chế bảo vệ phần cứng", res["message"])

    async def test_run_command_empty(self):
        res = await self.service.run_command_unrestricted("   ")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    async def test_execute_system_script_bash_success_and_cleanup(self):
        script = """
        echo "Line 1"
        echo "Line 2"
        """
        # When script is executed, return output with exit code 0
        def handle_exec(cmd):
            if "agent_script_" in cmd and "__SCRIPT_EXIT_CODE__" in cmd:
                return "Line 1\nLine 2\n__SCRIPT_EXIT_CODE__:0"
            return ""

        self.mock_ssh.responses = {
            "__SCRIPT_EXIT_CODE__": "Line 1\nLine 2\n__SCRIPT_EXIT_CODE__:0",
            "rm -f": "",
        }

        res = await self.service.execute_system_script(script, interpreter="bash", timeout=60)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Line 1\nLine 2", res["output"])

        # Check execution history: must contain staging (base64 -d), execution, and cleanup (rm -f)
        cmds = [c["command"] for c in self.mock_ssh.executed_commands]
        self.assertTrue(any("base64 -d" in c for c in cmds), "Script staging missing base64 decode")
        self.assertTrue(any("bash /tmp/agent_script_" in c for c in cmds), "Script execution command missing")
        self.assertTrue(any("rm -f /tmp/agent_script_" in c for c in cmds), "Zero-leak script cleanup missing")

    async def test_execute_system_script_python_error_exit_code(self):
        py_script = """
        import sys
        sys.stderr.write("Critical error occurred\\n")
        sys.exit(3)
        """
        self.mock_ssh.responses = {
            "__SCRIPT_EXIT_CODE__": "Critical error occurred\n__SCRIPT_EXIT_CODE__:3",
            "rm -f": "",
        }

        res = await self.service.execute_system_script(py_script, interpreter="python3")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["exit_code"], 3)
        self.assertIn("Critical error occurred", res["output"])

        # Cleanup rm -f must still be called in finally!
        cmds = [c["command"] for c in self.mock_ssh.executed_commands]
        self.assertTrue(any("rm -f /tmp/agent_script_" in c for c in cmds), "Cleanup must run even on error")

    async def test_execute_system_script_run_as_root(self):
        self.mock_ssh.responses = {
            "__SCRIPT_EXIT_CODE__": "root_action_ok\n__SCRIPT_EXIT_CODE__:0",
            "rm -f": "",
        }

        res = await self.service.execute_system_script("echo root", run_as_root=True)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["run_as_root"])

        cmds = [c["command"] for c in self.mock_ssh.executed_commands]
        self.assertTrue(any("sudo -n bash /tmp/agent_script_" in c for c in cmds))

    async def test_manage_docker_containers_list(self):
        container_json_1 = json.dumps({"ID": "abc12345", "Names": "dashboard_ai_agent", "Status": "Up 2 hours"})
        container_json_2 = json.dumps({"ID": "def67890", "Names": "dashboard_db", "Status": "Up 5 days"})
        self.mock_ssh.responses["docker ps -a"] = f"{container_json_1}\n{container_json_2}"

        res = await self.service.manage_docker_containers(action="list")
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["data"]), 2)
        self.assertEqual(res["data"][0]["Names"], "dashboard_ai_agent")

    async def test_manage_docker_containers_inspect_and_logs(self):
        inspect_data = [{"Id": "c1", "State": {"Running": True}}]
        self.mock_ssh.responses["docker inspect web_service"] = json.dumps(inspect_data)
        self.mock_ssh.responses["docker logs"] = "2026-09-27T10:00:00Z Server running on port 80"

        res_inspect = await self.service.manage_docker_containers("inspect", container_name="web_service")
        self.assertEqual(res_inspect["status"], "success")
        self.assertTrue(res_inspect["data"][0]["State"]["Running"])

        res_logs = await self.service.manage_docker_containers("logs", container_name="web_service", lines=50)
        self.assertEqual(res_logs["status"], "success")
        self.assertIn("Server running on port 80", res_logs["raw_output"])

    async def test_manage_docker_containers_critical_guard(self):
        # Stopping a critical container without force=True must be blocked
        res_blocked = await self.service.manage_docker_containers("stop", container_name="dashboard_db", force=False)
        self.assertEqual(res_blocked["status"], "blocked")
        self.assertIn("dịch vụ Production trọng yếu", res_blocked["message"])

        # With force=True, it should proceed
        self.mock_ssh.responses["docker stop -t 0 dashboard_db"] = "dashboard_db"
        res_forced = await self.service.manage_docker_containers("stop", container_name="dashboard_db", force=True)
        self.assertEqual(res_forced["status"], "success")

    async def test_manage_docker_containers_prune_and_validation(self):
        self.mock_ssh.responses["docker container prune"] = "Deleted Containers: c1, c2\nTotal reclaimed space: 500MB"
        res = await self.service.manage_docker_containers("prune")
        self.assertEqual(res["status"], "success")
        self.assertIn("500MB", res["raw_output"])

        # Missing container name for start
        res_err = await self.service.manage_docker_containers("start", container_name="")
        self.assertEqual(res_err["status"], "error")
        self.assertIn("yêu cầu cung cấp tham số 'container_name'", res_err["message"])

    async def test_optimize_system_resources_all_steps(self):
        free_before = "Mem: 3200 2000 500 0 700 1200\n"
        df_before = "Filesystem 1M-blocks Used Available Use% Mounted on\n/dev/sda1 50000 30000 20000 60% /\n"

        free_after = "Mem: 3200 1400 1100 0 700 1800\n"
        df_after = "Filesystem 1M-blocks Used Available Use% Mounted on\n/dev/sda1 50000 28000 22000 56% /\n"

        # Sequential responses for free -m and df -m /
        call_counts = {"free": 0, "df": 0}

        async def dynamic_exec(cmd, **kwargs):
            if "free -m" in cmd:
                call_counts["free"] += 1
                return free_before if call_counts["free"] == 1 else free_after
            if "df -m /" in cmd:
                call_counts["df"] += 1
                return df_before if call_counts["df"] == 1 else df_after
            return "OK"

        self.mock_ssh.execute_command = dynamic_exec

        res = await self.service.optimize_system_resources()
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["steps_executed"]), 6)
        self.assertEqual(res["freed"]["ram_freed_mb"], 600)   # 1800 - 1200
        self.assertEqual(res["freed"]["disk_freed_mb"], 2000) # 30000 - 28000
        self.assertIn("600 MB RAM", res["message"])


if __name__ == "__main__":
    unittest.main()
