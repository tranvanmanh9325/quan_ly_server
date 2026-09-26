"""
test_adversarial_cwe184_ngrok.py — Empirical Adversarial Challenge for Ngrok URL Validation.

Milestone M9 — Challenger 2 (URL Security & RFC 3986 Challenger).
Exhaustively tests _is_valid_ngrok_url in network_service.py against:
- CodeQL CWE-184 (Incomplete URL Substring Sanitization)
- RFC 3986 Host Authority Boundaries
- WHATWG / Browser URL parser differentials (Backslash confusion)
- Subdomain spoofing & hyphen prefixing
- Path, query, and userinfo injection
- Scheme evasion & protocol whitelisting
- Port out-of-range / non-numeric port exceptions
- Control characters, null bytes, and percent-encoding attacks
- Positive verification of legitimate ngrok tunnels (Zero False Positives)
"""

import unittest
from typing import List, Tuple

from app.services.network_service import _is_valid_ngrok_url, is_valid_ngrok_url


class TestAdversarialNgrokValidation(unittest.TestCase):
    """Empirical adversarial test harness evaluating 70+ attack vectors against _is_valid_ngrok_url."""

    # -------------------------------------------------------------------------
    # 1. Subdomain Spoofing Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_subdomain_spoofing_rejected(self):
        vectors = [
            "https://ngrok.io.evil.com",
            "https://ngrok.io.attacker.org",
            "https://ngrok-free.app.evil.com",
            "https://ngrok-free.app.attacker.org",
            "https://ngrok.app.evil.com",
            "https://ngrok-free.dev.attacker.com",
            "https://ngrok.dev.evilcorp.com",
            "http://0.tcp.ngrok.io.evil.com:12345",
            "https://sub.ngrok.io.attacker.io",
            "https://tunnel.ngrok-free.app.legit.com",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Subdomain spoofing vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 2. Hyphen Prefixing & Domain Collision Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_hyphen_prefixing_rejected(self):
        vectors = [
            "https://fake-ngrok.io",
            "https://evil-ngrok-free.app",
            "https://my-ngrok.app",
            "https://ngrok-free-app.com",
            "https://notngrok.io",
            "https://ngrok.io-fake.com",
            "https://evilngrok.io",
            "https://ngrok.evil.app",
            "https://fake-ngrok-free.dev",
            "https://myngrok.dev",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Hyphen prefixing / domain collision should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 3. Path Injection Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_path_injection_rejected(self):
        vectors = [
            "https://evil.com/ngrok.io",
            "https://evil.com/sub.ngrok-free.app",
            "https://attacker.org/https://sub.ngrok.io",
            "https://legit.com/path?url=https://ngrok.io",
            "https://attacker.com/v1/tunnel/ngrok.app",
            "https://attacker.com/ngrok-free.dev/test",
            "https://evil.com/0.tcp.ngrok.io:12345",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Path injection vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 4. Query and Fragment / Anchor Injection Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_query_and_fragment_injection_rejected(self):
        vectors = [
            "https://attacker.com/?q=ngrok.io",
            "https://attacker.com/?target=https://sub.ngrok-free.app",
            "https://evil.com/#ngrok.io",
            "https://evil.com/#https://sub.ngrok.io",
            "https://attacker.org/test?dummy=ngrok.dev#anchor",
            "https://evil.com?target=sub.ngrok.io",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Query or fragment injection vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 5. Userinfo / Credential Injection Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_userinfo_injection_rejected(self):
        vectors = [
            "https://ngrok.io@evil.com",
            "https://ngrok-free.app@attacker.org",
            "https://sub.ngrok.io:token@evil.com",
            "https://admin:ngrok.io@evil.com/",
            "https://user@ngrok.io.evil.com",
            "tcp://0.tcp.ngrok.io@evil.com:12345",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Userinfo injection spoofing vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 6. Scheme Evasion Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_scheme_evasion_rejected(self):
        vectors = [
            "ftp://0.tcp.ap.ngrok.io",
            "ftp://sub.ngrok-free.app",
            "javascript:alert(1)//ngrok.io",
            "javascript://ngrok-free.app/%0aalert(1)",
            "data:text/html,<script>alert('ngrok.io')</script>",
            "file:///ngrok.io",
            "gopher://sub.ngrok.io:70",
            "ssh://0.tcp.ngrok.io:22",
            "ws://sub.ngrok.io",
            "wss://sub.ngrok.io",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Non-whitelisted scheme vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 7. Backslash & WHATWG Parser Differential Vectors (Adversarial stress test)
    # -------------------------------------------------------------------------
    def test_backslash_differential_rejected(self):
        vectors = [
            r"https://evil.com\sub.ngrok.io",
            r"https://evil.com\\sub.ngrok.io",
            r"https://evil.com\.ngrok.io",
            r"https://evil.com\fake.ngrok.io",
            r"https://evil.com\@sub.ngrok.io",
            r"https://user:pass@evil.com\sub.ngrok.io",
            r"https://sub.ngrok.io:8080\evil.com",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Backslash differential evasion should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 8. Encoded Delimiters, Null Bytes & Control Characters (Adversarial stress test)
    # -------------------------------------------------------------------------
    def test_encoded_and_control_chars_rejected(self):
        vectors = [
            "https://evil.com%5csub.ngrok.io",
            "https://evil.com%2fsub.ngrok.io",
            "https://evil.com%23sub.ngrok.io",
            "https://evil.com%3fsub.ngrok.io",
            "https://sub\x00.ngrok.io",
            "https://sub .ngrok.io",
            "https://sub\t.ngrok.io",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Encoded delimiter or control character vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 9. Malformed Syntax, Boundary & Port Vectors (Must be REJECTED)
    # -------------------------------------------------------------------------
    def test_malformed_syntax_rejected(self):
        vectors = [
            "",
            None,
            "   ",
            "not_a_url",
            "https://",
            "https:///",
            "sub.ngrok.io",
            "//sub.ngrok.io",
            "https://192.168.1.100",
            "https://[::1]",
            "https://ngr\u03bfk.io",
            "https://sub.ngrok.io.",
            "tcp://0.tcp.ngrok.io:invalidport",
            "tcp://0.tcp.ngrok.io:999999",
        ]
        for url in vectors:
            with self.subTest(url=url):
                self.assertFalse(
                    _is_valid_ngrok_url(url),
                    f"Malformed or boundary vector should be rejected: {url}",
                )

    # -------------------------------------------------------------------------
    # 10. Legitimate Ngrok URLs (Zero False Positives — MUST PASS)
    # -------------------------------------------------------------------------
    def test_legitimate_ngrok_urls_accepted(self):
        legit_cases = [
            "https://sub.ngrok-free.app",
            "http://sub.ngrok-free.app",
            "https://my-service.ngrok.io",
            "http://my-service.ngrok.io:8080",
            "tcp://0.tcp.ap.ngrok.io:12345",
            "tcp://1.tcp.ngrok.io:22222",
            "tcp://4.tcp.eu.ngrok.io:19999",
            "https://api.ngrok.app",
            "http://dev-tunnel.ngrok-free.dev",
            "https://admin.ngrok.dev",
            "https://ngrok.io",
            "https://ngrok-free.app",
            "https://ngrok.app",
            "https://ngrok-free.dev",
            "https://ngrok.dev",
            "https://a.b.c.subdomain.ngrok-free.app",
            "https://app-1234.ngrok-free.app/path/to/resource",
            "https://my-app.ngrok.io/?query=1&param=test",
            "https://sub.ngrok.io/#section1",
            "https://sub.ngrok.io:443/api/v1/status",
            "https://user:pass@sub.ngrok-free.app",
        ]
        for url in legit_cases:
            with self.subTest(url=url):
                self.assertTrue(
                    _is_valid_ngrok_url(url),
                    f"Legitimate URL was incorrectly rejected (false positive): {url}",
                )
                self.assertTrue(
                    is_valid_ngrok_url(url),
                    f"Public alias should also accept legitimate URL: {url}",
                )


if __name__ == "__main__":
    unittest.main()
