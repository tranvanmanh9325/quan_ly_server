"""
Adversarial Empirical Verification Suite for Deep Research Capability (R3 & Acceptance Criteria).
Author: Challenger 2 (teamwork_preview_challenger) - Empirical Challenger & Adversarial Verifier.

Target of Verification:
1. Researcher Agent query variations generation (>= 3 distinct queries from diverse technical angles).
2. Google Search tool invocation count (browser_search_google >= 3 calls with distinct queries).
3. Web navigation & text extraction (browser_navigate & browser_get_text live content ingestion).
4. Citation URL validity (strict http/https validation, deduplication, rejection of relative/malformed/placeholder links).
5. Robust fallback & zero-crash resilience against:
   - Google CAPTCHA detection
   - Search network connection & read timeouts
   - Search HTTP 500 / internal errors
   - Empty search results (zero organic hits)
   - Navigation HTTP 404 / 500 / 45s timeout
   - Missing or None browser_agent
"""

import asyncio
import json
import re
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.teamwork_engine import TeamworkEngine, TeamworkResult
from app.services.browser_agent import BrowserAgentService


class TestChallengerDeepResearchEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial & Empirical verification test suite for Teamwork Deep Research.
    """

    async def asyncSetUp(self) -> None:
        self.mock_llm_router = MagicMock()
        self.mock_llm_router.complete = AsyncMock()

        self.mock_browser_agent = MagicMock()
        self.mock_browser_agent.browser_search_google = AsyncMock()
        self.mock_browser_agent.browser_navigate = AsyncMock()
        self.mock_browser_agent.browser_get_text = AsyncMock()

        self.mock_tool_executor = MagicMock()
        self.mock_tool_executor.browser_agent = self.mock_browser_agent

        self.engine = TeamworkEngine(
            llm_router=self.mock_llm_router,
            tool_executor=self.mock_tool_executor,
            default_model="llama-3.3-70b-versatile",
        )

    def _make_llm_response(self, text: str) -> Dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": text,
                    }
                }
            ]
        }

    # ──────────────────────────────────────────────────────────────────────────
    # CHALLENGE 1: QUERY VARIATIONS & MULTI-ANGLE DIVERSITY
    # ──────────────────────────────────────────────────────────────────────────

    async def test_ch1_01_llm_clean_json_produces_three_diverse_queries(self) -> None:
        """Verify normal LLM JSON response returns >= 3 distinct technical queries."""
        task = "Tối ưu hóa TCP window scaling và BBR congestion control"
        queries_raw = [
            "tcp window scaling BBR congestion control official documentation RFC",
            "linux kernel tcp_bbr sysctl production best practices tuning",
            "bbr bufferbloat packet loss latency troubleshooting edge cases",
        ]
        self.mock_llm_router.complete.return_value = self._make_llm_response(json.dumps(queries_raw))

        queries = await self.engine._generate_search_queries(task)

        self.assertEqual(len(queries), 3)
        self.assertEqual(len(set(queries)), 3, "Queries must be strictly distinct")
        # Check diverse technical angles
        self.assertTrue(any("rfc" in q.lower() or "documentation" in q.lower() for q in queries))
        self.assertTrue(any("production" in q.lower() or "tuning" in q.lower() for q in queries))
        self.assertTrue(any("troubleshooting" in q.lower() or "edge cases" in q.lower() for q in queries))

    async def test_ch1_02_llm_returns_markdown_fences_handled_cleanly(self) -> None:
        """Verify model returning markdown ```json ... ``` code fence is properly stripped."""
        task = "Thiết lập Zero-downtime deployment Kubernetes"
        raw_markdown = (
            "```json\n"
            "[\n"
            "  \"kubernetes rolling update zero downtime architecture\",\n"
            "  \"k8s readiness probe preStop hook best practices\",\n"
            "  \"kubernetes 502 bad gateway during rollout edge cases\"\n"
            "]\n"
            "```"
        )
        self.mock_llm_router.complete.return_value = self._make_llm_response(raw_markdown)

        queries = await self.engine._generate_search_queries(task)
        self.assertEqual(len(queries), 3)
        for q in queries:
            self.assertFalse(q.startswith("```"))
            self.assertFalse(q.endswith("```"))
        self.assertIn("readiness probe", queries[1])

    async def test_ch1_03_llm_returns_insufficient_or_corrupt_json_triggers_deterministic_fallback(self) -> None:
        """
        Adversarial: LLM returns only 1 query or invalid JSON syntax.
        Fallback matrix must kick in and guarantee exactly 3 distinct multi-angle queries.
        """
        task = "PostgreSQL VACUUM tuning"

        # Case A: Partial array with only 1 item
        self.mock_llm_router.complete.return_value = self._make_llm_response('["single query only"]')
        queries_partial = await self.engine._generate_search_queries(task)
        self.assertEqual(len(queries_partial), 3)
        self.assertEqual(queries_partial[0], "single query only")
        self.assertEqual(len(set(queries_partial)), 3)

        # Case B: Corrupted JSON with syntax error
        self.mock_llm_router.complete.return_value = self._make_llm_response('{"error": "not a list"')
        queries_corrupt = await self.engine._generate_search_queries(task)
        self.assertEqual(len(queries_corrupt), 3)
        self.assertEqual(len(set(queries_corrupt)), 3)
        # Verify fallback matrix technical angles
        self.assertIn(f"{task} official documentation architecture", queries_corrupt)
        self.assertIn(f"{task} best practices production configuration", queries_corrupt)
        self.assertIn(f"{task} common pitfalls edge cases troubleshooting", queries_corrupt)

        # Case C: Empty response
        self.mock_llm_router.complete.return_value = self._make_llm_response("")
        queries_empty = await self.engine._generate_search_queries(task)
        self.assertEqual(len(queries_empty), 3)
        self.assertEqual(len(set(queries_empty)), 3)

    # ──────────────────────────────────────────────────────────────────────────
    # CHALLENGE 2: SEARCH INVOCATION COUNT & DIVERSE ARGUMENTS
    # ──────────────────────────────────────────────────────────────────────────

    async def test_ch2_01_browser_search_google_invoked_exactly_three_times_with_distinct_args(self) -> None:
        """Verify Researcher Agent executes browser_search_google for each generated query."""
        task = "Phân tích bảo mật SSH Key vs Certificate Authority"
        queries_expected = [
            "ssh ca architecture official documentation",
            "ssh certificate authority vault production best practices",
            "ssh certificate revocation edge cases security flaws",
        ]
        self.mock_llm_router.complete.side_effect = [
            self._make_llm_response(json.dumps(queries_expected)),
            self._make_llm_response("Research summary"),
            self._make_llm_response("Analyst selection"),
            self._make_llm_response("Implementer script"),
            self._make_llm_response("Reviewer verdict:\n• Rủi ro: Khóa CA bị lộ private key."),
        ]

        # Return mock results for search
        self.mock_browser_agent.browser_search_google.side_effect = [
            {"success": True, "top_results": [{"title": "SSH OpenSSH", "url": "https://openssh.com/ca", "snippet": "Doc 1"}]},
            {"success": True, "top_results": [{"title": "Vault SSH CA", "url": "https://vaultproject.io/docs/ssh", "snippet": "Doc 2"}]},
            {"success": True, "top_results": [{"title": "SSH Revocation", "url": "https://security.stackexchange.com/q/1234", "snippet": "Doc 3"}]},
        ]
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "OpenSSH CA",
            "page_text": "Certificate authority implementation details in OpenSSH.",
            "url": "https://openssh.com/ca",
        }

        result = await self.engine.execute_teamwork(task)

        # 1. Total search calls must be >= 3
        self.assertEqual(self.mock_browser_agent.browser_search_google.call_count, 3)

        # 2. Inspect arguments for all calls
        called_queries = [call.args[0] for call in self.mock_browser_agent.browser_search_google.call_args_list]
        self.assertEqual(called_queries, queries_expected)
        self.assertEqual(len(set(called_queries)), 3, "Each query must be distinct")

    # ──────────────────────────────────────────────────────────────────────────
    # CHALLENGE 3: WEB NAVIGATION & REAL TEXT EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    async def test_ch3_01_browser_navigate_extracts_real_web_text_and_feeds_synthesis(self) -> None:
        """Verify Researcher Agent navigates to chosen URL, extracts page text, and includes it in LLM prompt."""
        task = "Khảo sát eBPF cho Network Monitoring"
        target_url = "https://ebpf.io/what-is-ebpf"
        extracted_content = (
            "Extended Berkeley Packet Filter (eBPF) is a revolutionary technology with origins in the Linux kernel "
            "that can run sandboxed programs in a privileged context such as the operating system kernel."
        )

        captured_llm_prompts: List[Dict[str, str]] = []

        async def capture_complete(messages: List[Dict[str, str]], **kwargs):
            captured_llm_prompts.append({"sys": messages[0]["content"], "user": messages[1]["content"]})
            if "Principal Technical Investigator" in messages[0]["content"] and "JSON array" in messages[0]["content"]:
                return self._make_llm_response(json.dumps(["ebpf 1", "ebpf 2", "ebpf 3"]))
            return self._make_llm_response("Mocked LLM generation response")

        self.mock_llm_router.complete.side_effect = capture_complete

        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [
                {"title": "eBPF Overview", "url": target_url, "snippet": "eBPF Linux Kernel"},
            ],
            "page_text": "Search results page summary",
        }
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "eBPF Overview",
            "page_text": extracted_content,
            "url": target_url,
        }

        result = await self.engine.execute_teamwork(task)

        # Verify browser_navigate was called with the exact extracted URL
        self.mock_browser_agent.browser_navigate.assert_called_once_with(target_url)

        # Verify extracted page text was fed into LLM synthesis prompt
        researcher_synthesis_call = None
        for p in captured_llm_prompts:
            if "Synthesize deep research findings" in p["sys"]:
                researcher_synthesis_call = p
                break

        self.assertIsNotNone(researcher_synthesis_call, "Researcher synthesis prompt must be invoked")
        self.assertIn("Extended Berkeley Packet Filter", researcher_synthesis_call["user"])
        self.assertIn(target_url, researcher_synthesis_call["user"])

    async def test_ch3_02_browser_agent_service_browser_get_text_unit_contract(self) -> None:
        """Verify BrowserAgentService.browser_get_text primitive contract directly."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(return_value="Extracted DOM Content via selector")
        mock_page.locator.return_value = mock_locator
        mock_page.url = "https://example.org/test"

        service = BrowserAgentService()
        # Mock _get_or_create_active_page to return our mock_page
        service._get_or_create_active_page = AsyncMock(return_value=mock_page)

        res = await service.browser_get_text("h1.main-title")
        self.assertTrue(res["success"])
        self.assertEqual(res["text"], "Extracted DOM Content via selector")
        self.assertEqual(res["selector"], "h1.main-title")
        self.assertEqual(res["url"], "https://example.org/test")

    # ──────────────────────────────────────────────────────────────────────────
    # CHALLENGE 4: URL CITATION VALIDITY & SANITIZATION
    # ──────────────────────────────────────────────────────────────────────────

    async def test_ch4_01_urls_must_be_real_http_rejects_placeholders_and_malformed(self) -> None:
        """Adversarial: Search returns relative URLs, ftp links, javascript:, empty links."""
        task = "Bảo vệ API Gateway"

        self.mock_llm_router.complete.return_value = self._make_llm_response("Standard synthesis")

        # Inject malformed and adversarial URLs
        self.mock_browser_agent.browser_search_google.side_effect = [
            {
                "success": True,
                "top_results": [
                    {"title": "Valid HTTPS", "url": "https://konghq.com/docs", "snippet": "Official"},
                    {"title": "Relative Link", "url": "/docs/api-gateway", "snippet": "Relative"},
                    {"title": "FTP Protocol", "url": "ftp://files.example.com", "snippet": "FTP"},
                    {"title": "Javascript URI", "url": "javascript:alert(1)", "snippet": "XSS"},
                    {"title": "Empty String", "url": "   ", "snippet": "None"},
                ],
            },
            {
                "success": True,
                "top_results": [
                    {"title": "Valid HTTP", "url": "http://api-security.org/guide", "snippet": "HTTP"},
                    {"title": "Duplicate Kong", "url": "https://konghq.com/docs", "snippet": "Dupe"},
                ],
            },
            {
                "success": True,
                "top_results": [
                    {"title": "Valid GitHub", "url": "https://github.com/TykTechnologies/tyk", "snippet": "GitHub"},
                ],
            },
        ]
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "Kong Docs",
            "page_text": "Kong Gateway Docs",
            "url": "https://konghq.com/docs",
        }

        result = await self.engine.execute_teamwork(task)

        # Sources must only contain valid http/https URLs, deduplicated
        extracted_urls = [s["url"] for s in result.sources]
        self.assertEqual(
            extracted_urls,
            [
                "https://konghq.com/docs",
                "http://api-security.org/guide",
                "https://github.com/TykTechnologies/tyk",
            ],
        )

        for u in extracted_urls:
            self.assertTrue(u.startswith("http://") or u.startswith("https://"))
            self.assertFalse(u.startswith("/"))
            self.assertFalse(u.startswith("ftp://"))
            self.assertFalse(u.startswith("javascript:"))

        # Check Report Markdown formatting
        report = result.report_markdown
        self.assertIn("https://konghq.com/docs", report)
        self.assertIn("http://api-security.org/guide", report)
        self.assertIn("https://github.com/TykTechnologies/tyk", report)
        self.assertNotIn("javascript:", report)
        self.assertNotIn("ftp://", report)

    async def test_ch4_02_empty_sources_displays_honest_notice_no_fabricated_urls(self) -> None:
        """Adversarial: When no search results are returned, report must NOT fabricate fake example.com URLs."""
        task = "Bảo mật nhân Linux nội bộ"
        self.mock_llm_router.complete.return_value = self._make_llm_response("Analysis & Code")
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        result = await self.engine.execute_teamwork(task)

        self.assertEqual(len(result.sources), 0)
        report = result.report_markdown
        self.assertIn("## 📚 2. Nguồn tham khảo thực tế", report)
        self.assertIn("Không có liên kết ngoài từ tìm kiếm", report)
        self.assertNotIn("example.com", report)
        self.assertNotIn("http://fake", report)

    # ──────────────────────────────────────────────────────────────────────────
    # CHALLENGE 5: STRESS & FAULT TOLERANCE FALLBACK MATRIX
    # ──────────────────────────────────────────────────────────────────────────

    async def test_ch5_01_google_captcha_exception_falls_back_without_crashing(self) -> None:
        """Adversarial: Google search triggers CAPTCHA exception on all queries."""
        task = "Tối ưu hóa Swap Memory trên Linux"
        self.mock_llm_router.complete.return_value = self._make_llm_response("Completed smoothly")
        self.mock_browser_agent.browser_search_google.side_effect = RuntimeError(
            "Google CAPTCHA 429: Our systems have detected unusual traffic from your computer network."
        )

        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(self.mock_browser_agent.browser_search_google.call_count, 3)
        self.assertIn("Tối ưu hóa Swap Memory trên Linux", result.report_markdown)
        self.assertEqual(len(result.sources), 0)

    async def test_ch5_02_search_mixed_errors_and_partial_success(self) -> None:
        """
        Adversarial:
        Query 1: ConnectTimeout
        Query 2: HTTP 500 internal error
        Query 3: Success with valid URL
        Pipeline must recover, capture the valid URL from Query 3, and navigate to it.
        """
        task = "Cấu hình Logrotate cho Docker logs"
        self.mock_llm_router.complete.return_value = self._make_llm_response("Synthesis OK")

        self.mock_browser_agent.browser_search_google.side_effect = [
            TimeoutError("Connection timed out after 30s"),
            {"success": False, "error": "HTTP 500 Internal Server Error"},
            {
                "success": True,
                "top_results": [{"title": "Docker Logging Guide", "url": "https://docs.docker.com/config/containers/logging/", "snippet": "Logging"}],
                "page_text": "Docker logging docs",
            },
        ]
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "Docker Logging",
            "page_text": "Configuring log drivers and logrotate.",
            "url": "https://docs.docker.com/config/containers/logging/",
        }

        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0]["url"], "https://docs.docker.com/config/containers/logging/")
        self.mock_browser_agent.browser_navigate.assert_called_once_with(
            "https://docs.docker.com/config/containers/logging/"
        )

    async def test_ch5_03_browser_navigate_http_404_500_or_timeout_handled_gracefully(self) -> None:
        """Adversarial: Target web page returns HTTP 404/500 or times out during browser_navigate."""
        task = "Phân tích mã nguồn Linux Kernel"
        self.mock_llm_router.complete.return_value = self._make_llm_response("Analysis completed")

        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [
                {"title": "Dead Link 404", "url": "https://kernel.org/defunct_page", "snippet": "Dead link"}
            ],
            "page_text": "Google snippets text",
        }
        # browser_navigate raises Timeout / Navigation Failure
        self.mock_browser_agent.browser_navigate.side_effect = TimeoutError("Page load timed out after 45000ms")

        result = await self.engine.execute_teamwork(task)

        # Pipeline must not crash
        self.assertIsInstance(result, TeamworkResult)
        # URL is still preserved in sources from search results
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0]["url"], "https://kernel.org/defunct_page")
        self.assertIn("https://kernel.org/defunct_page", result.report_markdown)

    async def test_ch5_04_missing_or_none_browser_agent_tool_executor(self) -> None:
        """Adversarial: tool_executor has no browser_agent or browser_agent is None."""
        self.mock_tool_executor.browser_agent = None
        self.mock_llm_router.complete.return_value = self._make_llm_response("Pure internal knowledge")

        result = await self.engine.execute_teamwork("Nhiệm vụ khi không có browser tool")

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(len(result.sources), 0)
        self.assertIn("Nhiệm vụ khi không có browser tool", result.report_markdown)


if __name__ == "__main__":
    unittest.main()
