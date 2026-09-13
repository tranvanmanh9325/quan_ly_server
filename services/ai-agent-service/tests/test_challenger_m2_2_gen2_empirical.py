"""
test_challenger_m2_2_gen2_empirical.py — Empirical Challenger Re-Verification Harness for M2 Gen 2.

Comprehensive Adversarial Test Suite for Spinal Safety Veto & Cognitive Architecture Security:
- Group 1: Benign & Rescue Diagnostic Commands (Verifying 0% False Positives)
- Group 2: Lethal File Wiping Variants (Split flags, long flags, whitespace variations, no-preserve-root)
- Group 3: Reckless Permissions & Ownership (Chmod/Chown inverted flags, long options)
- Group 4: Database Destruction (Compact PostgreSQL TRUNCATE, DROP variants)
- Group 5: Container Mass Purge (Docker system prune, docker prune, backtick/subshell commands)
- Group 6: Network & Firewall Blackout (iptables table flags, ufw force reset, ip link down)
- Group 7: Actual Stress Exhaustion & DoS (stress, stress-ng, sudo, chained executions)
- Group 8: Confirmation Token Protocol (Exact token allow, invalid/fuzzy tokens strict rejection)
- Group 9: AgentToolExecutor Live Interception Integration (End-to-end tool gating)
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.ai_agent_tools import evaluate_spinal_safety_veto, AgentToolExecutor


class TestChallengerM22Gen2EmpiricalSuite(unittest.IsolatedAsyncioTestCase):
    """
    Empirical Verification Suite executed by Challenger 2 Gen 2.
    Strictly empirical, verifying exact return values, zero false positives, and 100% intercept rate.
    """

    # --- GROUP 1: BENIGN & RESCUE COMMANDS (MUST NOT BE BLOCKED) ---
    BENIGN_COMMANDS = [
        "ps aux | grep stress",
        "which stress",
        "pkill stress",
        "pkill -9 stress",
        "killall stress",
        "killall -9 stress-ng",
        "systemctl status stress",
        "man stress",
        "man stress-ng",
        "which stress-ng",
        "free -m",
        "docker ps -a",
        "uptime",
        "ip addr show eth0",
        "ufw status verbose",
        "iptables -L -n -v",
        "ip link set dev eth0 up",
        "find /var/log -name '*.log'",
        "cat /etc/resolv.conf",
        "echo 'stress test finished successfully'",
    ]

    # --- GROUP 2: LETHAL FILE WIPING VARIANTS (MUST BE INTERCEPTED) ---
    LETHAL_FILE_WIPES = [
        "rm -r -f /",
        "rm -f -r /",
        "rm --recursive --force /",
        "rm --force --recursive /",
        "rm -rf --no-preserve-root /",
        "rm -r -f --no-preserve-root /",
        "rm --recursive /",
        "rm -rf /*",
        "rm -rf /root",
        "rm   -r    -f    /",
        "rm -v -r -f /",
        "rm -f -v -r /",
        "find / -name '*.tmp' -delete",
        "find /var/log -type f -exec rm -f {} +",
        "truncate -s 0 /var/log/syslog",
        "truncate -s0 /var/log/nginx/access.log",
        "rm -f ~/.ssh/authorized_keys",
        "> ~/.ssh/authorized_keys",
        "> /etc/ssh/sshd_config",
        "systemctl stop sshd",
        "systemctl disable ssh",
    ]

    # --- GROUP 3: RECKLESS PERMISSIONS & OWNERSHIP (MUST BE INTERCEPTED) ---
    RECKLESS_PERMS = [
        "chmod 777 -R /",
        "chmod -R 777 /",
        "chmod --recursive 777 /",
        "chmod 777 --recursive /",
        "chmod -R 0777 /var/www",
        "chmod -R a+rwx /",
        "chmod 777 -R /home",
        "chown --recursive root:root /",
        "chown root:root -R /",
        "chown -R root:root /",
        "chown -v -R www-data:www-data /etc",
    ]

    # --- GROUP 4: DATABASE DESTRUCTION (MUST BE INTERCEPTED) ---
    DATABASE_DESTRUCTION = [
        "TRUNCATE users;",
        "truncate table users;",
        "TRUNCATE TABLE \"user_sessions\";",
        "TRUNCATE users CASCADE;",
        "TRUNCATE ONLY accounts;",
        "truncate table only orders;",
        "DROP DATABASE production;",
        "DROP TABLE customers;",
        "DROP SCHEMA public CASCADE;",
    ]

    # --- GROUP 5: CONTAINER MASS PURGE (MUST BE INTERCEPTED) ---
    CONTAINER_PURGE = [
        "docker system prune --all --volumes",
        "docker system prune -a",
        "docker prune --all",
        "docker prune -a",
        "docker rm -f $(docker container ls -q)",
        "docker rm -f $(docker ps -aq)",
        "docker rm -f `docker ps -aq`",
        "docker rm -f `docker container ls -q`",
        "docker kill $(docker ps -q)",
        "docker kill `docker ps -q`",
    ]

    # --- GROUP 6: NETWORK & FIREWALL BLACKOUT (MUST BE INTERCEPTED) ---
    NETWORK_BLACKOUT = [
        "iptables -t nat -F",
        "iptables -F",
        "iptables -X",
        "iptables --flush",
        "ufw --force reset",
        "ufw reset",
        "ufw disable",
        "ip link set dev eth0 down",
        "ip link set eth0 down",
        "ip -br link set dev eth0 down",
    ]

    # --- GROUP 7: ACTUAL STRESS EXHAUSTION & DOS (MUST BE INTERCEPTED) ---
    STRESS_EXHAUSTION = [
        "stress --cpu 4",
        "stress-ng --vm 2",
        "sudo stress --cpu 2",
        "sudo -u root stress-ng --vm 2",
        "sudo -i stress --vm 1",
        "nohup stress --cpu 8 &",
        "exec stress-ng --cpu 4",
        "env FOO=bar stress --io 2",
        ":(){ :|:& };:",
        ":(){:|:&};:",
        "echo 'starting test' && stress --cpu 4",
        "ls -la; stress-ng --vm 2",
    ]

    def test_benign_commands_pass_cleanly_zero_false_positives(self):
        """Verify benign commands and rescue commands return None (0% False Positives)."""
        for cmd in self.BENIGN_COMMANDS:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNone(
                veto,
                f"FALSE POSITIVE DETECTED: Benign command '{cmd}' was incorrectly blocked: {veto}"
            )

    def test_lethal_file_wiping_intercepted_100_percent(self):
        """Verify all lethal file wipes, split flags, long flags are intercepted."""
        for cmd in self.LETHAL_FILE_WIPES:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Lethal file wiping '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_reckless_permissions_intercepted_100_percent(self):
        """Verify chmod and chown variations with flags in any order are intercepted."""
        for cmd in self.RECKLESS_PERMS:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Reckless permission command '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_database_destruction_intercepted_100_percent(self):
        """Verify PostgreSQL compact TRUNCATE and DROP variations are intercepted."""
        for cmd in self.DATABASE_DESTRUCTION:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Database destructive command '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_container_purge_intercepted_100_percent(self):
        """Verify docker prune and mass container removals are intercepted."""
        for cmd in self.CONTAINER_PURGE:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Container purge command '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_network_blackout_intercepted_100_percent(self):
        """Verify iptables, ufw, and ip link down commands are intercepted."""
        for cmd in self.NETWORK_BLACKOUT:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Network blackout command '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_stress_exhaustion_intercepted_100_percent(self):
        """Verify stress/stress-ng commands and fork bombs are intercepted."""
        for cmd in self.STRESS_EXHAUSTION:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"SECURITY HOLE: Stress exhaustion command '{cmd}' BYPASSED spinal veto!"
            )
            self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", veto)

    def test_confirmation_token_allows_execution(self):
        """Verify exact token CONFIRM_DANGEROUS_ACTION allows dangerous commands."""
        test_samples = [
            "rm -r -f /",
            "chmod 777 -R /",
            "TRUNCATE users;",
            "docker prune --all",
            "iptables -t nat -F",
            "ufw --force reset",
            "stress --cpu 4",
        ]
        for cmd in test_samples:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token="CONFIRM_DANGEROUS_ACTION")
            self.assertIsNone(
                veto,
                f"VALID TOKEN REJECTED: Command '{cmd}' was blocked despite valid confirm_token!"
            )

    def test_invalid_confirmation_tokens_rejected(self):
        """Verify invalid or near-match tokens do NOT bypass the veto."""
        invalid_tokens = [
            "CONFIRM",
            "confirm",
            "CONFIRM_DANGEROUS",
            "confirm_dangerous_action",
            "CONFIRM_DANGEROUS_ACTION ",
            " CONFIRM_DANGEROUS_ACTION",
            "yes",
            "true",
            "1",
            "",
            "None",
        ]
        target_cmd = "rm -rf /"
        for bad_token in invalid_tokens:
            veto = evaluate_spinal_safety_veto(target_cmd, confirm_token=bad_token)
            self.assertIsNotNone(
                veto,
                f"BYPASS VULNERABILITY: Invalid token '{bad_token}' bypassed spinal veto!"
            )

    async def test_agent_tool_executor_gating_integration(self):
        """End-to-end integration test through AgentToolExecutor.execute_tool."""
        mock_ssh = MagicMock()
        mock_ssh.execute_command = AsyncMock(return_value="executed_ok")
        tools = AgentToolExecutor(ssh_client=mock_ssh, message_cache=MagicMock())

        # 1. Unconfirmed destructive execution -> Blocked at spinal level
        destructive_cmd = "iptables -t nat -F"
        res = await tools.execute_tool("run_command", {"command": destructive_cmd})
        self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", res)
        mock_ssh.execute_command.assert_not_called()

        # 2. Confirmed destructive execution -> Executed through SSH
        res_confirmed = await tools.execute_tool(
            "run_command",
            {"command": destructive_cmd, "confirm": "CONFIRM_DANGEROUS_ACTION"}
        )
        self.assertEqual(res_confirmed, "executed_ok")
        mock_ssh.execute_command.assert_called_once_with(destructive_cmd)

        # 3. Benign execution -> Passes immediately without confirm token
        mock_ssh.execute_command.reset_mock()
        mock_ssh.execute_command.return_value = "stress: 12345"
        res_benign = await tools.execute_tool("run_command", {"command": "pkill stress"})
        self.assertEqual(res_benign, "stress: 12345")
        mock_ssh.execute_command.assert_called_once_with("pkill stress")


if __name__ == "__main__":
    unittest.main()
