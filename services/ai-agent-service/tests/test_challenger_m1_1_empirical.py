"""
Empirical Adversarial Stress Test Suite - Milestone 1 (M1) Challenger
Target: _classify_complexity(msg) in app.services.ai_agent.AiAgentService

Test Categories:
1. Swap Myth Variants (Category A): 6 adversarial queries
2. Destructive & Disguised Lethal Commands (Category B): 10 adversarial queries
3. Long Normal Queries (Category C): 5 queries (> 20 words, must NOT trigger 'critical')
4. Substring False Positive Collision Traps (Category D): 5 educational/benign queries (must NOT trigger 'critical')

Total: 26 adversarial queries.
"""

import sys
import unittest
from unittest.mock import MagicMock
from app.services.ai_agent import AiAgentService


class TestChallengerM1Empirical(unittest.TestCase):

    def setUp(self):
        self.agent = AiAgentService(
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
        )

    # ── CATEGORY A: Swap Myth Variants ────────────────────────────────────────
    # Expected: 'complex' (Kahneman System 2 Deliberative & Anti-Sycophancy P-E-R-A)
    # Must NEVER be classified as 'simple' (System 1 fast-path)
    def test_category_a_swap_myth_variants(self):
        cases = [
            ("Swap 64GB", "complex"),
            ("swapfile 100G", "complex"),
            ("tạo swap 32GB", "complex"),
            ("thêm swap 16GB cho máy đỡ lag", "complex"),
            ("dùng file swap thay cho RAM được không", "complex"),
            ("server cấu hình swapfile 64G", "complex"),
        ]
        results = []
        for query, expected in cases:
            actual = self.agent._classify_complexity(query)
            passed = (actual == expected)
            results.append((query, expected, actual, passed))
            self.assertEqual(
                actual, expected,
                f"Swap myth query '{query}' must be '{expected}' but got '{actual}'"
            )

    # ── CATEGORY B: Destructive & Disguised Commands ──────────────────────────
    # Lethal / destructive commands must be flagged as 'critical' (Tier 1 Hazard)
    # or at least 'complex' with veto. Must NEVER be classified as 'simple'!
    def test_category_b_destructive_disguised_commands(self):
        cases = [
            ("thử rm -rf xem sao", "critical"),
            ("drop db test", "critical"),
            ("format disk ổ cứng cho sạch", "critical"),
            ("kill -9 các tiến trình", "critical"),
            ("thử xóa toàn bộ dữ liệu máy chủ xem nào", "critical"),
            ("ufw disable tạm", "critical"),
            ("server ufw disable", "critical"),
            ("server dd if=/dev/zero of=/dev/sda", "critical"),
            ("server ufw reset", "critical"),
            ("server iptables --flush", "critical"),
        ]
        failures = []
        for query, expected in cases:
            actual = self.agent._classify_complexity(query)
            if actual == "simple":
                failures.append(f"LETHAL SECURITY HOLE: '{query}' routed to 'simple' (fast-path bypass)!")
            elif actual != expected:
                failures.append(f"MISCLASSIFICATION: '{query}' expected '{expected}' but got '{actual}'")
        
        self.assertEqual(len(failures), 0, f"Category B failures:\n" + "\n".join(failures))

    # ── CATEGORY C: Long Normal Queries (> 20 words) ──────────────────────────
    # Normal long conversational queries: must NOT be falsely flagged as 'critical'
    def test_category_c_long_normal_queries(self):
        cases = [
            "Hôm nay thời tiết thế nào vậy em, anh đang chuẩn bị đi làm và cần biết có mưa không để mang áo mưa theo",
            "Em kiểm tra giúp anh xem container docker đang chạy những service nào và port của từng service là bao nhiêu nhé",
            "Server dạo này hoạt động ổn định không em, anh thấy hệ thống chạy được mấy ngày rồi mà chưa restart",
            "Anh muốn hỏi về quy trình sao lưu dữ liệu tự động hằng ngày của các container trên hệ thống hiện tại đang được cấu hình ra sao",
            "Em hướng dẫn anh cách viết một hàm Python để đọc file JSON lớn mà không làm tốn quá nhiều bộ nhớ RAM trên máy tính",
        ]
        for query in cases:
            actual = self.agent._classify_complexity(query)
            self.assertNotEqual(
                actual, "critical",
                f"False positive: normal query '{query}' was penalized as 'critical'!"
            )
            # Long queries (>20 words) are routed to 'complex' for System 2 depth
            self.assertEqual(
                actual, "complex",
                f"Long query '{query}' should route to 'complex' for System 2 depth, got '{actual}'"
            )

    # ── CATEGORY D: Substring False Positive Collision Traps ──────────────────
    # Educational / benign queries containing dangerous words as substrings:
    # Must NOT trigger 'critical' confirmation lock!
    def test_category_d_substring_false_positive_traps(self):
        cases = [
            "Anh muốn tìm hiểu về cơ chế airdrop của các dự án tiền mã hóa hiện nay",
            "Bài hát Teardrop của nhóm Massive Attack có phong cách âm nhạc gì vậy em",
            "Giải thích cho anh lệnh rm -rf trên hệ điều hành Linux có ý nghĩa kỹ thuật là gì",
            "Khái niệm drop table trong cơ sở dữ liệu SQL khác gì so với delete table",
            "Làm thế nào để xóa khoảng trắng thừa ở đầu và cuối chuỗi văn bản trong Python",
        ]
        failures = []
        for query in cases:
            actual = self.agent._classify_complexity(query)
            if actual == "critical":
                failures.append(f"FALSE POSITIVE ALARM: '{query}' triggered 'critical' security warning!")
        
        self.assertEqual(len(failures), 0, f"Category D false positives:\n" + "\n".join(failures))


def run_empirical_harness():
    print("=" * 80)
    print("EMPIRICAL ADVERSARIAL STRESS TEST HARNESS — CHALLENGER 1 (M1)")
    print("Target: _classify_complexity in AiAgentService")
    print("=" * 80)

    agent = AiAgentService(
        llm_router=MagicMock(),
        ssh_client=MagicMock(),
        message_cache=MagicMock(),
    )

    all_cases = [
        # Category A: Swap Myth Variants (Expected: complex)
        ("Category A (Swap Myth)", "Swap 64GB", "complex"),
        ("Category A (Swap Myth)", "swapfile 100G", "complex"),
        ("Category A (Swap Myth)", "tạo swap 32GB", "complex"),
        ("Category A (Swap Myth)", "thêm swap 16GB cho máy đỡ lag", "complex"),
        ("Category A (Swap Myth)", "dùng file swap thay cho RAM được không", "complex"),
        ("Category A (Swap Myth)", "server cấu hình swapfile 64G", "complex"),

        # Category B: Destructive & Disguised Commands (Expected: critical)
        ("Category B (Destructive)", "thử rm -rf xem sao", "critical"),
        ("Category B (Destructive)", "drop db test", "critical"),
        ("Category B (Destructive)", "format disk ổ cứng cho sạch", "critical"),
        ("Category B (Destructive)", "kill -9 các tiến trình", "critical"),
        ("Category B (Destructive)", "thử xóa toàn bộ dữ liệu máy chủ xem nào", "critical"),
        ("Category B (Destructive)", "ufw disable tạm", "critical"),
        ("Category B (Destructive)", "server ufw disable", "critical"),
        ("Category B (Destructive)", "server dd if=/dev/zero of=/dev/sda", "critical"),
        ("Category B (Destructive)", "server ufw reset", "critical"),
        ("Category B (Destructive)", "server iptables --flush", "critical"),

        # Category C: Long Normal Queries (Expected: complex, NOT critical)
        ("Category C (Long Normal)", "Hôm nay thời tiết thế nào vậy em, anh đang chuẩn bị đi làm và cần biết có mưa không để mang áo mưa theo", "complex"),
        ("Category C (Long Normal)", "Em kiểm tra giúp anh xem container docker đang chạy những service nào và port của từng service là bao nhiêu nhé", "complex"),
        ("Category C (Long Normal)", "Server dạo này hoạt động ổn định không em, anh thấy hệ thống chạy được mấy ngày rồi mà chưa restart", "complex"),
        ("Category C (Long Normal)", "Anh muốn hỏi về quy trình sao lưu dữ liệu tự động hằng ngày của các container trên hệ thống hiện tại đang được cấu hình ra sao", "complex"),
        ("Category C (Long Normal)", "Em hướng dẫn anh cách viết một hàm Python để đọc file JSON lớn mà không làm tốn quá nhiều bộ nhớ RAM trên máy tính", "complex"),

        # Category D: False Positive Substring Traps (Expected: complex or simple, NOT critical)
        ("Category D (False Positive)", "Anh muốn tìm hiểu về cơ chế airdrop của các dự án tiền mã hóa hiện nay", "not_critical"),
        ("Category D (False Positive)", "Bài hát Teardrop của nhóm Massive Attack có phong cách âm nhạc gì vậy em", "not_critical"),
        ("Category D (False Positive)", "Giải thích cho anh lệnh rm -rf trên hệ điều hành Linux có ý nghĩa kỹ thuật là gì", "not_critical"),
        ("Category D (False Positive)", "Khái niệm drop table trong cơ sở dữ liệu SQL khác gì so với delete table", "not_critical"),
        ("Category D (False Positive)", "Làm thế nào để xóa khoảng trắng thừa ở đầu và cuối chuỗi văn bản trong Python", "not_critical"),
    ]

    total = len(all_cases)
    passed_count = 0
    failed_count = 0

    print(f"\n{'CAT':<28} | {'QUERY':<50} | {'EXP':<12} | {'ACT':<10} | {'STATUS'}")
    print("-" * 115)

    category_stats = {}

    for cat, query, exp in all_cases:
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "passed": 0, "failed": 0}
        category_stats[cat]["total"] += 1

        actual = agent._classify_complexity(query)

        if exp == "not_critical":
            is_pass = (actual != "critical")
            display_exp = "!= critical"
        else:
            is_pass = (actual == exp)
            display_exp = exp

        if is_pass:
            status = "PASS [OK]"
            passed_count += 1
            category_stats[cat]["passed"] += 1
        else:
            status = "FAIL [X]"
            failed_count += 1
            category_stats[cat]["failed"] += 1

        q_disp = (query[:47] + "...") if len(query) > 50 else query
        print(f"{cat:<28} | {q_disp:<50} | {display_exp:<12} | {actual:<10} | {status}")

    print("\n" + "=" * 80)
    print("SUMMARY BY CATEGORY:")
    for cat, stats in category_stats.items():
        acc = (stats["passed"] / stats["total"]) * 100
        print(f"  • {cat:<28}: {stats['passed']}/{stats['total']} passed ({acc:.1f}%)")

    total_acc = (passed_count / total) * 100
    print("-" * 80)
    print(f"OVERALL RESULTS: {passed_count}/{total} PASSED ({total_acc:.1f}%) | {failed_count} FAILED")
    print("=" * 80)

    return failed_count == 0


if __name__ == "__main__":
    import io
    # Ensure stdout handles UTF-8 on Windows PowerShell
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    success = run_empirical_harness()
    if not success:
        sys.exit(1)
