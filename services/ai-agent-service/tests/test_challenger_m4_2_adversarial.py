"""
test_challenger_m4_2_adversarial.py — Milestone 4 Adversarial Stress Test Suite.

Author: Challenger 2 (teamwork_preview_challenger_m4_2)
Role: Empirical Challenger (critic, specialist)
Target: Commit 59f986d (Gorilla RAT Scoped Tools Token Budget & Action Risk Tri-Tier Gating)

Challenger Objectives:
1. Adversarial Substring Isolation Stress Test (30+ queries):
   - Trap words with short substrings ('laptop', 'zip', 'gzip', 'download', 'pdf',
     'portugal', 'freestyle', 'psql', 'cpu_stress', 'swapper', 'ramdom', 'sshpass', etc.)
   - Ensure false-positive server/cluster activation does NOT occur via raw substrings.
2. Token Budget & Priority Pruning Stress Test (30+ complex multi-domain queries):
   - Stress test combinatorial queries spanning server, media, weather, archive, facebook, web, task.
   - Strictly verify: tool schema token budget <= 700 tokens across 100% of queries.
   - Strictly verify: active tool count <= 8 across 100% of queries.
3. Action Risk Tri-Tier Gating Stress Test (Pipe, Compound, Redirection, Chained):
   - Single pure diagnostic commands -> TIER_1_SAFE
   - Pure diagnostic pipes ('ps aux | grep ...', 'top ... | head ...') -> TIER_1_SAFE
   - Compound commands chaining diagnostic + modifying ('free -m; docker restart ...') -> MUST ELEVATE TO TIER_2_REVERSIBLE (NOT TIER_1_SAFE)
   - Compound commands with redirection write ('ps aux > /tmp/out') -> MUST ELEVATE TO TIER_2_REVERSIBLE
   - Compound commands chaining diagnostic + lethal ('free -m; rm -rf /') -> MUST BE TIER_3_LETHAL
"""
import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
    infer_default_diagnostic_command,
    evaluate_spinal_safety_veto,
)


class TestChallengerM4AdversarialSuite(unittest.TestCase):
    """Empirical Adversarial Stress Suite for Milestone 4."""

    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.agent = AiAgentService(
            llm_router=self.mock_llm,
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )
        self.tools = AgentToolExecutor(ssh_client=self.mock_ssh, message_cache=self.mock_cache)

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1: Adversarial Substring Isolation Stress Test
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_substring_traps_do_not_trigger_false_server_cluster(self):
        """
        Verify that words containing short server keywords as substrings
        do not trigger the server cluster (which adds server-only tools like
        get_server_active_sessions, server_capture_screenshot).
        """
        substring_traps = [
            # ("laptop", "top")
            ("mở laptop lên xem tài liệu", False),
            ("mua laptop mới cho văn phòng", False),
            # ("zip", "ip")
            ("giải nén file data.zip này", False),
            ("tệp tin zip này bị hỏng rồi", False),
            # ("gzip", "ip")
            ("nén tệp tin theo chuẩn gzip", False),
            # ("download", "load")
            ("download file hướng dẫn sử dụng", False),
            ("tôi muốn download tài liệu này", False),
            # ("pdf", "df")
            ("đọc file pdf đính kèm", False),
            ("chuyển đổi tài liệu sang pdf", False),
            # ("portugal", "port")
            ("du lịch portugal mùa nào đẹp nhất", False),
            ("đội tuyển portugal đá bóng hôm nay", False),
            # ("freestyle", "free")
            ("nhảy freestyle rất điêu luyện", False),
            ("bơi freestyle 100m", False),
            # ("psql", "ps")
            ("tài liệu psql cheat sheet", False),
            # ("ramdom", "ram")
            ("chọn ramdom một số may mắn", False),
            # ("swapper", "swap")
            ("thuật toán swapper trong đồ họa", False),
            # ("sshpass", "ssh")
            ("hướng dẫn cài đặt sshpass", False),
        ]

        server_only_markers = {"get_server_active_sessions", "server_capture_screenshot"}

        for query, _ in substring_traps:
            scoped = self.tools._resolve_scoped_tool_names(query)
            # If server cluster was falsely triggered, server_only_markers would be present
            overlap = scoped.intersection(server_only_markers)
            self.assertEqual(
                len(overlap), 0,
                f"Query '{query}' falsely triggered server cluster tools: {overlap}"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2: 35+ Combinatorial & Multi-Domain Queries Token Budget Stress Test
    # ──────────────────────────────────────────────────────────────────────────

    def test_02_strictly_enforce_700_tokens_and_max_8_tools_across_35_queries(self):
        """
        Stress test 35+ diverse, combinatorial, multi-domain and edge-case queries.
        Every query MUST strictly satisfy:
        1. 2 <= len(tools) <= 8 (Priority Pruning)
        2. json_tokens <= 700.0 (Groq 8,000 TPM safety budget)
        """
        adversarial_queries = [
            # Single domain standard & edge cases
            "kiểm tra ram máy chủ",
            "xem thời tiết hôm nay ra sao",
            "tải video tiktok này https://vt.tiktok.com/ZS12345/",
            "tải video youtube https://youtu.be/dQw4w9WgXcQ",
            "giải nén file zip data.zip",
            "mở tệp nén rar backup.rar tìm mật khẩu",
            "xem tin nhắn facebook messenger gần đây",
            "tìm kiếm google thông tin ubuntu 26.04 lts",
            "nhớ ngày mai 8h sáng nộp báo cáo",
            "thời tiết bựa ni ở vinh răng em",
            # Dual-domain overlaps
            "kiểm tra ram máy chủ và xem thời tiết hà nội",
            "xem thời tiết hôm nay và tải video tiktok https://tiktok.com/123",
            "tải video facebook https://fb.watch/xyz và kiểm tra server docker",
            "giải nén file zip này rồi lưu task nhớ mai kiểm tra",
            "xem tin nhắn messenger và tìm kiếm google tin tức mới",
            "kiểm tra cpu máy chủ rồi tìm kiếm google cách tối ưu",
            "thời tiết sài gòn thế nào, tiện thể nhớ mai mang ô",
            "tải video youtube rồi giải nén tệp archive.7z",
            # Triple-domain overlaps
            "kiểm tra ram cpu máy chủ, xem thời tiết và tải video tiktok",
            "xem tin nhắn facebook, tìm kiếm google và ghi nhớ task mới",
            "giải nén file zip, kiểm tra server load và xem thời tiết vinh",
            "tải video fb.watch, kiểm tra docker container và lưu task mai xem",
            # Quadruple & multi-domain combinatorial stress cases
            "kiểm tra server, ram, docker, xem thời tiết, tải video tiktok https://tiktok.com/v123 và xem tin nhắn facebook",
            "kiểm tra máy chủ cpu ram disk, giải nén file rar, tìm kiếm google và ghi nhớ việc cần làm",
            "thời tiết đà nẵng, tải clip youtube, đọc archive zip, rep tin nhắn fb và kiểm tra uptime server",
            "vừa tải video tiktok, vừa xem thời tiết, vừa check tin nhắn messenger và kiểm tra ram server",
            # Extreme all-cluster combo
            "kiểm tra server ram docker htop uptime, xem thời tiết mưa bão, tải video tiktok youtube fb.watch, "
            "giải nén file zip rar 7z bẻ khóa mật khẩu, nhắn tin facebook messenger, tìm kiếm google web click điền form, "
            "và ghi nhớ task hoàn thành",
            # Substring trap mixtures
            "mở laptop xem thời tiết và download file zip hướng dẫn kèm video youtube",
            "đọc file pdf này trên server rồi tải clip facebook về máy",
            "chuyến đi portugal freestyle cần xem thời tiết và ghi nhớ lịch trình",
            "kiểm tra psql database tải cpu_stress và gửi tin nhắn messenger",
            # Noise & unicode stress cases
            "   ??? !!! kiểm tra RAM, CPU, DISK ... và thời tiết ???   ",
            "TẢI VIDEO TIKTOK https://vt.tiktok.com/abc VÀ KIỂM TRA SERVER NGAY LẬP TỨC",
            "bựa ni trời mưa to quá, server có bị chi không em, tải hộ anh cái video ni luôn",
            "giải nén gấp file zip password khó, check giùm anh tin nhắn fb của khách",
            "tìm kiếm google tài liệu linux rồi nhớ lại tối nay đọc",
        ]

        self.assertGreaterEqual(len(adversarial_queries), 35, "Must test at least 35 adversarial queries")

        budget_violations = []
        count_violations = []

        for q in adversarial_queries:
            tools = self.tools.build_tools(query=q)
            dumped = json.dumps(tools, ensure_ascii=False)
            approx_tokens = len(dumped) / 3.5

            if len(tools) < 2 or len(tools) > 8:
                count_violations.append((q, len(tools)))

            if approx_tokens > 700.0:
                tool_names = [t["function"]["name"] for t in tools]
                budget_violations.append((q, len(tools), approx_tokens, tool_names))

        # Assert no tool count violations
        self.assertEqual(
            len(count_violations), 0,
            f"Tool count violated (must be 2-8 tools): {count_violations}"
        )

        # Assert no token budget violations
        self.assertEqual(
            len(budget_violations), 0,
            f"Token budget exceeded > 700 tokens on {len(budget_violations)} queries! Violations:\n" +
            "\n".join([f"  - Query: '{v[0][:50]}...' -> {v[1]} tools, {v[2]:.1f} tokens: {v[3]}" for v in budget_violations])
        )

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3: Action Risk Tri-Tier Gating Stress Test (Pipe & Compound Commands)
    # ──────────────────────────────────────────────────────────────────────────

    def test_03_pure_diagnostic_pipes_remain_tier_1_safe(self):
        """
        Chained commands where EVERY pipe segment is purely diagnostic (read-only)
        must remain classified as ACTION_TIER_1_SAFE.
        """
        safe_pipes = [
            "ps aux | grep python",
            "top -b -n 1 | head -n 15",
            "cat /proc/cpuinfo | grep 'model name'",
            "docker ps -a | grep Exited",
            "netstat -tuln | grep 8080",
            "journalctl -n 50 --no-pager | tail -n 10",
            "cat /etc/os-release | grep PRETTY_NAME",
            "df -h | grep '/dev/sda'",
            "free -m | grep Mem",
            "ss -tulpn | grep LISTEN",
        ]
        for cmd in safe_pipes:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_1_SAFE,
                f"Pure diagnostic pipe '{cmd}' must be TIER_1_SAFE, got '{tier}'"
            )

    def test_04_compound_commands_with_mutations_must_elevate_to_tier_2(self):
        """
        ADVERSARIAL STRESS TEST:
        Compound commands (chained via ;, &&, ||) where a diagnostic command is followed
        or preceded by a modifying/operational command MUST NOT be classified as TIER_1_SAFE.
        They must be elevated to ACTION_TIER_2_REVERSIBLE (or blocked).
        """
        mutating_compounds = [
            # Diagnostic followed by container restart
            "free -m; docker restart dashboard_ai_agent",
            "uptime && docker restart dashboard_db",
            # Diagnostic followed by service restart
            "systemctl status nginx; systemctl restart nginx",
            "df -h && systemctl reload nginx",
            # Diagnostic followed by file creation/touch
            "uptime && touch /tmp/maintenance_flag",
            "free -h; mkdir -p /tmp/scratch_dir",
            # Diagnostic followed by copy/backup
            "cat /etc/nginx/nginx.conf; cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf_bak",
            # Diagnostic followed by state modification
            "ls -la; systemctl stop redis",
        ]
        for cmd in mutating_compounds:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_2_REVERSIBLE,
                f"Compound mutating command '{cmd}' MUST NOT be TIER_1_SAFE! Got '{tier}'"
            )

    def test_05_compound_redirection_commands_must_not_be_tier_1(self):
        """
        ADVERSARIAL STRESS TEST:
        Commands using redirection (>, >>) to write or overwrite files must NOT
        be classified as TIER_1_SAFE read-only commands.
        """
        redirection_writes = [
            "ps aux > /tmp/ps_output.txt",
            "cat /proc/cpuinfo > /tmp/cpu.log",
            "df -h >> /var/log/disk_monitor.log",
            "free -m > /tmp/mem.txt",
        ]
        for cmd in redirection_writes:
            tier = classify_command_risk(cmd)
            self.assertNotEqual(
                tier, ACTION_TIER_1_SAFE,
                f"Redirection write command '{cmd}' MUST NOT be classified as TIER_1_SAFE read-only! Got '{tier}'"
            )

    def test_06_compound_commands_with_lethal_payload_must_be_tier_3(self):
        """
        ADVERSARIAL STRESS TEST:
        Chained commands containing lethal payloads (rm -rf /, DROP DATABASE, mkfs...)
        prefixed with innocent diagnostic commands MUST be classified as ACTION_TIER_3_LETHAL.
        """
        lethal_compounds = [
            "free -m; rm -rf /",
            "uptime && rm -rf ~",
            "df -h | dd if=/dev/zero of=/dev/sda",
            "echo 'diagnostic'; DROP DATABASE quan_ly_server",
            "cat /etc/hosts && mkfs.ext4 /dev/sda1",
            "docker ps; docker system prune -a --volumes",
            "ls -la; iptables -F",
        ]
        for cmd in lethal_compounds:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_3_LETHAL,
                f"Lethal compound command '{cmd}' MUST be TIER_3_LETHAL, got '{tier}'"
            )
            veto = evaluate_spinal_safety_veto(cmd)
            self.assertIsNotNone(
                veto,
                f"Lethal compound command '{cmd}' must be vetoed by spinal safety"
            )


if __name__ == "__main__":
    unittest.main()
