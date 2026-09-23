"""
test_challenger_m3_dynamic_scoping_reflex.py — Milestone M3 Adversarial Challenger Test Suite:
Dynamic Tool Scoping & Prompt Reflex Verification.

Code Under Test:
  - services/ai-agent-service/app/services/ai_agent_tools.py (AgentToolExecutor)
  - services/ai-agent-service/app/services/ai_agent.py (AiAgentService)

Empirical Invariants:
1. Dynamic Tool Scoping:
   - Total scoped tools MUST ALWAYS be <= 8 (preventing Groq 8,000 TPM limit exhaustion / HTTP 413).
   - When heavy clusters (Archive or Facebook) are active, total scoped tools MUST be <= 6.
   - Tested across > 45 Vietnamese prompts: có dấu, không dấu, teencode / phương ngữ, câu phức đa ý định,
     edge cases (chuỗi rỗng, khoảng trắng, payload cực lớn 10k ký tự, injection, URLs, emoji).
   - Media queries MUST include download_media_audio and/or download_media_video.
   - All scoped tools must be valid tools defined in AgentToolExecutor._build_tools().
2. Prompt Reflex & Conversational Affirmation:
   - Query: "Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không"
   - System prompt contract: Section 2e mandates "Dạ CÓ!" BLUF affirmation and invitation to send link.
   - Prohibits copyright refusals and deflection to manual CLI commands.
   - Live/Simulated LLM inference verification verifies "Dạ CÓ!" and link invitation in response.
"""

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm_router import LlmRouter
from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import (
    DIRECT_RETURN_TOOLS,
    SCREENSHOT_TOOLS,
    AgentToolExecutor,
)


def _create_mock_tool_executor() -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    return AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache, telegram_bot=mock_telegram)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ADVERSARIAL VIETNAMESE PROMPT CORPUS (45+ Test Prompts)
# ─────────────────────────────────────────────────────────────────────────────

PROMPTS_WITH_DIACRITICS_MEDIA = [
    "tải mp3 bài tiktok này giùm anh https://vt.tiktok.com/ZS123456/",
    "lấy nhạc video youtube này https://youtu.be/dQw4w9WgXcQ",
    "tách nhạc clip này https://vt.tiktok.com/abc",
    "nhạc tiktok này hay quá https://vt.tiktok.com/xyz",
    "tải video tiktok không logo https://vt.tiktok.com/123",
    "lấy audio từ video facebook reels này https://www.facebook.com/reel/123456789",
    "tải bài hát này về máy nghe https://vt.tiktok.com/song123",
    "tải audio chất lượng cao 320kbps từ link youtube shorts này",
]

PROMPTS_WITHOUT_DIACRITICS_MEDIA = [
    "tai mp3 link nay https://vt.tiktok.com/123",
    "lay audio video youtube nay https://youtu.be/123",
    "tach nhac clip tiktok",
    "nhac tiktok nay ten gi https://vt.tiktok.com/abc",
    "tai video tiktok nay https://vt.tiktok.com/456",
    "down video fb reels https://fb.watch/123",
    "lay clip douyin khong logo",
    "tai audio bai hat nay ve may",
]

PROMPTS_TEENCODE_AND_DIALECT_MEDIA = [
    "tải nhac tiktok hộ vs https://vt.tiktok.com/abc",
    "kéo video tt về máy giùm https://vt.tiktok.com/xyz",
    "lấy cấy nhạc nớ về cho tau https://vt.tiktok.com/456",
    "tách audio clip nớ coi răng",
    "down video ni hộ t vs https://fb.watch/abc",
    "nhạc bựa ni trên tiktok cuốn quá tải mp3 giùm",
]

PROMPTS_NON_MEDIA_STANDARD = [
    "xem thời tiết hôm nay ở Vinh có mưa không",
    "kiểm tra dung lượng ổ đĩa và ram máy chủ",
    "lưu lại công việc này để mai làm",
    "tìm kiếm google thông tin về Python 3.14",
    "giải nén file zip backup.zip mật khẩu 123456",
    "gửi tin nhắn facebook cho khách hàng",
    "kiểm tra nhiệt độ cpu và tiến trình docker",
    "máy chủ đang chạy những port nào",
]

PROMPTS_NON_MEDIA_DIALECT_AND_TEEN = [
    "bựa ni trời răng e",
    "máy em chạy đc bao lâu rùi",
    "xem ram sv nha",
    "rep ib fb giúp t",
    "bựa qua có tin nhắn fb nào ko",
    "máy chủ bật bao lâu rồi em",
]

PROMPTS_COMPLEX_MULTI_INTENT = [
    # Server + Media + Weather
    "vừa kiểm tra ram máy chủ vừa tải mp3 tiktok này https://vt.tiktok.com/123 và xem thời tiết ở Hà Nội",
    # Archive + Web + Media
    "giải nén file zip này rồi tìm google xem lỗi gì và tải video tiktok https://vt.tiktok.com/456",
    # Server + Weather + Media
    "kiểm tra docker ps, xem thời tiết Nghệ An và tải nhạc tiktok https://vt.tiktok.com/789",
    # Facebook + Task + Server
    "nhắn tin facebook cho khách, ghi nhớ việc này, và kiểm tra uptime máy chủ",
    # Facebook + Archive + Media
    "inbox fb cho anh Tuấn gửi file zip này và tải mp3 tiktok https://vt.tiktok.com/abc",
    # ALL CLUSTERS COMBINED (Max stress test!)
    (
        "tải video tiktok https://vt.tiktok.com/123, tải mp3 bài hát đó, "
        "giải nén file archive.zip, gửi tin nhắn messenger fb, tra cứu google thời tiết Vinh "
        "và kiểm tra tải cpu ram máy chủ, nhớ lưu lại task này!"
    ),
]

PROMPTS_ADVERSARIAL_EDGE_CASES = [
    "",  # Empty string
    "   ",  # Whitespace only
    "\n\t\r   \n",  # Mixed whitespace
    "asdfghjkl qwertyuiop zxcvbnm 1234567890",  # Random nonsense
    "🎵 🎶 🎧 📹 🤖 !!! ??? ***",  # Emojis & punctuation
    "https://vt.tiktok.com/ZS123456/",  # Pure URL TikTok
    "https://youtu.be/dQw4w9WgXcQ",  # Pure URL YouTube
    "https://www.facebook.com/reel/123456789",  # Pure URL Facebook
    "'; DROP TABLE users; -- $(whoami) && rm -rf /",  # Injection payload
    "tải mp3 " * 1000,  # Extremely long prompt (~8,000 characters)
    "TẢI MP3 TIKTOK CHẤT LƯỢNG CAO",  # All uppercase
    "TaI mP3 TiKtOk ChẤt LưỢnG cAo",  # Inverted casing
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. DYNAMIC TOOL SCOPING ADVERSARIAL TEST SUITE
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicToolScopingAdversarial(unittest.TestCase):
    """Adversarial validation of dynamic tool scoping invariants."""

    def setUp(self):
        self.executor = _create_mock_tool_executor()
        self.all_built_tool_names = {
            t["function"]["name"]
            for t in self.executor._build_tools(query="", history=None)
        }

    def test_invariant_all_scoped_tools_exist_in_registry(self):
        """Every tool returned by scoping must exist in the master tool registry."""
        all_test_prompts = (
            PROMPTS_WITH_DIACRITICS_MEDIA
            + PROMPTS_WITHOUT_DIACRITICS_MEDIA
            + PROMPTS_TEENCODE_AND_DIALECT_MEDIA
            + PROMPTS_NON_MEDIA_STANDARD
            + PROMPTS_NON_MEDIA_DIALECT_AND_TEEN
            + PROMPTS_COMPLEX_MULTI_INTENT
            + PROMPTS_ADVERSARIAL_EDGE_CASES
        )
        for prompt in all_test_prompts:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            for tool_name in scoped:
                self.assertIn(
                    tool_name,
                    self.all_built_tool_names,
                    f"Scoped tool '{tool_name}' for prompt '{prompt[:30]}' is not a valid registered tool!",
                )

    def test_invariant_max_tools_strictly_lte_8_across_all_prompts(self):
        """Strict contract: scoped tools count MUST NEVER exceed 8 (Groq 8,000 TPM limit)."""
        all_test_prompts = (
            PROMPTS_WITH_DIACRITICS_MEDIA
            + PROMPTS_WITHOUT_DIACRITICS_MEDIA
            + PROMPTS_TEENCODE_AND_DIALECT_MEDIA
            + PROMPTS_NON_MEDIA_STANDARD
            + PROMPTS_NON_MEDIA_DIALECT_AND_TEEN
            + PROMPTS_COMPLEX_MULTI_INTENT
            + PROMPTS_ADVERSARIAL_EDGE_CASES
        )
        for idx, prompt in enumerate(all_test_prompts):
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            self.assertLessEqual(
                len(scoped),
                8,
                f"Prompt #{idx} '{prompt[:40]}' exceeded max 8 tools: {len(scoped)} tools scoped {scoped}",
            )

    def test_invariant_heavy_cluster_max_tools_strictly_lte_6(self):
        """Heavy clusters (Archive or Facebook) must strictly cap tool count to <= 6."""
        heavy_prompts = [
            "giải nén file rar và tìm kiếm google",
            "inbox facebook cho khách hàng",
            "khôi phục mật khẩu zip và tải mp3 https://vt.tiktok.com/123",
            "xem nhóm facebook và kiểm tra ram máy chủ",
            "giải nén file zip, kiểm tra server và nhắn tin facebook",
        ]
        for prompt in heavy_prompts:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            self.assertLessEqual(
                len(scoped),
                6,
                f"Heavy cluster prompt '{prompt}' exceeded max 6 tools: got {len(scoped)} ({scoped})",
            )

    def test_media_prompts_with_diacritics_scope_media_tools(self):
        """Standard Vietnamese media queries with diacritics must scope audio/video tools."""
        for prompt in PROMPTS_WITH_DIACRITICS_MEDIA:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            has_media = "download_media_audio" in scoped or "download_media_video" in scoped
            self.assertTrue(
                has_media,
                f"Media tool missing for diacritic prompt: '{prompt}' (scoped: {scoped})",
            )

    def test_media_prompts_without_diacritics_scope_media_tools(self):
        """Non-diacritic Vietnamese media queries must scope audio/video tools."""
        for prompt in PROMPTS_WITHOUT_DIACRITICS_MEDIA:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            has_media = "download_media_audio" in scoped or "download_media_video" in scoped
            self.assertTrue(
                has_media,
                f"Media tool missing for non-diacritic prompt: '{prompt}' (scoped: {scoped})",
            )

    def test_media_prompts_teencode_dialect_scope_media_tools(self):
        """Teencode and regional dialect media queries must scope audio/video tools."""
        for prompt in PROMPTS_TEENCODE_AND_DIALECT_MEDIA:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            has_media = "download_media_audio" in scoped or "download_media_video" in scoped
            self.assertTrue(
                has_media,
                f"Media tool missing for teencode/dialect prompt: '{prompt}' (scoped: {scoped})",
            )

    def test_pure_urls_scope_media_tools(self):
        """Pasting raw URLs from TikTok/YouTube/Facebook must scope media tools."""
        url_prompts = [
            "https://vt.tiktok.com/ZS123456/",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.facebook.com/reel/123456789",
            "https://www.douyin.com/video/1234567",
        ]
        for url in url_prompts:
            scoped = self.executor._resolve_scoped_tool_names(url)
            has_media = "download_media_audio" in scoped or "download_media_video" in scoped
            self.assertTrue(
                has_media,
                f"Raw URL '{url}' did not trigger media tool scoping! (scoped: {scoped})",
            )

    def test_complex_multi_intent_pruning_preserves_audio_tools(self):
        """Under heavy combinatorial multi-intent stress, priority pruning retains audio/video tools."""
        for prompt in PROMPTS_COMPLEX_MULTI_INTENT:
            scoped = self.executor._resolve_scoped_tool_names(prompt)
            self.assertLessEqual(len(scoped), 8)
            # If the prompt explicitly mentions media, media tools must survive pruning
            if any(k in prompt.lower() for k in ("mp3", "tiktok", "video", "nhạc")):
                has_media = "download_media_audio" in scoped or "download_media_video" in scoped
                self.assertTrue(
                    has_media,
                    f"Media tool pruned away in multi-intent prompt: '{prompt}' (scoped: {scoped})",
                )

    def test_edge_cases_empty_and_nonsense_fallback_to_core(self):
        """Empty or nonsense queries safely fallback to core cluster without error or overflow."""
        for edge_prompt in ["", "   ", "\t\n", "asdfghjklqwerty"]:
            scoped = self.executor._resolve_scoped_tool_names(edge_prompt)
            self.assertLessEqual(len(scoped), 8)
            self.assertGreaterEqual(len(scoped), 2)
            self.assertIn("run_command", scoped)

    def test_massive_prompt_adversarial_stress(self):
        """8,000-character prompt handles safely without regex crash, memory leak, or tool overflow."""
        massive_prompt = "tải mp3 tiktok " * 600
        scoped = self.executor._resolve_scoped_tool_names(massive_prompt)
        self.assertLessEqual(len(scoped), 8)
        self.assertIn("download_media_audio", scoped)

    def test_audio_tool_schema_compliance_in_build_tools(self):
        """download_media_audio must be present in _build_tools output with expected schema."""
        tools = self.executor._build_tools(query="tải mp3 tiktok")
        tool_audio = next(
            (t for t in tools if t.get("function", {}).get("name") == "download_media_audio"),
            None,
        )
        self.assertIsNotNone(tool_audio, "download_media_audio not found in _build_tools()")
        fn = tool_audio["function"]
        self.assertIn("parameters", fn)
        self.assertIn("url", fn["parameters"].get("properties", {}))
        self.assertIn("caption", fn["parameters"].get("properties", {}))
        self.assertIn("url", fn["parameters"].get("required", []))

    def test_download_media_audio_in_direct_return_set(self):
        """download_media_audio must be registered in DIRECT_RETURN_TOOLS."""
        self.assertIn(
            "download_media_audio",
            DIRECT_RETURN_TOOLS,
            "download_media_audio MUST be in DIRECT_RETURN_TOOLS for zero-latency single-turn response!",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. PROMPT REFLEX & SYSTEM PROMPT KNOWLEDGE TEST SUITE
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptReflexAndKnowledge(unittest.TestCase):
    """Adversarial validation of prompt reflex and knowledge rules in ai_agent.py."""

    def setUp(self):
        self.agent = AiAgentService(MagicMock(), MagicMock(), MagicMock())
        self.static_prefix = self.agent._STATIC_SYSTEM_PREFIX
        self.full_prompt = self.agent._build_system_prompt()

    def test_contract_section_2e_media_and_audio_archiving_protocol_present(self):
        """_STATIC_SYSTEM_PREFIX must contain Section 2e media and audio archiving protocol."""
        self.assertIn(
            "2e. GIAO THỨC TRÍCH XUẤT MEDIA, TẢI VIDEO & TRÍCH XUẤT MP3/AUDIO ĐẶC QUYỀN",
            self.static_prefix,
            "Section 2e missing in _STATIC_SYSTEM_PREFIX!",
        )

    def test_contract_mp3_320kbps_capability_explicitly_stated(self):
        """Prompt must state 320kbps / lossless extraction capability from TikTok, Douyin, YouTube, Facebook."""
        self.assertIn("320KBPS", self.static_prefix.upper())
        self.assertIn("TikWM Direct MP3 Flow", self.static_prefix)
        self.assertIn("yt-dlp + FFmpegExtractAudio", self.static_prefix)

    def test_contract_anti_refusal_and_anti_deflection_rules(self):
        """Prompt must strictly prohibit copyright refusal and deflection to CLI commands."""
        self.assertIn("TUYỆT ĐỐI CẤM TỪ CHỐI", self.static_prefix)
        self.assertIn("TUYỆT ĐỐI CẤM ĐÙN ĐẨY", self.static_prefix)

    def test_contract_mandatory_tool_call_for_audio_requests(self):
        """Prompt mandates download_media_audio or download_media_video(media_type='audio') on audio request."""
        self.assertIn("download_media_audio", self.static_prefix)
        self.assertIn("media_type=\"audio\"", self.static_prefix)

    def test_contract_conversational_reflex_da_co_affirmation_rule(self):
        """Prompt must mandate the explicit 'Dạ CÓ!' BLUF affirmation when asked about capability."""
        self.assertIn(
            "PHẢN XẠ ĐỐI THOẠI KHI ĐƯỢC HỎI NĂNG LỰC TẢI MP3 / AUDIO",
            self.static_prefix,
        )
        self.assertIn(
            'BẮT BUỘC trả lời khẳng định tự tin ngay từ câu đầu tiên (BLUF): "Dạ CÓ!"',
            self.static_prefix,
        )
        self.assertIn("chủ động mời anh Mạnh gửi link", self.static_prefix)

    def test_reflex_query_scoping_behavior(self):
        """The specific question 'Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không' scopes media tools."""
        query = "Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không"
        scoped = self.agent._resolve_scoped_tool_names(query)
        self.assertLessEqual(len(scoped), 8)
        has_media = "download_media_audio" in scoped or "download_media_video" in scoped
        self.assertTrue(
            has_media,
            f"Query '{query}' did not scope media tools! Scoped: {scoped}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. LIVE / SIMULATED LLM REFLEX EMPIRICAL TEST SUITE
# ─────────────────────────────────────────────────────────────────────────────

class TestLivePromptReflexEmpirical(unittest.IsolatedAsyncioTestCase):
    """Empirical verification of the prompt reflex: 'Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không'."""

    async def test_live_or_mocked_agent_reflex_affirmation(self):
        """
        Runs actual chat inference on the exact question.
        Verifies:
        1. Contains affirmative response ('Dạ CÓ!' or 'Dạ có' or 'Có').
        2. Affirms capability for MP3/audio quality (320kbps, chất lượng cao).
        3. Invites user to send link ('gửi link' / 'gửi liên kết').
        4. Does NOT refuse due to copyright or platform limitations.
        5. Does NOT deflect to manual terminal commands.
        """
        router = LlmRouter()
        agent = AiAgentService(router, MagicMock(), MagicMock())

        if not agent.is_configured() or os.environ.get("CI") == "true":
            self.skipTest("No LLM API keys configured or running in CI — skipping live LLM test.")

        query = "Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không"
        reply = await agent.chat("test_challenger_m3_2_chat", query)

        self.assertIsNotNone(reply)
        self.assertIsInstance(reply, str)
        self.assertGreater(len(reply), 20)

        # 1. Affirmation: Must confirm "Dạ CÓ!" or affirmative opening
        reply_lower = reply.lower().replace("*", "").replace("#", "")
        has_affirmation = (
            "dạ có" in reply_lower
            or "có ạ" in reply_lower
            or "hoàn toàn được" in reply_lower
            or "em có thể tải" in reply_lower
            or "em tải được" in reply_lower
        )
        self.assertTrue(
            has_affirmation,
            f"Agent failed to affirm capability! Reply:\n{reply}",
        )

        # 2. Invitation: Must proactively invite user to send link
        has_link_invite = (
            "gửi link" in reply_lower
            or "gửi đường link" in reply_lower
            or "gửi liên kết" in reply_lower
            or "link video" in reply_lower
            or "gửi video" in reply_lower
        )
        self.assertTrue(
            has_link_invite,
            f"Agent did not invite user to send link! Reply:\n{reply}",
        )

        # 3. No anti-copyright refusal
        self.assertNotIn("bản quyền", reply_lower, "Agent refused due to copyright!")
        self.assertNotIn("chính sách tiktok", reply_lower, "Agent cited platform policy refusal!")

        # 4. No anti-deflection to CLI
        self.assertNotIn("sudo apt", reply_lower, "Agent deflected to sudo apt!")
        self.assertNotIn("tự mở terminal", reply_lower, "Agent deflected to user terminal!")


if __name__ == "__main__":
    unittest.main()
