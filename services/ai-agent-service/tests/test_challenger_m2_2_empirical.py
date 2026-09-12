"""
test_challenger_m2_2_empirical.py — Empirical stress testing suite for Milestone 2.

Challenger M2_2 Adversarial Harness:
1. send_video Telegram parse error fallback:
   - Stream consumption and f.seek(0) rewind verification (real bytes verification).
   - Counterfactual oracle: proof that missing seek(0) causes empty byte transfer.
   - HTML stripping, tag sanitization, and plain text fallback payload structure.
   - Double-failure resilience (both HTML and Plain Text fail).
   - Boundary limits (caption truncation at 1024 chars, None/empty captions).
2. Video > 50MB Safe Notifications:
   - Fast-path in telegram_bot._process_update notifies user safely with direct link.
   - AgentToolExecutor download_media_video returns safe message without throwing.
   - send_video oversized file (>50MB) immediate guard abort.
3. 100% Zero-Disk-Leak under ANY failure mode:
   - Exception during send_video -> disk cleaned up.
   - Exception during send_document fallback -> disk cleaned up.
   - Unexpected exception during caption formatting -> disk cleaned up.
   - asyncio.CancelledError -> disk cleaned up.
   - AgentToolExecutor download_media_video exceptions -> disk cleaned up.
   - Cleanup idempotency and robustness on missing/already-deleted files.
"""

import asyncio
import html
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import TelegramBot, _strip_html_tags
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.media_downloader import (
    MediaItem,
    VideoTooLargeError,
    TEMP_MEDIA_DIR,
    TELEGRAM_MAX_FILE_SIZE,
)


class TestSendVideoParseErrorFallbackEmpirical(unittest.IsolatedAsyncioTestCase):
    """Adversarial testing of send_video parse error fallback and f.seek(0) rewind."""

    async def asyncSetUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "test_bot_token_123"

    async def test_send_video_f_seek_rewind_empirical_consumption(self):
        """
        Empirically verify that when Telegram rejects entities:
        1. The initial post consumes the file stream to EOF.
        2. f.seek(0) resets the file pointer to byte 0.
        3. The second post reads the full byte stream (not 0 bytes!).
        """
        test_content = b"EMPIRICAL_MP4_PAYLOAD_CHALLENGER_M2_2_" * 1024  # ~38KB
        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            tf.write(test_content)
            temp_path = tf.name

        try:
            consumed_bytes_first_call = None
            consumed_bytes_second_call = None
            call_count = 0

            async def mock_post(url, data=None, files=None, timeout=None):
                nonlocal call_count, consumed_bytes_first_call, consumed_bytes_second_call
                call_count += 1
                video_file_obj = files["video"][1]
                read_data = video_file_obj.read()

                if call_count == 1:
                    consumed_bytes_first_call = read_data
                    resp = MagicMock()
                    resp.status_code = 400
                    resp.text = "Bad Request: can't parse entities: Character '<' is reserved and must be escaped"
                    return resp
                elif call_count == 2:
                    consumed_bytes_second_call = read_data
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = '{"ok": true, "result": {"message_id": 777}}'
                    return resp
                raise RuntimeError("Unexpected 3rd call")

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=mock_post)

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client

                success = await self.bot.send_video(
                    chat_id="chat_999",
                    video_path=temp_path,
                    caption="🎬 <b>Tiểu Bảo Bảo tải video với <unclosed_tag> &amp; ký tự đặc biệt</b>",
                    parse_mode="HTML",
                )

                self.assertTrue(success, "send_video must succeed via plain text fallback")
                self.assertEqual(call_count, 2, "Must execute exactly 2 POST attempts")

                # Verify Call 1 consumed full bytes
                self.assertEqual(len(consumed_bytes_first_call), len(test_content))
                self.assertEqual(consumed_bytes_first_call, test_content)

                # CRITICAL EMPIRICAL PROOF: Call 2 MUST have read the full bytes because of f.seek(0)
                self.assertEqual(len(consumed_bytes_second_call), len(test_content),
                                 "If f.seek(0) was missing, consumed_bytes_second_call would be 0 bytes!")
                self.assertEqual(consumed_bytes_second_call, test_content)

                # Verify Call 2 stripped parse_mode and cleaned HTML
                call2_args = mock_client.post.call_args_list[1]
                call2_data = call2_args[1]["data"]
                self.assertNotIn("parse_mode", call2_data)
                self.assertIn("Tiểu Bảo Bảo tải video với", call2_data["caption"])
                self.assertNotIn("<unclosed_tag>", call2_data["caption"])
                self.assertNotIn("<b>", call2_data["caption"])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_send_video_counterfactual_oracle_without_seek_fails(self):
        """
        Counterfactual Oracle: Prove that without seek(0), a second read of a stream returns b''.
        This mathematically validates our test harness logic.
        """
        test_bytes = b"TEST_STREAM_BYTES"
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(test_bytes)
            tpath = tf.name

        try:
            with open(tpath, "rb") as f:
                first_read = f.read()
                self.assertEqual(first_read, test_bytes)

                # Without seek(0):
                second_read_no_seek = f.read()
                self.assertEqual(second_read_no_seek, b"", "Reading EOF stream without seek returns empty bytes")

                # With seek(0):
                f.seek(0)
                second_read_with_seek = f.read()
                self.assertEqual(second_read_with_seek, test_bytes, "seek(0) successfully rewinds stream")
        finally:
            if os.path.exists(tpath):
                os.unlink(tpath)

    def test_strip_html_tags_adversarial_matrix(self):
        """Adversarial stress-testing of _strip_html_tags across malformed HTML and entity edge cases."""
        matrix = [
            ("<b>Bold</b>", "Bold"),
            ("<i>Italic</i>", "Italic"),
            ("<code>code_snippet</code>", "code_snippet"),
            ("<a href='https://example.com'>Anchor</a>", "Anchor"),
            ("<unclosed tag with text>Rest of caption", "Rest of caption"),
            ("Mixed &amp; Entities &lt;3 &gt;5 &quot;quoted&quot; &#39;single&#39;",
             "Mixed & Entities <3 >5 \"quoted\" 'single'"),
            ("<script>alert('xss')</script>Normal text", "alert('xss')Normal text"),
            ("<div><span><p>Deeply <b>nested</b></p></span></div>", "Deeply nested"),
            ("Text without any HTML tags at all.", "Text without any HTML tags at all."),
            ("", ""),
            ("🎬 <b>Tiêu đề cực hay: 'Tết này anh về'</b>\n👤 Kênh: <code>@vietnam</code>\n⏱ 45s",
             "🎬 Tiêu đề cực hay: 'Tết này anh về'\n👤 Kênh: @vietnam\n⏱ 45s"),
        ]
        for input_html, expected in matrix:
            actual = _strip_html_tags(input_html)
            self.assertEqual(actual, expected, f"Failed on input: {input_html}")

    async def test_send_video_double_failure_resilience(self):
        """Verify that when both HTML and plain text retry fail, send_video returns False gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"dummy")
            tpath = tf.name

        try:
            err_resp1 = MagicMock(status_code=400, text="can't parse entities: unclosed tag")
            err_resp2 = MagicMock(status_code=500, text="Internal Server Error from Telegram")

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=[err_resp1, err_resp2])

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_video(chat_id="123", video_path=tpath, caption="<b>Test</b>")
                self.assertFalse(res, "send_video must return False when fallback also fails")
                self.assertEqual(mock_client.post.call_count, 2)
        finally:
            if os.path.exists(tpath):
                os.unlink(tpath)

    async def test_send_video_caption_boundary_limits(self):
        """Verify handling when caption is None, empty, or exceeds 1024 characters."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"dummy")
            tpath = tf.name

        try:
            ok_resp = MagicMock(status_code=200, text='{"ok": true}')
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=ok_resp)

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client

                # Test 1: Caption is None
                res1 = await self.bot.send_video(chat_id="123", video_path=tpath, caption=None)
                self.assertTrue(res1)
                call1_data = mock_client.post.call_args[1]["data"]
                self.assertNotIn("caption", call1_data)

                # Test 2: Huge caption (>2000 chars) is safely truncated to 1024
                huge_caption = "A" * 2500
                res2 = await self.bot.send_video(chat_id="123", video_path=tpath, caption=huge_caption)
                self.assertTrue(res2)
                call2_data = mock_client.post.call_args[1]["data"]
                self.assertEqual(len(call2_data["caption"]), 1024)
        finally:
            if os.path.exists(tpath):
                os.unlink(tpath)

    async def test_send_video_precheck_aborts_oversized_files(self):
        """Verify send_video immediately aborts without API request when file exceeds 50MB."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"header")
            tpath = tf.name

        try:
            mock_client = MagicMock()
            mock_client.post = AsyncMock()

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client

                # Mock stat().st_size to 51MB
                with patch("pathlib.Path.stat") as mock_stat:
                    stat_mock = MagicMock()
                    stat_mock.st_size = 51 * 1024 * 1024  # 51MB
                    mock_stat.return_value = stat_mock

                    res = await self.bot.send_video(chat_id="123", video_path=tpath)
                    self.assertFalse(res, "send_video must reject files > 50MB")
                    mock_client.post.assert_not_called()
        finally:
            if os.path.exists(tpath):
                os.unlink(tpath)


class TestVideoTooLargeNotificationSafety(unittest.IsolatedAsyncioTestCase):
    """Adversarial testing of 50MB oversized video handling and safe user notifications."""

    async def asyncSetUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "test_token"
        self.bot.chat_id = "123456"
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.bot._pending_archives = {}
        self.bot._rate_limiter = MagicMock()
        self.bot._rate_limiter.acquire = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"message_id": 888})
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.delete_message = AsyncMock(return_value=True)

    async def test_fastpath_process_update_safe_warning_and_cleanup(self):
        """Verify fast-path catches VideoTooLargeError, warns user with direct link, and doesn't crash."""
        large_url = "https://www.youtube.com/watch?v=heavy_4k_video"
        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(
            side_effect=VideoTooLargeError("Dung lượng video (95.4MB) vượt quá giới hạn 50MB của Telegram Bot.")
        )

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 5001,
                "message": {
                    "chat": {"id": 123456},
                    "text": f"tải video {large_url}",
                    "message_id": 10,
                },
            }
            # Must not raise any exception
            await self.bot._process_update(update)

            # Verification: status message was deleted
            self.bot.delete_message.assert_awaited_once_with("123456", 888)

            # Verification: warning message sent to user
            self.bot.send_message.assert_awaited_once()
            call_text = self.bot.send_message.call_args[0][1]
            self.assertIn("50MB", call_text)
            self.assertIn(large_url, call_text)

    async def test_ai_agent_tool_download_media_video_video_too_large(self):
        """Verify AgentToolExecutor download_media_video catches VideoTooLargeError safely."""
        executor = AgentToolExecutor(MagicMock(), MagicMock())
        executor.telegram_bot = self.bot

        large_url = "https://www.facebook.com/reel/123456789999"
        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(
            side_effect=VideoTooLargeError("Video 70MB exceeds 50MB")
        )

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            result = await executor.execute_tool(
                tool_name="download_media_video",
                tool_args={"url": large_url},
                chat_id="123456",
            )

            self.assertIn("50MB", result)
            self.assertIn(large_url, result)
            self.assertTrue(result.startswith("⚠️"))


class TestZeroDiskLeakUnderAdversarialFailures(unittest.IsolatedAsyncioTestCase):
    """Rigorous empirical proof that temporary files and folders are ALWAYS wiped from disk."""

    async def asyncSetUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "test_token"
        self.bot.chat_id = "123456"
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.bot._pending_archives = {}
        self.bot._rate_limiter = MagicMock()
        self.bot._rate_limiter.acquire = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"message_id": 111})
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.delete_message = AsyncMock(return_value=True)
        self.bot.dream_engine = None
        self.bot.chat_with_agent = AsyncMock(return_value="AI Response")

    def _create_real_temp_media(self) -> tuple[Path, Path, MediaItem]:
        """Creates a real yt-dlp temporary folder and file on physical disk."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="media_ytdlp_stress_", dir=str(TEMP_MEDIA_DIR)))
        tmp_file = tmp_dir / "test_video.mp4"
        tmp_file.write_bytes(b"STRESS_TEST_REAL_DISK_CONTENT" * 100)

        item = MediaItem(
            file_path=str(tmp_file),
            title="Stress Test Video",
            author="Tester",
            duration=60,
            media_type="video",
            source_url="https://youtube.com/watch?v=stress",
            file_size=len(tmp_file.read_bytes()),
            is_temp_file=True,
        )
        return tmp_dir, tmp_file, item

    async def test_zero_disk_leak_fastpath_when_send_video_raises_network_error(self):
        """When send_video throws a network/HTTP exception, temporary files MUST be cleaned up."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()
        self.assertTrue(tmp_file.exists())
        self.assertTrue(tmp_dir.exists())

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=media_item)

        self.bot.send_video = AsyncMock(side_effect=ConnectionResetError("Peer reset connection"))

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 6001,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://youtu.be/stress",
                    "message_id": 20,
                },
            }
            await self.bot._process_update(update)

            # Verification: Zero-Disk-Leak confirmed on physical filesystem
            self.assertFalse(tmp_file.exists(), f"File {tmp_file} leaked after send_video failure!")
            self.assertFalse(tmp_dir.exists(), f"Directory {tmp_dir} leaked after send_video failure!")

    async def test_zero_disk_leak_fastpath_when_send_document_fallback_fails(self):
        """When send_video returns False and send_document raises, temporary files MUST be cleaned up."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()
        self.assertTrue(tmp_file.exists())
        self.assertTrue(tmp_dir.exists())

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=media_item)

        self.bot.send_video = AsyncMock(return_value=False)
        self.bot.send_document = AsyncMock(side_effect=TimeoutError("sendDocument timed out"))

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 6002,
                "message": {
                    "chat": {"id": 123456},
                    "text": "tải video https://youtu.be/stress",
                    "message_id": 21,
                },
            }
            await self.bot._process_update(update)

            # Verification: Zero-Disk-Leak confirmed
            self.assertFalse(tmp_file.exists(), f"File {tmp_file} leaked after fallback failure!")
            self.assertFalse(tmp_dir.exists(), f"Directory {tmp_dir} leaked after fallback failure!")

    async def test_zero_disk_leak_fastpath_when_caption_formatting_crashes(self):
        """When an unexpected exception occurs before send_video (e.g. caption formatting), cleanup runs."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()
        # Invalidate duration to something that triggers an error if formatted
        media_item.file_size = None  # Will cause TypeError in division

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=media_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 6003,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://youtu.be/stress",
                    "message_id": 22,
                },
            }
            await self.bot._process_update(update)

            # Verification: Zero-Disk-Leak confirmed
            self.assertFalse(tmp_file.exists(), f"File {tmp_file} leaked on format error!")
            self.assertFalse(tmp_dir.exists(), f"Directory {tmp_dir} leaked on format error!")

    async def test_zero_disk_leak_fastpath_on_cancelled_error(self):
        """When task is cancelled (asyncio.CancelledError), finally block MUST still clean disk."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=media_item)

        self.bot.send_video = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 6004,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://youtu.be/stress",
                    "message_id": 23,
                },
            }
            with self.assertRaises(asyncio.CancelledError):
                await self.bot._process_update(update)

            # Verification: Zero-Disk-Leak confirmed despite CancelledError
            self.assertFalse(tmp_file.exists(), f"File {tmp_file} leaked on CancelledError!")
            self.assertFalse(tmp_dir.exists(), f"Directory {tmp_dir} leaked on CancelledError!")

    async def test_zero_disk_leak_ai_agent_tool_on_exception(self):
        """When AgentToolExecutor download_media_video crashes, temporary files are cleaned up."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()
        self.assertTrue(tmp_file.exists())
        self.assertTrue(tmp_dir.exists())

        executor = AgentToolExecutor(MagicMock(), MagicMock())
        executor.telegram_bot = self.bot

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=media_item)

        self.bot.send_video = AsyncMock(side_effect=RuntimeError("Upload socket broken"))

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            result = await executor.execute_tool(
                tool_name="download_media_video",
                tool_args={"url": "https://youtu.be/stress"},
                chat_id="123456",
            )

            self.assertIn("sự cố khi tải video", result)
            # Verification: Zero-Disk-Leak confirmed
            self.assertFalse(tmp_file.exists(), f"File {tmp_file} leaked in AgentToolExecutor!")
            self.assertFalse(tmp_dir.exists(), f"Directory {tmp_dir} leaked in AgentToolExecutor!")

    def test_media_item_cleanup_idempotency_and_robustness(self):
        """Verify calling cleanup() multiple times or on missing paths does not raise exceptions."""
        tmp_dir, tmp_file, media_item = self._create_real_temp_media()
        self.assertTrue(tmp_file.exists())

        # First call cleans up
        media_item.cleanup()
        self.assertFalse(tmp_file.exists())
        self.assertFalse(tmp_dir.exists())

        # Repeated calls must succeed without error (idempotent)
        try:
            media_item.cleanup()
            media_item.cleanup()
        except Exception as e:
            self.fail(f"Repeated cleanup() raised unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
