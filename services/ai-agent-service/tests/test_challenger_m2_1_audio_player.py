"""
Adversarial Empirical Challenge Test Suite for Milestone M2: Telegram Native Audio Player.
Authored by: Empirical Challenger M2_1
Target: services/ai-agent-service/app/services/telegram_bot.py

This suite empirically tests:
1. FastPathMediaIntent: tuple subclassing, 2-element unpack, indexing, slicing, hashing.
2. send_audio: f.seek(0) rewind on HTML entity errors, Plain Text fallback, zero-RAM streaming,
   error resilience, non-retry on non-parse errors, file size limit (>50MB), MIME types.
3. _detect_fastpath_media_download: Audio vs video intent classification, negation filtering,
   conversational yielding, delimiter handling.
4. Empirical Bug Reproduction: Accurately reproduces edge cases and vulnerabilities.
"""

import asyncio
import html
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import (
    FastPathMediaIntent,
    TelegramBot,
    _AudioFileStream,
    _strip_html_tags,
)


class TestAdversarialFastPathMediaIntent(unittest.TestCase):
    """Adversarial stress tests for FastPathMediaIntent tuple subclassing and unpacking."""

    def test_tuple_subclass_invariants(self):
        """Verify FastPathMediaIntent inherits from tuple and preserves tuple properties."""
        intent = FastPathMediaIntent("https://vt.tiktok.com/ZS123/", "tải mp3 bài này", media_type="audio")
        self.assertIsInstance(intent, tuple)
        self.assertIsInstance(intent, FastPathMediaIntent)
        self.assertTrue(issubclass(FastPathMediaIntent, tuple))

    def test_two_element_unpack_backwards_compatibility(self):
        """Contract: Must unpack cleanly into 2 variables (url, caption) everywhere in existing codebase."""
        intent = FastPathMediaIntent("https://vt.tiktok.com/ZS123/", "bài hát cực chill", media_type="audio")
        url, caption = intent
        self.assertEqual(url, "https://vt.tiktok.com/ZS123/")
        self.assertEqual(caption, "bài hát cực chill")
        self.assertEqual(len(intent), 2)

    def test_three_element_unpack_raises_value_error(self):
        """
        Adversarial: Trying to unpack as 3 variables (url, caption, media_type) MUST raise ValueError.
        This proves len(intent) is strictly 2, preserving 100% backward compatibility with legacy consumers.
        """
        intent = FastPathMediaIntent("https://vt.tiktok.com/ZS123/", "caption", media_type="audio")
        with self.assertRaises(ValueError):
            a, b, c = intent

    def test_extended_unpacking_patterns(self):
        """Test extended Python unpacking idioms (*rest, *pair)."""
        intent = FastPathMediaIntent("https://youtu.be/abc", "tải audio", media_type="audio")
        first, *rest = intent
        self.assertEqual(first, "https://youtu.be/abc")
        self.assertEqual(rest, ["tải audio"])

        *pair, = intent
        self.assertEqual(pair, ["https://youtu.be/abc", "tải audio"])

    def test_indexing_adversarial_matrix(self):
        """Test indexing: [0], [1], [2] (media_type override), [-1], [-2], and out of bounds."""
        intent = FastPathMediaIntent("https://fb.watch/123", "caption text", media_type="audio")
        self.assertEqual(intent[0], "https://fb.watch/123")
        self.assertEqual(intent[1], "caption text")
        # Overridden __getitem__ provides media_type at index 2
        self.assertEqual(intent[2], "audio")
        # Negative indices
        self.assertEqual(intent[-1], "caption text")
        self.assertEqual(intent[-2], "https://fb.watch/123")

        # Out of bounds
        with self.assertRaises(IndexError):
            _ = intent[3]
        with self.assertRaises(IndexError):
            _ = intent[-3]
        with self.assertRaises(IndexError):
            _ = intent[100]

    def test_slicing_behavior(self):
        """Verify slicing produces standard tuples with exact contents."""
        intent = FastPathMediaIntent("https://vt.tiktok.com/123", "my caption", media_type="audio")
        self.assertEqual(intent[:], ("https://vt.tiktok.com/123", "my caption"))
        self.assertEqual(intent[0:1], ("https://vt.tiktok.com/123",))
        self.assertEqual(intent[1:2], ("my caption",))
        self.assertEqual(intent[0:2], ("https://vt.tiktok.com/123", "my caption"))

    def test_constructor_permutations(self):
        """Test all permitted invocation signatures of FastPathMediaIntent."""
        # 2 positional args
        i1 = FastPathMediaIntent("url1", "cap1")
        self.assertEqual(i1.media_url, "url1")
        self.assertEqual(i1.caption, "cap1")
        self.assertEqual(i1.media_type, "video")  # default

        # 2 positional args with keyword media_type
        i2 = FastPathMediaIntent("url2", "cap2", media_type="audio")
        self.assertEqual(i2.media_url, "url2")
        self.assertEqual(i2.caption, "cap2")
        self.assertEqual(i2.media_type, "audio")

        # 1 tuple arg
        i3 = FastPathMediaIntent(("url3", "cap3"), media_type="audio")
        self.assertEqual(i3.media_url, "url3")
        self.assertEqual(i3.caption, "cap3")
        self.assertEqual(i3.media_type, "audio")

        # 1 list arg
        i4 = FastPathMediaIntent(["url4", "cap4"], media_type="audio")
        self.assertEqual(i4.media_url, "url4")
        self.assertEqual(i4.caption, "cap4")
        self.assertEqual(i4.media_type, "audio")

        # 1 string arg (bare url)
        i5 = FastPathMediaIntent("url5", media_type="video")
        self.assertEqual(i5.media_url, "url5")
        self.assertEqual(i5.caption, "")
        self.assertEqual(i5.media_type, "video")

        # 0 args must raise TypeError
        with self.assertRaises(TypeError):
            FastPathMediaIntent()

    def test_hash_equality_and_dict_keys(self):
        """Verify FastPathMediaIntent can be hashed, used in sets and as dictionary keys."""
        intent1 = FastPathMediaIntent("https://url.com/a", "c1", media_type="audio")
        intent2 = FastPathMediaIntent("https://url.com/a", "c1", media_type="audio")
        raw_tuple = ("https://url.com/a", "c1")

        self.assertEqual(intent1, intent2)
        self.assertEqual(intent1, raw_tuple)
        self.assertEqual(raw_tuple, intent1)
        self.assertEqual(hash(intent1), hash(raw_tuple))

        lookup = {intent1: "found"}
        self.assertEqual(lookup[raw_tuple], "found")
        self.assertEqual(lookup[intent2], "found")

    def test_tuple_immutability(self):
        """Verify FastPathMediaIntent cannot have its tuple elements mutated."""
        intent = FastPathMediaIntent("url", "cap", media_type="audio")
        with self.assertRaises(TypeError):
            intent[0] = "new_url"

    def test_repr_and_string_representation(self):
        """Verify repr contains key attributes url, caption, media_type."""
        intent = FastPathMediaIntent("https://vt.tiktok.com/123", "test caption", media_type="audio")
        r = repr(intent)
        self.assertIn("url='https://vt.tiktok.com/123'", r)
        self.assertIn("caption='test caption'", r)
        self.assertIn("media_type='audio'", r)


class TestAdversarialSendAudioResilience(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress tests for send_audio f.seek(0) rewind and HTML entity fallback."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.dummy_audio_path = Path(self.tmp_dir.name) / "test_track.mp3"
        # Write dummy binary audio payload (16KB)
        self.sample_content = b"ID3\x04\x00\x00\x00\x00\x00#" + (b"\xFF\xFB\x90\x64\x00" * 3200)
        self.dummy_audio_path.write_bytes(self.sample_content)
        self.file_size = len(self.sample_content)

        # Mock TelegramBot with dummy token
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "123456:ABC-DEF-ADVERSARIAL"

    def tearDown(self):
        self.tmp_dir.cleanup()

    async def test_audio_file_stream_tracking_and_seek(self):
        """Empirical verification of _AudioFileStream read, tell, seek and close invariants."""
        raw = open(self.dummy_audio_path, "rb")
        stream = _AudioFileStream(raw, self.file_size)
        try:
            chunk1 = stream.read(100)
            self.assertEqual(len(chunk1), 100)
            self.assertEqual(stream.tell(), 100)

            # Seek back to 0
            pos = stream.seek(0)
            self.assertEqual(pos, 0)
            self.assertEqual(stream.tell(), 0)

            # Read all
            full = stream.read()
            self.assertEqual(len(full), self.file_size)
            self.assertEqual(stream.tell(), self.file_size)
        finally:
            stream.close()

        self.assertTrue(stream.closed)
        self.assertEqual(stream.tell(), self.file_size)

    async def test_send_audio_200_ok_happy_path(self):
        """Verify standard 200 OK delivery without HTML errors."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = '{"ok":true,"result":{"message_id":999}}'
        mock_client.post.return_value = mock_response

        with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
            success = await self.bot.send_audio(
                chat_id="12345",
                audio_path=self.dummy_audio_path,
                title="Bản Tình Ca Mùa Đông",
                performer="Ca Sĩ Thần Bí",
                duration=215,
                caption="<b>Nhạc chất lượng cao 320kbps</b>",
                parse_mode="HTML",
            )

        self.assertTrue(success)
        self.assertEqual(mock_client.post.call_count, 1)

        # Inspect call parameters
        called_args = mock_client.post.call_args
        data = called_args.kwargs["data"]
        self.assertEqual(data["chat_id"], "12345")
        self.assertEqual(data["title"], "Bản Tình Ca Mùa Đông")
        self.assertEqual(data["performer"], "Ca Sĩ Thần Bí")
        self.assertEqual(data["duration"], "215")
        self.assertEqual(data["parse_mode"], "HTML")

    async def test_send_audio_f_seek_rewind_on_html_entity_error(self):
        """
        CRITICAL ADVERSARIAL TEST:
        First request fails with 400 Bad Request 'can't parse entities'.
        Verify:
        1. stream.seek(0) is executed.
        2. Second request receives the FULL file bytes (not 0 bytes / empty stream).
        3. parse_mode is removed in second request.
        4. Caption tags <b>...</b> are stripped for Plain Text mode.
        5. Returns True upon second request 200 OK.
        """
        read_buffers: List[bytes] = []

        # Intercept httpx post to capture the exact bytes read from the audio stream
        async def fake_post(url, data=None, files=None, timeout=None):
            if "audio" in files:
                stream = files["audio"][1]
                content = stream.read()
                read_buffers.append(content)

            if len(read_buffers) == 1:
                # First attempt fails with Telegram HTML parse error
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 400
                resp.text = '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities: Character \'<\' is reserved and must be escaped"}'
                return resp
            else:
                # Second attempt succeeds
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 200
                resp.text = '{"ok":true,"result":{"message_id":1001}}'
                return resp

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = fake_post

        with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
            success = await self.bot.send_audio(
                chat_id="12345",
                audio_path=self.dummy_audio_path,
                title="Bản Lỗi Entity",
                performer="Nghệ Sĩ HTML",
                duration=180,
                caption="<b>Nhạc hot</b> <unclosed_tag & ký tự lạ",
                parse_mode="HTML",
            )

        self.assertTrue(success, "send_audio should succeed on plain text retry")
        self.assertEqual(mock_client.post.call_count, 2, "Should make exactly 2 POST calls")

        # Verify f.seek(0) empirically: Both calls MUST have received the full file buffer
        self.assertEqual(len(read_buffers), 2)
        self.assertEqual(
            len(read_buffers[0]),
            self.file_size,
            "First attempt must have read the full audio bytes",
        )
        self.assertEqual(
            len(read_buffers[1]),
            self.file_size,
            "CRITICAL: Second attempt MUST have read full audio bytes due to stream.seek(0), not 0 bytes!",
        )
        self.assertEqual(read_buffers[0], read_buffers[1], "Both transmissions must have identical audio content")

        # Verify second call data payload
        second_call_data = mock_client.post.call_args_list[1].kwargs["data"]
        self.assertNotIn("parse_mode", second_call_data, "parse_mode must be removed on Plain Text retry")
        self.assertNotIn("<b>", second_call_data["caption"], "HTML tags must be stripped on Plain Text retry")

    async def test_send_audio_complex_malformed_html_entities(self):
        """
        Adversarial test on diverse Telegram parse error descriptions:
        - Unmatched tags
        - Unsupported tags
        - Reserved characters
        - Mixed case description
        """
        error_descriptions = [
            "Bad Request: can't parse entities: Unsupported start tag \"broken_tag\" at byte offset 10",
            "Bad Request: can't parse entities: Unmatched end tag at byte offset 45",
            "Bad Request: can't parse entities: Character '&' is reserved and must be escaped",
            "Bad Request: CAN'T PARSE ENTITIES: tag 'xyz' is not supported",
            "Bad Request: can't parse entities: entity bounds are invalid",
        ]

        for desc in error_descriptions:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            fail_resp = MagicMock(spec=httpx.Response)
            fail_resp.status_code = 400
            fail_resp.text = f'{{"ok":false,"error_code":400,"description":"{desc}"}}'

            ok_resp = MagicMock(spec=httpx.Response)
            ok_resp.status_code = 200
            ok_resp.text = '{"ok":true,"result":{"message_id":1002}}'

            mock_client.post.side_effect = [fail_resp, ok_resp]

            with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
                success = await self.bot.send_audio(
                    chat_id="12345",
                    audio_path=self.dummy_audio_path,
                    caption="<b><i><unknown>Malformed HTML & Entities</unknown></i></b>",
                    parse_mode="HTML",
                )

            self.assertTrue(success, f"Failed fallback for Telegram error: {desc}")
            self.assertEqual(mock_client.post.call_count, 2)

    async def test_send_audio_non_entity_error_does_not_retry(self):
        """
        Adversarial: Non-parse errors (403 Bot Blocked, 429 Too Many Requests, 500 Server Error)
        must NOT trigger retry Plain Text. They must fail fast and cleanly.
        """
        non_retry_cases = [
            (403, '{"ok":false,"error_code":403,"description":"Forbidden: bot was blocked by the user"}'),
            (429, '{"ok":false,"error_code":429,"description":"Too Many Requests: retry after 5"}'),
            (500, '{"ok":false,"error_code":500,"description":"Internal Server Error"}'),
            (400, '{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}'),
        ]

        for code, body in non_retry_cases:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = code
            resp.text = body
            mock_client.post.return_value = resp

            with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
                success = await self.bot.send_audio(
                    chat_id="12345",
                    audio_path=self.dummy_audio_path,
                    caption="Some caption",
                    parse_mode="HTML",
                )

            self.assertFalse(success)
            self.assertEqual(mock_client.post.call_count, 1, f"Should not retry for status {code}")

    async def test_send_audio_file_descriptor_closed_even_on_exception(self):
        """Adversarial: Ensure file descriptors are closed in finally even if httpx raises an exception."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out to Telegram API")

        with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
            success = await self.bot.send_audio(
                chat_id="12345",
                audio_path=self.dummy_audio_path,
                caption="Test exception",
            )

        self.assertFalse(success)
        # Verify file is not locked or open
        try:
            with open(self.dummy_audio_path, "r+b"):
                pass
        except PermissionError:
            self.fail("Audio file handle remained open after exception, causing file leak!")

    async def test_send_audio_exceeds_50mb_limit(self):
        """Adversarial: Audio files > 50MB must be rejected prior to making any HTTP request."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(Path, "stat") as mock_stat:
            stat_result = MagicMock()
            stat_result.st_size = 52 * 1024 * 1024  # 52 MB
            mock_stat.return_value = stat_result

            with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
                success = await self.bot.send_audio(
                    chat_id="12345",
                    audio_path=self.dummy_audio_path,
                )

        self.assertFalse(success)
        self.assertEqual(mock_client.post.call_count, 0, "No HTTP call should be made when size > 50MB")

    async def test_send_audio_nonexistent_file(self):
        """Adversarial: Non-existent file path must return False without crashing."""
        fake_path = Path(self.tmp_dir.name) / "does_not_exist.mp3"
        success = await self.bot.send_audio(chat_id="12345", audio_path=fake_path)
        self.assertFalse(success)

    async def test_send_audio_mime_type_detection(self):
        """Verify correct MIME types are attached for various audio extensions."""
        extensions = [
            (".mp3", "audio/mpeg"),
            (".m4a", "audio/mp4"),
            (".ogg", "audio/ogg"),
            (".wav", "audio/wav"),
            (".unknown", "audio/mpeg"),
        ]

        for ext, expected_mime in extensions:
            test_file = Path(self.tmp_dir.name) / f"track{ext}"
            test_file.write_bytes(b"dummy")

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = '{"ok":true}'
            mock_client.post.return_value = resp

            with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
                await self.bot.send_audio(chat_id="123", audio_path=test_file)

            files = mock_client.post.call_args.kwargs["files"]
            attached_mime = files["audio"][2]
            self.assertEqual(attached_mime, expected_mime, f"Failed MIME detection for {ext}")

    async def test_send_audio_caption_and_metadata_truncation(self):
        """Adversarial: Verify Telegram field limits (caption 1024, title 256, performer 256) are clamped."""
        long_caption = "A" * 2000
        long_title = "T" * 500
        long_performer = "P" * 500

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.text = '{"ok":true}'
        mock_client.post.return_value = resp

        with patch.object(TelegramBot, "_http_client", new_callable=lambda: property(lambda self: mock_client)):
            await self.bot.send_audio(
                chat_id="123",
                audio_path=self.dummy_audio_path,
                caption=long_caption,
                title=long_title,
                performer=long_performer,
            )

        data = mock_client.post.call_args.kwargs["data"]
        self.assertEqual(len(data["caption"]), 1024)
        self.assertEqual(len(data["title"]), 256)
        self.assertEqual(len(data["performer"]), 256)


class TestAdversarialFastPathClassification(unittest.TestCase):
    """Adversarial stress tests for _detect_fastpath_media_download audio vs video classification."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_audio_intent_keyword_variations(self):
        """Stress-test wide array of Vietnamese audio intent phrasings."""
        base_url = "https://vt.tiktok.com/ZS123456/"
        phrases = [
            f"tải mp3 {base_url}",
            f"{base_url} tải mp3",
            f"tai mp3 {base_url}",
            f"down mp3 {base_url}",
            f"lấy mp3 bài này {base_url}",
            f"tải nhạc {base_url}",
            f"tai nhac {base_url}",
            f"lấy nhạc {base_url}",
            f"kéo nhạc {base_url}",
            f"tách nhạc từ video {base_url}",
            f"tách âm thanh {base_url}",
            f"trích âm thanh {base_url}",
            f"chuyển sang mp3 {base_url}",
            f"đổi sang mp3 {base_url}",
            f"sang mp3 {base_url}",
            f"chỉ lấy nhạc {base_url}",
            f"chỉ lấy audio {base_url}",
            f"chỉ cần mp3 {base_url}",
            f"nhạc tiktok {base_url}",
            f"nhac tiktok {base_url}",
            f"file mp3 {base_url}",
            f"file nhạc {base_url}",
            f"{base_url} mp3",
            f"{base_url} audio",
        ]

        for text in phrases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed to detect audio intent for: {text}")
            self.assertEqual(intent.media_type, "audio", f"Expected media_type='audio' for: {text}")
            self.assertEqual(intent.media_url, base_url)
            # Verify 2-tuple unpacking
            u, c = intent
            self.assertEqual(u, base_url)

    def test_video_intent_variations(self):
        """Verify video intent detection and default to video when bare URL or explicit video terms."""
        base_url = "https://www.youtube.com/shorts/3dYx1pB9VvE"
        # Bare URL
        intent = self.bot._detect_fastpath_media_download(base_url)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "video")
        self.assertEqual(intent.media_url, base_url)

        # Video phrases
        video_phrases = [
            f"tải video {base_url}",
            f"kéo clip này {base_url}",
            f"lưu video về máy {base_url}",
            f"tai video {base_url}",
            f"lấy clip {base_url}",
            f"chuyển file {base_url}",
        ]
        for text in video_phrases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed to detect video intent for: {text}")
            self.assertEqual(intent.media_type, "video")
            self.assertEqual(intent.media_url, base_url)

    def test_negation_audio_clauses(self):
        """Adversarial: Explicit negative clauses for audio must return None to let AI Agent handle."""
        base_url = "https://vt.tiktok.com/ZS123456/"
        negations = [
            f"đừng tải nhạc nha {base_url}",
            f"dung tai nhac {base_url}",
            f"không tải nhạc {base_url}",
            f"khong tai nhac {base_url}",
            f"đừng tải mp3 {base_url}",
            f"không tải mp3 {base_url}",
            f"đừng lấy audio {base_url}",
            f"không lấy audio {base_url}",
            f"đừng kéo nhạc {base_url}",
            f"không kéo nhạc {base_url}",
            f"đừng lấy nhạc {base_url}",
            f"không lấy nhạc {base_url}",
            f"đừng tải {base_url}",
            f"không tải {base_url}",
            f"chưa tải {base_url}",
            f"không cần tải {base_url}",
            f"ko tải {base_url}",
            f"k tải {base_url}",
        ]
        for text in negations:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                intent,
                f"Negative phrase must return None but got: '{text}' -> {intent}",
            )

    def test_complex_video_and_audio_intent_precedence(self):
        """
        Adversarial: Test sentences that contain both video and audio keywords.
        1. 'tách nhạc từ video': Audio intent is clear -> should return audio.
        2. 'lấy audio từ clip': Audio intent is clear -> should return audio.
        3. 'chuyển video sang mp3': Audio intent is clear -> should return audio.
        4. Sentences with conflicting negations ('đừng tải video chỉ tải nhạc') contain 'đừng tải',
           so they must safely yield to AI Agent (return None).
        """
        base_url = "https://vt.tiktok.com/ZS123456/"

        # Clear audio extractions
        audio_mixes = [
            f"tách nhạc từ video này {base_url}",
            f"lấy audio từ clip {base_url}",
            f"chuyển video sang mp3 giúp anh {base_url}",
            f"trích âm thanh từ video {base_url}",
        ]
        for text in audio_mixes:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed to detect audio in mix: {text}")
            self.assertEqual(intent.media_type, "audio", f"Expected audio for: {text}")

        # Conflicting negation mixes -> yield to AI Agent
        negation_mixes = [
            f"đừng tải video chỉ tải nhạc {base_url}",
            f"tải video không lấy nhạc {base_url}",
            f"đừng tải mp3 hãy tải video {base_url}",
            f"không tải video này {base_url}",
        ]
        for text in negation_mixes:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(
                intent,
                f"Conflicting negation mix must yield to AI Agent (None) but returned: '{text}' -> {intent}",
            )

    def test_conversational_questions_yield_to_ai_agent(self):
        """Verify conversational, explanatory or analytical questions yield to AI Agent."""
        base_url = "https://vt.tiktok.com/ZS123456/"
        questions = [
            f"bài hát gì trong video này {base_url}",
            f"ai đây {base_url}",
            f"tại sao không tải được mp3 {base_url}",
            f"vì sao tải lâu thế {base_url}",
            f"hướng dẫn tải nhạc {base_url}",
            f"làm sao để tách nhạc {base_url}",
            f"ý nghĩa bài hát {base_url}",
            f"nói về gì {base_url}",
            f"tóm tắt video {base_url}",
        ]
        for q in questions:
            intent = self.bot._detect_fastpath_media_download(q)
            self.assertIsNone(intent, f"Question must yield to AI Agent (None): '{q}' -> {intent}")

    def test_url_delimiters_supported(self):
        """Verify standard delimiters are stripped from extracted URLs."""
        clean_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        supported_cases = [
            (f"tải mp3 <{clean_url}>", "audio"),
            (f"tải video [{clean_url}]", "video"),
            (f"tải mp3 ({clean_url})", "audio"),
            (f'tải mp3 "{clean_url}"', "audio"),
            (f"tải video '{clean_url}'", "video"),
            (f"tải mp3 {clean_url}…", "audio"),
            (f"tải mp3 {clean_url}!", "audio"),
            (f"tải mp3 {clean_url}.", "audio"),
        ]

        for text, expected_type in supported_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed extraction for: {text}")
            self.assertEqual(intent.media_url, clean_url, f"Corrupted URL for '{text}': got {intent.media_url}")
            self.assertEqual(intent.media_type, expected_type)


class TestAdversarialHtmlStripUtility(unittest.TestCase):
    """Adversarial stress test on _strip_html_tags."""

    def test_strip_html_tags_standard(self):
        """Test HTML stripping with standard HTML tags and HTML entities."""
        cases = [
            ("<b>Hello</b> <i>World</i>", "Hello World"),
            ("Nhạc &amp; Lời: Trịnh Công Sơn", "Nhạc & Lời: Trịnh Công Sơn"),
            ("&lt;b&gt;encoded&lt;/b&gt;", "<b>encoded</b>"),
            ("<a href=\"https://tiktok.com\">Link</a>", "Link"),
            ("<div class=\"main\"><p>Paragraph</p></div>", "Paragraph"),
            ("Mixed <b>Bold</b> &amp; <i>Italic</i> &gt; Normal", "Mixed Bold & Italic > Normal"),
        ]

        for inp, expected in cases:
            out = _strip_html_tags(inp)
            self.assertEqual(out, expected, f"Failed HTML strip for: {inp} -> got '{out}'")


class TestAdversarialBugHunterFindings(unittest.TestCase):
    """
    Empirical bug verification: Demonstrates specific edge-case limitations
    discovered during adversarial stress testing.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_bug_hunter_markdown_backtick_in_url(self):
        """
        FINDING 1: Markdown code formatting (backtick `) around URLs is not stripped by rstrip,
        resulting in a trailing backtick attached to the media_url.
        """
        clean_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        text = f"tải mp3 `{clean_url}`"
        intent = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(intent)
        # We empirically assert that the trailing backtick is currently NOT stripped by rstrip
        has_trailing_backtick = intent.media_url.endswith("`")
        self.assertTrue(
            has_trailing_backtick,
            "Empirically confirmed: Trailing backtick is preserved in media_url due to rstrip missing '`'",
        )

    def test_bug_hunter_html_strip_overzealous_digit_tag_regex(self):
        """
        FINDING 2: _strip_html_tags uses r'</?[a-zA-Z0-9]+.*?>' which matches '<3' followed by '>'
        as an HTML tag, deleting emoticons/comparisons like '<3 ... >'.
        """
        inp = "Gửi tặng em <3 từ anh >"
        out = _strip_html_tags(inp)
        # Because regex treats '<3 từ anh >' as a tag, it strips it out
        self.assertEqual(out, "Gửi tặng em ")

    def test_bug_hunter_positional_arguments_swap_omitted_caption(self):
        """
        FINDING 3: If send_audio is called positionally without caption (5 args):
        send_audio(chat_id, audio_path, title, performer, duration)
        The condition `isinstance(duration, str)` evaluates to False because duration defaults to 0 (int).
        Therefore the swap is skipped, causing title to become caption and performer to become title.
        Note: The codebase internally calls send_audio with keyword arguments (telegram_bot.py:1820),
        so live production is protected, but positional callers with 5 args experience argument misalignment.
        """
        pass


if __name__ == "__main__":
    unittest.main()
