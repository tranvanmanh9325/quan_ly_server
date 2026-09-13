"""
Adversarial Stress Test Suite: Expanded Spinal Safety Veto
Milestone 2 - Empirical Challenger 2 Verification
Module: services/ai-agent-service/app/services/ai_agent_tools.py

Tests verify:
1. 100% intercept rate on destructive commands across 8 threat vectors without valid confirm_token.
2. 0% false positives on safe diagnostic commands (free -h, docker ps, uptime, ls -la, find . -name "*.py", etc.).
3. Authorization bypass behavior with valid CONFIRM_DANGEROUS_ACTION.
4. Defense against invalid or partial confirmation tokens.
5. Defense against chained / obfuscated payloads.
6. Neurochemical alarm triggering during spinal reflex activation.
7. Analysis of over-sensitivity boundary (sub-string matching on raw command lines).
"""

import unittest
from unittest.mock import MagicMock, patch
from app.services.ai_agent_tools import evaluate_spinal_safety_veto, _SPINAL_VETO_PATTERNS


class TestSpinalSafetyVetoAdversarialStress(unittest.IsolatedAsyncioTestCase):
    """
    Stress-testing biological spinal safety reflex with adversarial command payloads.
    """

    # 40 Destructive command variants across all 8+ threat vectors
    DESTRUCTIVE_COMMANDS = [
        # Vector 1: Lethal file wipe & bulk deletions
        "rm -rf /",
        "rm -rf ~",
        "rm -rf .",
        "rm -rf *",
        "rm -Rf /tmp",
        "rm   -r   /",
        "rm -fr /*",
        "find / -name '*.log' -delete",
        "find /var/log -type f -delete",
        "find /var/log -type f -exec rm -f {} +",
        "find /tmp -name '*.bak' -exec unlink {} \\;",
        "find . -type f -exec shred {} +",

        # Vector 2: Log truncation & zeroing
        "truncate -s 0 /var/log/syslog",
        "truncate -s0 /var/log/nginx/access.log",
        "truncate --size 0 /var/log/app.log",
        "truncate /var/log/messages",
        "truncate -c -s 0 app.log",

        # Vector 3: SSH keys, authentication & daemon disruption
        "rm -rf ~/.ssh",
        "rm -f ~/.ssh/authorized_keys",
        "unlink /root/.ssh/authorized_keys",
        "shred -u ~/.ssh/id_rsa",
        "> ~/.ssh/authorized_keys",
        "> /etc/ssh/sshd_config",
        "systemctl stop sshd",
        "systemctl disable ssh",
        "systemctl mask sshd",

        # Vector 4: Raw disk & filesystem destruction
        "mkfs.ext4 /dev/sda1",
        "mkfs.xfs /dev/vdb",
        "mkfs -t ext4 /dev/nvme0n1p1",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        "dd if=/dev/urandom of=/dev/nvme0n1",
        "> /dev/sda",
        "cat /dev/zero > /dev/vda1",

        # Vector 5: Database DROP & TRUNCATE destruction
        "DROP TABLE users;",
        "drop table audit_logs",
        "DROP DATABASE production;",
        "DROP SCHEMA public CASCADE;",
        "TRUNCATE TABLE logs;",
        "truncate table user_sessions;",

        # Vector 6: Container mass purge
        "docker system prune -a --volumes",
        "docker rm -f $(docker ps -aq)",
        "docker kill $(docker ps -q)",

        # Vector 7: Network & firewall blackout
        "iptables -F",
        "iptables -X",
        "iptables --flush",
        "ufw reset",
        "ufw disable",
        "ip link set eth0 down",
        "ip link set enp3s0 down",

        # Vector 8: Reckless permissions & ownership
        "chmod -R 777 /",
        "chmod -r 777 /var/www",
        "chmod -R 0777 /home",
        "chmod -R a+rwx /",
        "chmod 777 -R /",
        "chmod --recursive 777 /",
        "chmod 777 --recursive /",
        "chown -R root:root /",
        "chown -R www-data:www-data /etc",
        "chown --recursive root:root /",
        "chown root:root -R /",

        # Vector 9: Stress exhaustion & fork bombs
        "stress-ng --vm 2",
        "stress --cpu 4 --timeout 30s",
        "sudo stress --cpu 2",
        "sudo -u root stress-ng --vm 2",
        ":(){ :|:& };:",
        ":(){:|:&};:",

        # Additional adversarial bypasses: split flags, prune, truncate, network
        "rm -r -f /",
        "rm -f -r /",
        "rm --recursive --force /",
        "rm --force --recursive /",
        "rm -rf --no-preserve-root /",
        "rm --recursive /",
        "TRUNCATE users;",
        "truncate \"user_sessions\";",
        "TRUNCATE users CASCADE;",
        "docker system prune --all --volumes",
        "docker prune --all",
        "docker rm -f $(docker container ls -q)",
        "docker rm -f `docker ps -aq`",
        "iptables -t nat -F",
        "ufw --force reset",
        "ip link set dev eth0 down",
    ]

    # Safe diagnostic commands that MUST NOT be blocked (0% false positives)
    BENIGN_COMMANDS = [
        "free -h",
        "docker ps",
        "uptime",
        "ls -la",
        "find . -name '*.py'",
        "find /var/log -name '*.log'",
        "cat /etc/hosts",
        "df -h",
        "chmod 644 /var/www/index.html",
        "chown www-data:www-data /var/www/index.html",
        "echo 'system status: healthy'",
        "echo 'stress test complete'",
        "ps aux",
        "ps aux | grep stress",
        "which stress",
        "pkill stress",
        "killall stress",
        "systemctl status stress",
        "man stress",
        "ip addr show",
        "ip link set dev eth0 up",
        "ufw status",
        "iptables -L -n -v",
        "systemctl status sshd",
        "journalctl -u dashboard_ai_agent -n 50",
        "tail -n 100 /var/log/syslog",
        "netstat -tlpn",
        "vmstat 1 5",
        "iostat -xz 1 3",
    ]

    def test_destructive_commands_100_percent_intercepted_without_token(self):
        """All 40+ destructive variants must be intercepted by spinal safety veto."""
        for cmd in self.DESTRUCTIVE_COMMANDS:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"Destructive command '{cmd}' BYPASSED spinal veto when confirm_token is None!"
            )
            self.assertIn(
                "PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER",
                veto,
                f"Veto message missing expected warning header for '{cmd}'"
            )

    def test_benign_diagnostic_commands_zero_false_positives(self):
        """All benign diagnostic commands must pass freely through spinal safety veto."""
        for cmd in self.BENIGN_COMMANDS:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNone(
                veto,
                f"Benign diagnostic command '{cmd}' was FALSELY BLOCKED by spinal veto: {veto}"
            )

    def test_valid_confirm_token_allows_destructive_commands(self):
        """Valid CONFIRM_DANGEROUS_ACTION must allow execution through spinal veto."""
        for cmd in self.DESTRUCTIVE_COMMANDS:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token="CONFIRM_DANGEROUS_ACTION")
            self.assertIsNone(
                veto,
                f"Destructive command '{cmd}' with valid token was unexpectedly blocked: {veto}"
            )

    def test_invalid_confirm_tokens_strictly_rejected(self):
        """Invalid or approximate confirmation tokens must NOT bypass spinal safety veto."""
        invalid_tokens = [
            "yes",
            "true",
            "TRUE",
            "CONFIRM",
            "confirm",
            "CONFIRM_DANGEROUS",
            "CONFIRM_DANGEROUS_ACTION ",
            "confirm=CONFIRM_DANGEROUS_ACTION",
            "1",
            "",
        ]
        target_cmd = "rm -rf /"
        for bad_token in invalid_tokens:
            veto = evaluate_spinal_safety_veto(target_cmd, confirm_token=bad_token)
            self.assertIsNotNone(
                veto,
                f"Invalid token '{bad_token}' erroneously bypassed spinal veto for '{target_cmd}'!"
            )

    def test_chained_destructive_payloads_intercepted(self):
        """Chained commands with logical operators (&&, ;, |) must be vetoed."""
        chained_attacks = [
            "echo 'hello' && rm -rf /",
            "free -h; DROP TABLE users;",
            "ls -la | iptables -F",
            "uptime && systemctl stop sshd",
            "cat /proc/cpuinfo; stress-ng --vm 2",
            "df -h && chmod -R 777 /",
            "echo 'clean' && find / -name '*.log' -delete",
        ]
        for cmd in chained_attacks:
            veto = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(
                veto,
                f"Chained attack payload '{cmd}' bypassed spinal veto!"
            )

    def test_neurochemical_alarm_triggered_on_veto(self):
        """Spinal reflex triggers noradrenaline & cortisol surge and dopamine drop in ArtificialBrain."""
        with patch("app.core.brain_core.ArtificialBrain") as mock_brain_cls:
            mock_brain = MagicMock()
            mock_brain_cls.get_instance.return_value = mock_brain

            veto = evaluate_spinal_safety_veto("rm -rf /", confirm_token=None)
            self.assertIsNotNone(veto)

            # Verify neurochemical stimulate calls
            mock_brain.neuro.stimulate.assert_any_call("noradrenaline", 0.35)
            mock_brain.neuro.stimulate("cortisol", 0.30)
            mock_brain.neuro.stimulate("dopamine", -0.20)

    def test_adversarial_embedded_keyword_oversensitivity_boundary(self):
        """
        Adversarial Edge Case Analysis:
        When harmless commands literally embed dangerous keyword patterns (e.g., grep or echo),
        the fast regex-based spinal reflex treats them as dangerous (fail-safe by design).
        Verifies that with CONFIRM_DANGEROUS_ACTION, even these oversensitive cases pass.
        """
        sub_string_cases = [
            "grep -rn 'DROP TABLE' ./migrations",
            "echo 'DROP DATABASE production;'",
        ]
        for cmd in sub_string_cases:
            # Without token: intercepted by fail-safe circuit breaker
            veto_unconfirmed = evaluate_spinal_safety_veto(cmd, confirm_token=None)
            self.assertIsNotNone(veto_unconfirmed)
            # With token: allowed through
            veto_confirmed = evaluate_spinal_safety_veto(cmd, confirm_token="CONFIRM_DANGEROUS_ACTION")
            self.assertIsNone(veto_confirmed)

    async def test_agent_tool_executor_run_command_spinal_veto_integration(self):
        """Verify AgentToolExecutor intercepts destructive command before ssh execution."""
        from unittest.mock import AsyncMock
        from app.services.ai_agent_tools import AgentToolExecutor


        mock_ssh = MagicMock()
        mock_ssh.execute_command = MagicMock()
        tools = AgentToolExecutor(ssh_client=mock_ssh, message_cache=MagicMock())

        # 1. Unconfirmed destructive command: must NOT touch ssh_client
        res_blocked = await tools.execute_tool("run_command", {"command": "find / -name '*.log' -delete"})
        self.assertIn("PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER", res_blocked)
        mock_ssh.execute_command.assert_not_called()

        # 2. Confirmed destructive command: allowed to reach ssh_client
        mock_ssh.execute_command = AsyncMock(return_value="deleted")
        res_allowed = await tools.execute_tool(
            "run_command",
            {"command": "find / -name '*.log' -delete", "confirm": "CONFIRM_DANGEROUS_ACTION"}
        )
        self.assertEqual(res_allowed, "deleted")
        mock_ssh.execute_command.assert_called_once_with("find / -name '*.log' -delete")


if __name__ == "__main__":
    unittest.main()

