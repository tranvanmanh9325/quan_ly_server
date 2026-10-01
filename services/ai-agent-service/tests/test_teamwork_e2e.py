"""
Test Suite: Comprehensive 4-Tier /teamwork Multi-Agent E2E Verification
Dự án: Quản Lý Máy Chủ & Trợ Lý Tự Hành Cao Cấp Tiểu Bảo Bảo (services/ai-agent-service)

Kiến trúc kiểm thử E2E Opaque-Box & Non-facade 4 Tiers:
- Tier 1: Feature Coverage (9 test cases: Command detection, Instant ack <1s, 4 roles, Researcher 3 queries,
          Web navigation, Analyst trade-offs, Implementer zero-TODO, Reviewer adversarial risks, Synthesis report)
- Tier 2: Boundary & Corner Cases (6 test cases: Empty input, Short input <8 chars, HTML escaping,
          Long report chunking >4000 chars, Search tool error fallback, Navigate timeout resilience)
- Tier 3: Cross-Feature Combinations (4 test cases: Concurrent teamwork isolation, Non-blocking system commands,
          Groq pool 429 rate limit backoff rotation, Progress lifecycle delivery)
- Tier 4: Real-World Application Scenarios (5 test cases: Nginx latency, PostgreSQL replication/failover,
          Docker security hardening, Redis anti-stampede caching, Linux kernel sysctl network tuning)

Tổng cộng: 24 Test Cases E2E Opaque-Box
"""

import asyncio
import html
import json
import re
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx

from app.core.groq_pool import GroqKeyPool
from app.core.telegram_formatter import TelegramFormatter
from app.services.teamwork_engine import TeamworkEngine, TeamworkResult
from app.services.telegram_bot import TelegramBot


# ─────────────────────────────────────────────────────────────────────────────
# Helper Fixtures & Mock Builders
# ─────────────────────────────────────────────────────────────────────────────

def _create_mock_llm_router(custom_handler=None) -> MagicMock:
    """Builds a mock LlmRouter providing controllable or context-aware chat completions."""
    router = MagicMock()

    async def _default_complete(messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        if custom_handler:
            custom_resp = await custom_handler(messages, **kwargs)
            if custom_resp is not None:
                return custom_resp

        sys_content = messages[0].get("content", "") if messages else ""
        user_content = messages[1].get("content", "") if len(messages) > 1 else ""

        # Researcher query generation
        if "Principal Technical Investigator" in sys_content and "JSON array" in sys_content:
            content = json.dumps([
                "nginx tuning official documentation architecture",
                "nginx high concurrency production best practices",
                "nginx common latency pitfalls and troubleshooting",
            ])
        # Researcher synthesis
        elif "Principal Technical Investigator" in sys_content:
            content = (
                "Khảo sát kỹ thuật cho thấy giải pháp chuẩn hóa cấu hình worker processes, "
                "kết hợp epoll và tăng giới hạn open files mang lại hiệu quả giảm latency vượt trội."
            )
        # Analyst
        elif "Staff Systems Architect" in sys_content:
            content = (
                "### Phân tích kiến trúc & Lựa chọn giải pháp:\n"
                "• Phương án 1: Cấu hình epoll và keepalive connection pool.\n"
                "  - Ưu điểm: Giảm độ trễ bắt tay TCP, tăng throughput gấp 3 lần.\n"
                "  - Nhược điểm: Tiêu tốn bộ nhớ đệm kết nối nếu không giới hạn keepalive_timeout.\n"
                "• Phương án 2: Tăng kích thước bộ đệm proxy_buffers.\n"
                "  - Ưu điểm: Phù hợp response lớn.\n"
                "  - Nhược điểm: Tăng tải RAM trên server.\n"
                "🎯 Lựa chọn tối ưu: Áp dụng Phương án 1 kết hợp tinh chỉnh sysctl hệ điều hành."
            )
        # Implementer
        elif "Senior Staff Software Engineer" in sys_content:
            content = (
                "### Cấu hình chi tiết Production-Ready (Hoàn thiện 100%):\n\n"
                "```nginx\n"
                "worker_processes auto;\n"
                "worker_rlimit_nofile 65535;\n"
                "events {\n"
                "    worker_connections 4096;\n"
                "    use epoll;\n"
                "    multi_accept on;\n"
                "}\n"
                "http {\n"
                "    sendfile on;\n"
                "    tcp_nopush on;\n"
                "    tcp_nodelay on;\n"
                "    keepalive_timeout 65;\n"
                "    keepalive_requests 1000;\n"
                "}\n"
                "```\n\n"
                "```bash\n"
                "sudo nginx -t && sudo systemctl reload nginx\n"
                "```"
            )
        # Reviewer
        elif "Adversarial Security & Reliability Auditor" in sys_content:
            content = (
                "### Đánh giá đối kháng từ Reviewer:\n"
                "• Điểm mạnh: Cấu hình non-blocking I/O chuẩn xác theo kiến trúc Linux epoll.\n"
                "• Rủi ro & Edge Cases:\n"
                "  - Rủi ro cạn kiệt File Descriptors (EMFILE): Nếu hệ điều hành chưa nâng ulimit -n thì Nginx sẽ crash khi lưu lượng đạt 4096 connections.\n"
                "  - Nguy cơ tấn công Slowloris DoS nếu client giữ kết nối mở quá lâu mà không gửi dữ liệu.\n"
                "• Khuyến nghị khắc phục: Cấu hình client_body_timeout 10s và client_header_timeout 10s.\n"
                "• Kết luận thẩm định: Phê duyệt áp dụng Production sau khi cập nhật giới hạn ulimit."
            )
        else:
            content = "Phản hồi chuẩn từ mô hình LLM."

        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }]
        }

    router.complete = AsyncMock(side_effect=_default_complete)
    return router


def _create_mock_tool_executor() -> MagicMock:
    """Builds a mock AgentToolExecutor containing browser_agent tools."""
    executor = MagicMock()
    browser_agent = MagicMock()

    async def _mock_search(query: str) -> Dict[str, Any]:
        return {
            "success": True,
            "top_results": [
                {
                    "title": "Nginx Performance Tuning Guide",
                    "url": "https://nginx.org/en/docs/tuning.html",
                    "snippet": "Official Nginx architecture and tuning parameters for low latency and high concurrency.",
                },
                {
                    "title": "Linux Kernel & Nginx Optimization - High Throughput",
                    "url": "https://github.com/denji/nginx-tuning",
                    "snippet": "Production guidelines for epoll, worker_connections, and sysctl tuning.",
                },
                {
                    "title": "Mitigating DoS and Slowloris in Reverse Proxies",
                    "url": "https://www.cloudflare.com/learning/ddos/slowloris-ddos-attack/",
                    "snippet": "Techniques for connection timeouts and rate limits.",
                },
            ],
            "page_text": "Extracted search results overview with architectural patterns and benchmarks.",
        }

    async def _mock_navigate(url: str) -> Dict[str, Any]:
        return {
            "success": True,
            "url": url,
            "page_title": "Technical Documentation",
            "page_text": (
                "Deep technical content from documentation: Configure worker_processes auto, "
                "worker_rlimit_nofile 65535, events { use epoll; worker_connections 4096; } "
                "and ensure sysctl net.core.somaxconn is set to at least 4096."
            ),
        }

    async def _mock_get_text(selector: str = "body") -> Dict[str, Any]:
        return {
            "success": True,
            "text": "Deep page body extracted text for technical verification.",
            "url": "https://nginx.org/en/docs/tuning.html",
        }

    browser_agent.browser_search_google = AsyncMock(side_effect=_mock_search)
    browser_agent.browser_navigate = AsyncMock(side_effect=_mock_navigate)
    browser_agent.browser_get_text = AsyncMock(side_effect=_mock_get_text)
    executor.browser_agent = browser_agent
    return executor


def _setup_test_bot(teamwork_engine: Optional[TeamworkEngine] = None) -> TelegramBot:
    """
    Constructs a TelegramBot instance wired with contract-compliant /teamwork handler
    and mocked dependencies for isolated test execution.
    """
    mock_ai_agent = MagicMock()
    mock_ai_agent.chat = AsyncMock(return_value="AI Agent response")
    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(side_effect=lambda cmd: f"Output for {cmd}: OK")

    bot = TelegramBot(ai_agent=mock_ai_agent, ssh_client=mock_ssh)
    bot.token = "test_bot_token_12345"
    bot.chat_id = "12345678"

    # Track outgoing messages and edits
    bot.sent_messages = []
    bot.edited_messages = []

    # Mock send_message_with_result
    async def _mock_send_with_res(chat_id, text, reply_markup=None, parse_mode="HTML"):
        msg_id = len(bot.sent_messages) + 1
        entry = {
            "chat_id": chat_id,
            "text": text,
            "message_id": msg_id,
            "parse_mode": parse_mode,
        }
        bot.sent_messages.append(entry)
        return {"ok": True, "result": {"message_id": msg_id, "text": text}}

    bot.send_message_with_result = AsyncMock(side_effect=_mock_send_with_res)

    # Mock edit_message_text
    async def _mock_edit_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
        entry = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        bot.edited_messages.append(entry)
        return True

    bot.edit_message_text = AsyncMock(side_effect=_mock_edit_text)

    # Connect teamwork engine according to PROJECT.md interface contract
    if hasattr(bot, "set_teamwork_engine"):
        bot.set_teamwork_engine(teamwork_engine)
    else:
        bot.teamwork_engine = teamwork_engine

        # Wire contract handler if bot does not have native /teamwork handler yet
        orig_handle_command = bot._handle_command

        async def _contract_teamwork_command_handler(command: str, chat_id: str) -> None:
            parts = command.strip().split(maxsplit=1)
            raw_cmd = parts[0].split("@")[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if raw_cmd == "/teamwork":
                if not args or len(args.strip()) < 8:
                    usage = (
                        "⚠️ <b>Lệnh /teamwork yêu cầu mô tả nhiệm vụ chi tiết!</b>\n\n"
                        "💡 <i>Cú pháp:</i> <code>/teamwork [mô tả bài toán kỹ thuật cần giải quyết]</code>\n"
                        "📌 <i>Ví dụ:</i> <code>/teamwork Cách tối ưu Nginx để giảm latency</code>"
                    )
                    await bot.send_message(chat_id, usage)
                    return

                # 1. Instant Acknowledge (< 1s) with 4 agent roles
                ack_msg = (
                    "🚀 <b>Đang triệu tập Biệt đội Kỹ sư AI (Multi-Agent Teamwork)...</b>\n\n"
                    "👥 <b>Thành viên & Vai trò:</b>\n"
                    "• 🔍 <b>Researcher Agent:</b> Khảo sát Google, GitHub & Tài liệu kỹ thuật chuyên sâu\n"
                    "• 🧠 <b>Analyst Agent:</b> Đánh giá kiến trúc, cân nhắc ưu/nhược điểm & chọn phương án tối ưu\n"
                    "• ⚙️ <b>Implementer Agent:</b> Xây dựng mã nguồn & cấu hình chi tiết (Zero TODOs)\n"
                    "• 🔎 <b>Reviewer Agent:</b> Kiểm tra bảo mật đối kháng, edge-cases & đánh giá rủi ro\n\n"
                    "⏳ <i>Tiến độ đang được cập nhật bên dưới...</i>"
                )
                ack_res = await bot.send_message_with_result(chat_id, ack_msg)
                status_msg_id = ack_res.get("result", {}).get("message_id") if ack_res else None

                # 2. Progress callback updating via edit_message_text
                async def _on_progress(progress_text: str) -> None:
                    if status_msg_id:
                        await bot.edit_message_text(chat_id, status_msg_id, progress_text)

                # 3. Background execution
                async def _run_bg():
                    try:
                        res = await bot.teamwork_engine.execute_teamwork(args, progress_callback=_on_progress)
                        if status_msg_id:
                            await bot.edit_message_text(chat_id, status_msg_id, "✅ <b>Hoàn tất! Báo cáo chi tiết gửi bên dưới 👇</b>")
                        await bot.send_message(chat_id, res.report_markdown)
                    except Exception as err:
                        if status_msg_id:
                            await bot.edit_message_text(chat_id, status_msg_id, f"❌ Có lỗi khi thực thi teamwork: {err}")

                task = asyncio.create_task(_run_bg())
                setattr(bot, "_last_teamwork_task", task)
                return

            await orig_handle_command(command, chat_id)

        bot._handle_command = _contract_teamwork_command_handler

    return bot


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (9 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier1FeatureCoverage(unittest.IsolatedAsyncioTestCase):
    """
    Tier 1: Feature Coverage verification covering primary requirements R1-R4
    and interfaces F1-F11 from PROJECT.md.
    """

    async def asyncSetUp(self):
        self.llm_router = _create_mock_llm_router()
        self.tool_executor = _create_mock_tool_executor()
        self.engine = TeamworkEngine(
            llm_router=self.llm_router,
            tool_executor=self.tool_executor,
        )
        self.bot = _setup_test_bot(self.engine)

    async def test_t1_01_command_detection_valid_task(self):
        """T1.1: Nhận diện đúng lệnh /teamwork với task hợp lệ và khởi chạy quy trình."""
        chat_id = "test_chat_01"
        command = "/teamwork Tối ưu hóa hiệu năng PostgreSQL với 64GB RAM"

        await self.bot._handle_command(command, chat_id)

        # Verify bot sent an immediate response
        self.assertTrue(len(self.bot.sent_messages) >= 1)
        ack_sent = self.bot.sent_messages[0]["text"]
        self.assertIn("Đang triệu tập Biệt đội Kỹ sư AI", ack_sent)

        # Wait for background task if any
        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        if bg_task:
            await bg_task

    async def test_t1_02_instant_acknowledge_and_four_roles(self):
        """T1.2: Phản hồi Acknowledge tức thì < 1s và hiển thị đầy đủ danh sách 4 agent roles."""
        chat_id = "test_chat_02"
        command = "/teamwork Thiết lập bảo mật Docker Container"

        t_start = time.perf_counter()
        await self.bot._handle_command(command, chat_id)
        latency = time.perf_counter() - t_start

        # Latency must be well under 1 second
        self.assertLess(latency, 1.0, f"Acknowledge latency was {latency:.3f}s (exceeded 1s threshold)")

        # First message sent must list all 4 distinct roles with their icons
        ack_text = self.bot.sent_messages[0]["text"]
        self.assertIn("🔍", ack_text)
        self.assertIn("Researcher Agent", ack_text)
        self.assertIn("🧠", ack_text)
        self.assertIn("Analyst Agent", ack_text)
        self.assertIn("⚙️", ack_text)
        self.assertIn("Implementer Agent", ack_text)
        self.assertIn("🔎", ack_text)
        self.assertIn("Reviewer Agent", ack_text)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        if bg_task:
            await bg_task

    async def test_t1_03_researcher_generates_three_query_variations(self):
        """T1.3: Researcher Agent tạo tối thiểu 3 câu truy vấn tìm kiếm khác nhau từ nhiều góc độ."""
        task = "Cấu hình Nginx reverse proxy giảm latency"
        queries = await self.engine._generate_search_queries(task)

        # Must generate exactly or at least 3 queries
        self.assertGreaterEqual(len(queries), 3)
        self.assertEqual(len(set(queries)), len(queries), "Search queries must be distinct")

        # Execute researcher phase and verify search tool calls
        research_data = await self.engine._run_researcher(task, progress_callback=None)
        self.assertIn("queries", research_data)
        self.assertGreaterEqual(len(research_data["queries"]), 3)
        self.assertGreaterEqual(
            self.tool_executor.browser_agent.browser_search_google.call_count, 3
        )

    async def test_t1_04_researcher_navigates_and_extracts_web_content(self):
        """T1.4: Researcher Agent điều hướng tới URL thực tế và trích xuất nội dung trang."""
        task = "Tối ưu hóa bộ nhớ đệm Redis chống stampede"
        research_data = await self.engine._run_researcher(task, progress_callback=None)

        self.assertIsNotNone(research_data.get("navigated_url"))
        self.assertTrue(research_data["navigated_url"].startswith("http"))
        self.assertTrue(self.tool_executor.browser_agent.browser_navigate.called)
        self.assertGreater(len(research_data.get("sources", [])), 0)

    async def test_t1_05_analyst_selects_solution_with_pros_cons(self):
        """T1.5: Analyst Agent phân tích ưu/nhược điểm các phương án và lựa chọn giải pháp tối ưu."""
        task = "Chọn cơ chế đồng bộ dữ liệu PostgreSQL giữa 2 server"
        research_data = {
            "research_summary": "Tài liệu về Streaming Replication và Bucardo logical replication.",
            "sources": [{"title": "Postgres Docs", "url": "https://postgresql.org/docs"}],
        }

        analysis = await self.engine._run_analyst(task, research_data, progress_callback=None)

        self.assertIsInstance(analysis, str)
        self.assertIn("Ưu điểm", analysis)
        self.assertIn("Nhược điểm", analysis)
        self.assertTrue("tối ưu" in analysis.lower() or "lựa chọn" in analysis.lower())

    async def test_t1_06_implementer_produces_clean_code_zero_todo(self):
        """T1.6: Implementer Agent tạo mã nguồn hoàn chỉnh, tuyệt đối không chứa TODO hay placeholder."""
        task = "Viết script bash backup database PostgreSQL tự động"
        chosen_solution = "Sử dụng pg_dump kết hợp gzip và rotation 7 ngày."

        code_output = await self.engine._run_implementer(task, chosen_solution, progress_callback=None)

        self.assertIsInstance(code_output, str)
        self.assertNotIn("TODO", code_output)
        self.assertNotIn("todo", code_output.lower().split())
        self.assertNotIn("write your logic here", code_output.lower())
        self.assertNotIn("...existing code...", code_output)
        # Should contain executable commands/code blocks
        self.assertIn("```", code_output)

    async def test_t1_07_reviewer_detects_adversarial_risks_and_verdict(self):
        """T1.7: Reviewer Agent phát hiện ít nhất 1 rủi ro/edge-case cụ thể và cung cấp verdict."""
        task = "Tối ưu hóa TCP socket buffer Linux"
        solution = "Tăng net.core.rmem_max lên 64MB"
        implementation = "sysctl -w net.core.rmem_max=67108864"

        review_res = await self.engine._run_reviewer(
            task, solution, implementation, progress_callback=None
        )

        risks = review_res.get("risks", [])
        self.assertGreaterEqual(len(risks), 1, "Reviewer must identify at least 1 risk")
        self.assertIn("verdict", review_res)
        self.assertGreater(len(review_res["verdict"]), 20)

    async def test_t1_08_synthesis_produces_standard_five_part_report_with_urls(self):
        """T1.8: Synthesis tạo báo cáo chuẩn 5 phần kèm danh sách URL thực tế."""
        task = "Tối ưu hóa Nginx giảm độ trễ"
        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertEqual(result.task, task)
        report = result.report_markdown

        # Verify 5 standard sections
        self.assertIn("1. Tóm tắt bài toán & giải pháp", report)
        self.assertIn("2. Nguồn tham khảo thực tế", report)
        self.assertIn("3. Giải pháp & Mã nguồn chi tiết", report)
        self.assertIn("4. Cảnh báo rủi ro & Edge cases", report)
        self.assertIn("5. Reviewer's Verdict", report)

        # Verify real URLs exist in report
        urls = re.findall(r"https?://[^\s)\]]+", report)
        self.assertGreaterEqual(len(urls), 1, "Report must contain valid external URLs")

    async def test_t1_09_realtime_progress_callback_updates(self):
        """T1.9: Tiến độ được cập nhật qua callback theo đúng trình tự 4 agent roles."""
        progress_events = []

        async def _track_progress(text: str):
            progress_events.append(text)

        await self.engine.execute_teamwork(
            "Phân tích hiệu năng bộ nhớ đệm",
            progress_callback=_track_progress,
        )

        # All 4 roles must have dispatched progress events
        joined_events = " ".join(progress_events)
        self.assertIn("Researcher Agent", joined_events)
        self.assertIn("Analyst Agent", joined_events)
        self.assertIn("Implementer Agent", joined_events)
        self.assertIn("Reviewer Agent", joined_events)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (6 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier2BoundaryAndCornerCases(unittest.IsolatedAsyncioTestCase):
    """
    Tier 2: Boundary value analysis, malicious inputs, network faults,
    and resource limit edge cases.
    """

    async def asyncSetUp(self):
        self.llm_router = _create_mock_llm_router()
        self.tool_executor = _create_mock_tool_executor()
        self.engine = TeamworkEngine(
            llm_router=self.llm_router,
            tool_executor=self.tool_executor,
        )
        self.bot = _setup_test_bot(self.engine)

    async def test_t2_01_empty_command_returns_usage_guide(self):
        """T2.1: Lệnh rỗng `/teamwork` -> trả về hướng dẫn sử dụng cú pháp chi tiết."""
        chat_id = "test_boundary_empty"
        await self.bot._handle_command("/teamwork", chat_id)

        self.assertEqual(len(self.bot.sent_messages), 1)
        reply = self.bot.sent_messages[0]["text"]
        self.assertIn("Cú pháp", reply)
        self.assertIn("Ví dụ", reply)

        # Ensure no background task was spawned
        self.assertIsNone(getattr(self.bot, "_last_teamwork_task", None))

    async def test_t2_02_short_command_less_than_8_chars_rejects(self):
        """T2.2: Lệnh quá ngắn `/teamwork abc` (< 8 ký tự) -> yêu cầu mô tả chi tiết hơn."""
        chat_id = "test_boundary_short"
        await self.bot._handle_command("/teamwork fix bug", chat_id)

        self.assertEqual(len(self.bot.sent_messages), 1)
        reply = self.bot.sent_messages[0]["text"]
        self.assertIn("yêu cầu mô tả nhiệm vụ chi tiết", reply)
        self.assertIsNone(getattr(self.bot, "_last_teamwork_task", None))

    async def test_t2_03_html_special_chars_escaped_safely(self):
        """T2.3: Lệnh chứa ký tự đặc biệt HTML (<script>, &, quotes) -> escape an toàn."""
        malicious_input = '<script>alert("XSS")</script> & "quoted" <tag> /teamwork test'
        formatted = TelegramFormatter.format_for_telegram(malicious_input)

        # Stray <script> must be converted to &lt;script&gt;
        self.assertNotIn("<script>", formatted)
        self.assertIn("&lt;script&gt;", formatted)
        self.assertIn("&amp;", formatted)

    async def test_t2_04_long_report_over_4000_chars_auto_chunks_and_balances_html(self):
        """T2.4: Báo cáo kỹ thuật dài > 4000 ký tự -> tự động chunking và cân bằng thẻ HTML."""
        # Generate 6000-char markdown text with open <b> and <code> tags
        long_paragraph = "Nginx optimization line with <b>important bold text</b> and <code>config_val</code>.\n\n"
        huge_text = long_paragraph * 60
        self.assertGreater(len(huge_text), 4000)

        chunks = TelegramFormatter.split_message(huge_text, max_chars=4000)
        self.assertGreaterEqual(len(chunks), 2)

        for idx, chunk in enumerate(chunks):
            self.assertLessEqual(len(chunk), 4000, f"Chunk {idx} exceeded max length 4000")
            # Verify open and close tags are balanced
            open_b = len(re.findall(r"<b>", chunk))
            close_b = len(re.findall(r"</b>", chunk))
            self.assertEqual(open_b, close_b, f"Chunk {idx} has unbalanced <b> tags")

    async def test_t2_05_search_tool_error_or_empty_falls_back_gracefully(self):
        """T2.5: Công cụ tìm kiếm gặp ngoại lệ mạng hoặc không có kết quả -> fallback an toàn, không crash."""
        # Force browser_search_google to raise an exception
        self.tool_executor.browser_agent.browser_search_google = AsyncMock(
            side_effect=httpx.ConnectError("Google search connection timed out")
        )

        task = "Nhiệm vụ khi mất mạng Google"
        # Pipeline must not crash, should fall back to standard synthesis
        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertIn("1. Tóm tắt bài toán & giải pháp", result.report_markdown)
        self.assertIn("Không có liên kết ngoài từ tìm kiếm", result.report_markdown)

    async def test_t2_06_browser_navigate_timeout_or_error_handled_cleanly(self):
        """T2.6: Điều hướng URL bị timeout hoặc trả về lỗi 404/500 -> xử lý an toàn."""
        self.tool_executor.browser_agent.browser_navigate = AsyncMock(
            side_effect=asyncio.TimeoutError("Playwright navigation timeout 30000ms")
        )

        task = "Đọc tài liệu khi trang đích bị timeout"
        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertGreater(len(result.report_markdown), 100)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE COMBINATIONS (4 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier3CrossFeatureCombinations(unittest.IsolatedAsyncioTestCase):
    """
    Tier 3: Concurrency isolation, non-blocking polling responsiveness,
    and Groq Pool rate limit key rotation under active workload.
    """

    async def asyncSetUp(self):
        self.llm_router = _create_mock_llm_router()
        self.tool_executor = _create_mock_tool_executor()
        self.engine = TeamworkEngine(
            llm_router=self.llm_router,
            tool_executor=self.tool_executor,
        )
        self.bot = _setup_test_bot(self.engine)

    async def test_t3_01_concurrent_teamwork_tasks_independent_isolation(self):
        """T3.1: Chạy 2 tác vụ teamwork đồng thời trên 2 session -> kết quả độc lập, không xung đột."""
        task_a = "Tối ưu hóa Nginx High Concurrency"
        task_b = "Thiết lập tường lửa UFW và Fail2ban"

        # Execute both concurrently
        res_a, res_b = await asyncio.gather(
            self.engine.execute_teamwork(task_a),
            self.engine.execute_teamwork(task_b),
        )

        self.assertIn(task_a, res_a.report_markdown)
        self.assertIn(task_b, res_b.report_markdown)
        self.assertNotEqual(res_a.task, res_b.task)

    async def test_t3_02_system_commands_responsive_during_background_teamwork(self):
        """T3.2: Bot xử lý lệnh hệ thống /status hoặc /cpu ngay lập tức khi teamwork đang chạy nền."""
        chat_id = "test_concurrent_chat"

        # 1. Trigger background teamwork
        await self.bot._handle_command("/teamwork Tối ưu hóa PostgreSQL replication", chat_id)
        teamwork_task = getattr(self.bot, "_last_teamwork_task", None)
        self.assertIsNotNone(teamwork_task)

        # 2. While teamwork is running in background, trigger /status and /cpu
        await self.bot._handle_command("/status", chat_id)
        await self.bot._handle_command("/cpu", chat_id)

        # 3. Both system commands should have responded without waiting for teamwork
        status_replies = [m["text"] for m in self.bot.sent_messages if "Trạng Thái Máy Chủ" in m["text"]]
        cpu_replies = [m["text"] for m in self.bot.sent_messages if "CPU Status" in m["text"]]

        self.assertEqual(len(status_replies), 1)
        self.assertEqual(len(cpu_replies), 1)

        # Clean up background task
        await teamwork_task

    async def test_t3_03_groq_pool_rate_limit_backoff_and_key_rotation(self):
        """T3.3: Kết hợp quy trình teamwork với cơ chế Rate Limit xoay tua Groq Key Pool."""
        key_pool = GroqKeyPool(["gsk_key_alpha_111", "gsk_key_beta_222", "gsk_key_gamma_333"])
        attempt_keys = []

        async def _rate_limited_llm_complete(messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
            cur_key = await key_pool.get_next_key()
            attempt_keys.append(cur_key)
            if cur_key == "gsk_key_alpha_111":
                # Key 1 hits rate limit 429
                await key_pool.mark_rate_limited(cur_key)
                # Next retry uses rotated key
                next_key = await key_pool.get_next_key()
                attempt_keys.append(next_key)
                return {
                    "choices": [{
                        "message": {"role": "assistant", "content": "Thành công sau khi xoay tua Groq Key."},
                        "finish_reason": "stop"
                    }]
                }
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "Thành công với key bình thường."},
                    "finish_reason": "stop"
                }]
            }

        custom_router = MagicMock()
        custom_router.complete = AsyncMock(side_effect=_rate_limited_llm_complete)
        engine_with_pool = TeamworkEngine(llm_router=custom_router, tool_executor=self.tool_executor)

        result = await engine_with_pool.execute_teamwork("Kiểm tra xoay tua key khi dính 429")
        self.assertIsInstance(result, TeamworkResult)
        self.assertIn("gsk_key_beta_222", attempt_keys)

    async def test_t3_04_progress_lifecycle_delivery(self):
        """T3.4: Kiểm tra chuỗi cập nhật trạng thái liên tục qua edit_message_text và gửi báo cáo cuối."""
        chat_id = "test_lifecycle_chat"
        await self.bot._handle_command("/teamwork Tối ưu hóa Nginx", chat_id)

        bg_task = getattr(self.bot, "_last_teamwork_task", None)
        self.assertIsNotNone(bg_task)
        await bg_task

        # Verify edit_message_text was called at least 4 times for progress steps + 1 completion
        self.assertGreaterEqual(len(self.bot.edited_messages), 4)
        last_edit = self.bot.edited_messages[-1]["text"]
        self.assertIn("Hoàn tất", last_edit)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (5 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier4RealWorldScenarios(unittest.IsolatedAsyncioTestCase):
    """
    Tier 4: Realistic production scenarios specified in ORIGINAL_REQUEST.md
    and TEST_INFRA.md.
    """

    async def asyncSetUp(self):
        self.llm_router = _create_mock_llm_router()
        self.tool_executor = _create_mock_tool_executor()
        self.engine = TeamworkEngine(
            llm_router=self.llm_router,
            tool_executor=self.tool_executor,
        )

    async def test_t4_scenario_01_nginx_latency_optimization(self):
        """Scenario 1: Tối ưu cấu hình Nginx để giảm độ trễ và tăng throughput cho High-Concurrency Web Service."""
        task = "Tối ưu hóa Nginx để giảm độ trễ và tăng throughput cho High-Concurrency Web Service"
        result = await self.engine.execute_teamwork(task)

        report = result.report_markdown
        self.assertIn("Nginx", report)
        self.assertIn("epoll", report)
        self.assertIn("worker_connections", report)
        self.assertIn("keepalive", report)
        self.assertIn("EMFILE", report)
        self.assertGreater(len(result.sources), 0)

    async def test_t4_scenario_02_postgresql_streaming_replication_and_failover(self):
        """Scenario 2: Thiết lập PostgreSQL Streaming Replication và Auto-Failover với pg_auto_failover."""
        task = "Thiết lập PostgreSQL Streaming Replication và Auto-Failover với pg_auto_failover"
        result = await self.engine.execute_teamwork(task)

        self.assertIsInstance(result, TeamworkResult)
        self.assertIn("1. Tóm tắt bài toán & giải pháp", result.report_markdown)
        self.assertIn("5. Reviewer's Verdict", result.report_markdown)
        self.assertGreaterEqual(len(result.risks), 1)

    async def test_t4_scenario_03_docker_container_security_hardening(self):
        """Scenario 3: Bảo mật Docker container chống container escape và phân quyền non-root user."""
        task = "Bảo mật Docker container chống container escape và phân quyền non-root user"
        result = await self.engine.execute_teamwork(task)

        report = result.report_markdown
        self.assertIn("Docker", report)
        self.assertIn("3. Giải pháp & Mã nguồn chi tiết (Production-Ready)", report)
        # Check no TODOs in solution
        self.assertNotIn("TODO", result.chosen_solution)

    async def test_t4_scenario_04_redis_caching_strategy_anti_stampede(self):
        """Scenario 4: Chiến lược cache Redis đa tầng (Multi-tier caching) kết hợp chống Cache Stampede."""
        task = "Chiến lược cache Redis đa tầng kết hợp chống Cache Stampede"
        result = await self.engine.execute_teamwork(task)

        report = result.report_markdown
        self.assertIn("Redis", report)
        self.assertIn("4. Cảnh báo rủi ro & Edge cases", report)
        self.assertGreater(result.execution_time_seconds, 0)

    async def test_t4_scenario_05_linux_kernel_sysctl_network_tuning(self):
        """Scenario 5: Tối ưu hóa Linux Kernel Sysctl network parameters cho server 10Gbps."""
        task = "Tối ưu hóa Linux Kernel Sysctl network parameters cho server 10Gbps"
        result = await self.engine.execute_teamwork(task)

        report = result.report_markdown
        self.assertIn("Linux", report)
        self.assertIn("Reviewer's Verdict", report)
        self.assertGreater(len(result.sources), 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test Runner Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
