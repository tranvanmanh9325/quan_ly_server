"""
Unit and Integration Tests for TeamworkEngine (Milestone 1 - R1/R2/R3/R4).

Verifies:
1. TeamworkResult data container and serialization.
2. TeamworkEngine initialization and role progression.
3. Researcher Agent: 3 distinct search queries & real URL navigation.
4. Progress Callback notifications across all 4 phases.
5. Standardized 5-part Markdown technical report structure.
6. Fault tolerance: Empty search results and network exceptions.
7. Fault tolerance: Missing or None browser_agent.
8. Fault tolerance: LLM router failures and None responses.
9. Fault tolerance: Progress callback exceptions.
10. Query variation generation resilience.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.teamwork_engine import TeamworkEngine, TeamworkResult


class TestTeamworkEngine(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Mock LLM Router
        self.mock_llm_router = MagicMock()
        self.mock_llm_router.complete = AsyncMock()

        # Mock Browser Agent
        self.mock_browser_agent = MagicMock()
        self.mock_browser_agent.browser_search_google = AsyncMock()
        self.mock_browser_agent.browser_navigate = AsyncMock()

        # Mock Tool Executor
        self.mock_tool_executor = MagicMock()
        self.mock_tool_executor.browser_agent = self.mock_browser_agent

        # Instantiate TeamworkEngine
        self.engine = TeamworkEngine(
            llm_router=self.mock_llm_router,
            tool_executor=self.mock_tool_executor,
            default_model="llama-3.3-70b-versatile",
        )

    def _create_llm_response(self, text: str) -> dict:
        """Helper to create OpenAI-compatible mock response dictionary."""
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

    async def test_01_result_initialization_and_serialization(self) -> None:
        """Verify TeamworkResult holds all required fields and serializes to dict properly."""
        result = TeamworkResult(
            task="Tối ưu Nginx",
            report_markdown="# Report",
            sources=[{"title": "Nginx Docs", "url": "https://nginx.org", "snippet": "Tuning"}],
            risks=["Buffer overflow edge case"],
            chosen_solution="Sử dụng HTTP/2 và FastCGI microcache",
            reviewer_verdict="Phê duyệt sẵn sàng triển khai",
            execution_time_seconds=12.5,
        )

        self.assertEqual(result.task, "Tối ưu Nginx")
        self.assertEqual(result.report_markdown, "# Report")
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0]["url"], "https://nginx.org")
        self.assertEqual(len(result.risks), 1)
        self.assertEqual(result.chosen_solution, "Sử dụng HTTP/2 và FastCGI microcache")
        self.assertEqual(result.reviewer_verdict, "Phê duyệt sẵn sàng triển khai")
        self.assertEqual(result.execution_time_seconds, 12.5)

        data = result.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["task"], "Tối ưu Nginx")
        self.assertEqual(data["sources"][0]["title"], "Nginx Docs")

    async def test_02_sequential_pipeline_runs_all_four_roles(self) -> None:
        """Verify end-to-end execution through Researcher -> Analyst -> Implementer -> Reviewer."""
        task_desc = "Tối ưu hóa Nginx giảm latency"

        # Mock LLM outputs for each sequential role
        # Call 1: _generate_search_queries
        # Call 2: _run_researcher summary
        # Call 3: _run_analyst
        # Call 4: _run_implementer
        # Call 5: _run_reviewer
        queries_json = json.dumps([
            "nginx latency tuning core docs",
            "nginx http2 microcache best practices",
            "nginx buffer size edge cases troubleshooting",
        ])

        self.mock_llm_router.complete.side_effect = [
            self._create_llm_response(queries_json),
            self._create_llm_response("Tổng hợp nghiên cứu Nginx với HTTP/2 và TCP nodelay."),
            self._create_llm_response("Analyst: Lựa chọn giải pháp HTTP/2 kết hợp epoll và sendfile."),
            self._create_llm_response("Implementer: Cấu hình /etc/nginx/nginx.conf hoàn chỉnh không có TODO."),
            self._create_llm_response(
                "Reviewer Audit:\n"
                "• Điểm mạnh: Cấu hình đồng bộ, giảm TTFB.\n"
                "• Rủi ro & Edge Cases: Nguy cơ OOM khi client_body_buffer_size quá nhỏ khi upload lớn.\n"
                "• Khuyến nghị: Bổ sung rate limiting zone.\n"
                "• Kết luận: Phê duyệt áp dụng Staging."
            ),
        ]

        # Mock Google search responses
        self.mock_browser_agent.browser_search_google.side_effect = [
            {
                "success": True,
                "top_results": [{"title": "Nginx Core", "url": "https://nginx.org/core", "snippet": "Docs"}],
                "page_text": "Nginx official documentation content",
            },
            {
                "success": True,
                "top_results": [{"title": "Nginx Tuning Blog", "url": "https://nginx.com/blog", "snippet": "Tuning"}],
                "page_text": "Performance tuning tips",
            },
            {
                "success": True,
                "top_results": [{"title": "GitHub Server Configs", "url": "https://github.com/h5bp/server-configs-nginx", "snippet": "Configs"}],
                "page_text": "H5BP nginx configs",
            },
        ]

        # Mock navigate response
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "Nginx Core Documentation",
            "page_text": "Detailed parameters: worker_processes auto, keepalive_timeout 65.",
            "url": "https://nginx.org/core",
        }

        # Progress tracking mock
        progress_mock = AsyncMock()

        result = await self.engine.execute_teamwork(task_desc, progress_callback=progress_mock)

        # Assertions
        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(result.task, task_desc)
        self.assertIn("epoll và sendfile", result.chosen_solution)
        self.assertIn("Reviewer Audit", result.reviewer_verdict)
        self.assertGreater(len(result.sources), 0)
        self.assertGreater(len(result.risks), 0)
        self.assertGreaterEqual(result.execution_time_seconds, 0.0)

        # Verify Google search was called 3 times
        self.assertEqual(self.mock_browser_agent.browser_search_google.call_count, 3)

        # Verify navigate was called at least once
        self.mock_browser_agent.browser_navigate.assert_called_once()

    async def test_03_researcher_invokes_three_search_queries_and_navigates(self) -> None:
        """Verify Researcher Agent executes >= 3 distinct search queries and navigates to real URL."""
        task_desc = "Cấu hình Failover tự động PostgreSQL"

        self.mock_llm_router.complete.side_effect = [
            self._create_llm_response(json.dumps([
                "postgresql replication official documentation",
                "pgpool patroni failover best practices",
                "split brain postgresql edge cases recovery",
            ])),
            self._create_llm_response("Tóm tắt tài liệu Patroni và Raft consensus."),
            self._create_llm_response("Analyst chọn Patroni kết hợp etcd."),
            self._create_llm_response("Implementer tạo file patroni.yml hoàn chỉnh."),
            self._create_llm_response(
                "Reviewer:\n"
                "• Rủi ro: Nguy cơ split-brain nếu mạng giữa etcd cluster bị ngắt phân mảnh.\n"
                "• Kết luận: Đạt chuẩn."
            ),
        ]

        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [
                {"title": "Patroni Docs", "url": "https://patroni.readthedocs.io", "snippet": "HA Template"}
            ],
            "page_text": "Patroni HA template documentation",
        }
        self.mock_browser_agent.browser_navigate.return_value = {
            "success": True,
            "page_title": "Patroni Readthedocs",
            "page_text": "Patroni is an HA template for PostgreSQL",
            "url": "https://patroni.readthedocs.io",
        }

        result = await self.engine.execute_teamwork(task_desc)

        # Verify search call count >= 3
        self.assertGreaterEqual(self.mock_browser_agent.browser_search_google.call_count, 3)
        self.assertEqual(self.mock_browser_agent.browser_navigate.call_count, 1)

        # Verify source URL exists in results
        urls = [s["url"] for s in result.sources]
        self.assertIn("https://patroni.readthedocs.io", urls)

    async def test_04_progress_callback_called_four_times_with_exact_roles(self) -> None:
        """Verify progress_callback is dispatched sequentially with exact emoji and role markers."""
        self.mock_llm_router.complete.return_value = self._create_llm_response("Output")
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        recorded_messages = []

        async def capture_progress(msg: str) -> None:
            recorded_messages.append(msg)

        await self.engine.execute_teamwork("Kiểm tra disk I/O", progress_callback=capture_progress)

        self.assertEqual(len(recorded_messages), 4)
        self.assertTrue(recorded_messages[0].startswith("🔍 [1/4] Researcher Agent"))
        self.assertTrue(recorded_messages[1].startswith("🧠 [2/4] Analyst Agent"))
        self.assertTrue(recorded_messages[2].startswith("⚙️ [3/4] Implementer Agent"))
        self.assertTrue(recorded_messages[3].startswith("🔎 [4/4] Reviewer Agent"))

    async def test_05_report_markdown_five_standard_sections(self) -> None:
        """Verify final synthesis report contains all 5 required standard sections."""
        self.mock_llm_router.complete.side_effect = [
            self._create_llm_response(json.dumps(["q1", "q2", "q3"])),
            self._create_llm_response("Research summary"),
            self._create_llm_response("Analyst chosen strategy: Redis Sentinel"),
            self._create_llm_response("Implementer configs: sentinel monitor mymaster"),
            self._create_llm_response("Reviewer verdict:\n• Rủi ro: Quorum loss khi mạng chia cắt."),
        ]
        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [{"title": "Redis Sentinel", "url": "https://redis.io/sentinel", "snippet": "Sentinel Guide"}],
        }
        self.mock_browser_agent.browser_navigate.return_value = {"success": True, "page_text": "Sentinel docs"}

        result = await self.engine.execute_teamwork("Thiết lập Redis High Availability")

        report = result.report_markdown
        self.assertIn("# 🚀 [TEAMWORK REPORT] Thiết lập Redis High Availability", report)
        self.assertIn("## 🎯 1. Tóm tắt bài toán & giải pháp", report)
        self.assertIn("## 📚 2. Nguồn tham khảo thực tế", report)
        self.assertIn("## 💻 3. Giải pháp & Mã nguồn chi tiết (Production-Ready)", report)
        self.assertIn("## ⚠️ 4. Cảnh báo rủi ro & Edge cases", report)
        self.assertIn("## 🛡️ 5. Reviewer's Verdict", report)

        # Confirm citation of actual URL
        self.assertIn("https://redis.io/sentinel", report)

    async def test_06_resilience_when_search_returns_empty_or_errors(self) -> None:
        """Verify pipeline completes smoothly when browser_search_google fails or returns empty."""
        # Query generation fails to return valid json, triggers fallback
        self.mock_llm_router.complete.return_value = self._create_llm_response("Fallback text")

        # Google search raises network exception
        self.mock_browser_agent.browser_search_google.side_effect = Exception("Google CAPTCHA or Network error")

        result = await self.engine.execute_teamwork("Khắc phục sự cố Nginx")

        # Must not crash
        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(self.mock_browser_agent.browser_search_google.call_count, 3)
        self.assertIn("Khắc phục sự cố Nginx", result.report_markdown)

    async def test_07_resilience_when_browser_agent_is_none(self) -> None:
        """Verify pipeline handles tool_executor with no browser_agent gracefully."""
        self.engine.tool_executor.browser_agent = None
        self.mock_llm_router.complete.return_value = self._create_llm_response("Default answer")

        result = await self.engine.execute_teamwork("Tối ưu hóa Docker swap")

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(len(result.sources), 0)
        self.assertIn("Tối ưu hóa Docker swap", result.report_markdown)

    async def test_08_resilience_when_llm_fails_or_returns_none(self) -> None:
        """Verify fallback behavior when LLM router returns None or throws."""
        self.mock_llm_router.complete.side_effect = Exception("LLM Provider Timeout")
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        result = await self.engine.execute_teamwork("Cấu hình Firewall UFW")

        self.assertIsInstance(result, TeamworkResult)
        self.assertTrue(len(result.chosen_solution) > 0)
        self.assertTrue(len(result.reviewer_verdict) > 0)
        self.assertTrue(len(result.risks) >= 1)
        self.assertIn("Cấu hình Firewall UFW", result.report_markdown)

    async def test_09_progress_callback_exception_does_not_abort_workflow(self) -> None:
        """Verify an exception inside progress_callback does not crash the teamwork engine."""
        self.mock_llm_router.complete.return_value = self._create_llm_response("OK")
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        broken_callback = AsyncMock(side_effect=RuntimeError("Telegram network failure"))

        result = await self.engine.execute_teamwork("Kiểm tra uptime", progress_callback=broken_callback)

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(broken_callback.call_count, 4)

    async def test_10_generate_search_queries_variations(self) -> None:
        """Verify query generator always produces at least 3 distinct non-empty queries."""
        # 1. When LLM produces markdown code fences
        self.mock_llm_router.complete.return_value = self._create_llm_response(
            "```json\n[\"query A\", \"query B\", \"query C\"]\n```"
        )
        queries = await self.engine._generate_search_queries("Optimize Linux kernel")
        self.assertEqual(len(queries), 3)
        self.assertEqual(queries, ["query A", "query B", "query C"])

        # 2. When LLM produces fewer than 3 queries
        self.mock_llm_router.complete.return_value = self._create_llm_response(
            "[\"only one query\"]"
        )
        queries_fallback = await self.engine._generate_search_queries("Optimize Linux kernel")
        self.assertEqual(len(queries_fallback), 3)
        self.assertEqual(queries_fallback[0], "only one query")
        self.assertNotEqual(queries_fallback[1], queries_fallback[2])

    async def test_11_browser_navigate_fails_but_search_succeeds(self) -> None:
        """Verify sources and pipeline are preserved when browser_navigate raises an exception."""
        self.mock_llm_router.complete.return_value = self._create_llm_response("Analysis & Code")
        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [
                {"title": "Valid Doc", "url": "https://docs.example.com", "snippet": "Example"}
            ],
            "page_text": "Sample text",
        }
        self.mock_browser_agent.browser_navigate.side_effect = TimeoutError("Page load timed out after 45s")

        result = await self.engine.execute_teamwork("Tối ưu hóa bộ nhớ đệm")

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0]["url"], "https://docs.example.com")
        self.assertIn("https://docs.example.com", result.report_markdown)

    async def test_12_url_deduplication_and_invalid_filtering(self) -> None:
        """Verify URL deduplication and filtering out non-http protocols or blank links."""
        self.mock_llm_router.complete.return_value = self._create_llm_response("Result")
        self.mock_browser_agent.browser_search_google.return_value = {
            "success": True,
            "top_results": [
                {"title": "Valid Link 1", "url": "https://example.com/one", "snippet": "First"},
                {"title": "Duplicate Link 1", "url": "https://example.com/one", "snippet": "Dupe"},
                {"title": "Invalid Scheme", "url": "ftp://ftp.example.com", "snippet": "FTP"},
                {"title": "Relative URL", "url": "/docs/index.html", "snippet": "Relative"},
                {"title": "Empty URL", "url": "   ", "snippet": "Empty"},
                {"title": "Valid Link 2", "url": "http://example.com/two", "snippet": "Second"},
            ],
        }

        result = await self.engine.execute_teamwork("Lọc URLs an toàn")

        self.assertEqual(len(result.sources), 2)
        urls = [s["url"] for s in result.sources]
        self.assertEqual(urls, ["https://example.com/one", "http://example.com/two"])

    async def test_13_reviewer_risk_extraction_patterns(self) -> None:
        """Verify risk extractor captures various bullet formats and keyword triggers."""
        self.mock_llm_router.complete.side_effect = [
            self._create_llm_response(json.dumps(["q1", "q2", "q3"])),
            self._create_llm_response("Research"),
            self._create_llm_response("Analyst"),
            self._create_llm_response("Implementer"),
            self._create_llm_response(
                "Reviewer findings:\n"
                "1. Nguy cơ tràn bộ nhớ đệm (buffer overflow) khi payload lớn.\n"
                "- Rủi ro bảo mật injection nếu input không được sanitize.\n"
                "* Lỗ hổng CWE-400 do thiếu rate limit.\n"
                "• Edge case: Concurrency deadlock khi nhiều workers cùng tranh chấp tài nguyên.\n"
                "Thảo luận chung không phải rủi ro."
            ),
        ]
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        result = await self.engine.execute_teamwork("Kiểm thử bảo mật đối kháng")

        self.assertGreaterEqual(len(result.risks), 4)
        self.assertTrue(any("tràn bộ nhớ đệm" in r for r in result.risks))
        self.assertTrue(any("CWE-400" in r for r in result.risks))
        self.assertTrue(any("deadlock" in r for r in result.risks))

    async def test_14_progress_callback_none_works_without_error(self) -> None:
        """Verify pipeline executes cleanly when progress_callback is omitted (None)."""
        self.mock_llm_router.complete.return_value = self._create_llm_response("All good")
        self.mock_browser_agent.browser_search_google.return_value = {"success": True, "top_results": []}

        result = await self.engine.execute_teamwork("Tác vụ không có callback", progress_callback=None)

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(result.task, "Tác vụ không có callback")


if __name__ == "__main__":
    unittest.main()

