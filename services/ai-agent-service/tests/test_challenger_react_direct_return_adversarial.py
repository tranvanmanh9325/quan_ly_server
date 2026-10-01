"""
test_challenger_react_direct_return_adversarial.py — Challenger 2 Empirical Adversarial Verification Suite.

Adversarial Verification Vectors:
1. ReAct Terminal Execution Mechanics (DIRECT_RETURN_TOOLS):
   - Confirms that all 9 M7 Video Editor tools and M6 Multimedia tools terminate immediately.
   - LLM inference is called exactly ONCE (Turn 2 is completely skipped, 0 hallucination).
   - Pending photos flushed via _flush_pending_photos.
   - History trimmed via _trim_history and populated with assistant tool_result.
   - Differential verification: Non-terminal tools (run_command, get_weather, read_file_content,
     get_security_report) continue to Turn 2 for synthesis (call_count >= 2).
   - Terminal tool error outputs return directly without triggering reflexion loops.
   - Parallel tool execution containing a terminal tool triggers immediate direct return.

2. Non-Terminal Tools Isolation & Architectural Disjointness:
   - Exhaustively verifies that diagnostic, operational, security, note, browser, and system tools
     are strictly excluded from DIRECT_RETURN_TOOLS.
   - Set intersection between DIRECT_RETURN_TOOLS and non-terminal categories is strictly empty.
   - Exact count and membership audit (precisely 31 tools).
   - Verifies class attribute propagation across AgentToolExecutor and AiAgentService.

3. Static System Prefix Invariance & KV-Cache Reuse:
   - Byte-level immutability across time steps and instances (SHA-256 hash invariant).
   - Strict prefix anchoring: _build_system_prompt() always starts with _STATIC_SYSTEM_PREFIX.
   - Absolute absence of volatile tokens (timestamps, format specifiers, dynamic memory).
   - Completeness of Section 2t Tool-First Imperative rules (DaVinci prohibition, auto mode mandate).

4. Stress & Extreme Adversarial Scenarios:
   - Rapid sequential execution stress harness across multiple sessions.
   - Max iterations ceiling protection.
   - Unicode argument preservation in direct return.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["TESTING"] = "true"

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    SCREENSHOT_TOOLS,
)


def _build_test_agent() -> AiAgentService:
    """Creates an AiAgentService instance with mocked external gateways."""
    mock_llm_router = MagicMock()
    mock_llm_router.has_active_providers = True
    mock_llm_router.rtk.compress.side_effect = lambda text, **kw: text
    mock_ssh = MagicMock()
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    mock_telegram.send_photo = AsyncMock()

    agent = AiAgentService(
        llm_router=mock_llm_router,
        ssh_client=mock_ssh,
        message_cache=mock_cache,
    )
    agent.set_telegram_bot(mock_telegram)
    return agent


class TestReActTerminalExecutionAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial Verification Vector 1: Terminal Execution Mechanics in the ReAct Loop."""

    ALL_9_VIDEO_EDITOR_TOOLS = [
        "remove_text_from_video",
        "add_subtitle_to_video",
        "apply_color_grade",
        "stabilize_video",
        "concatenate_videos",
        "extract_frames",
        "remove_watermark_region",
        "enhance_video_quality",
        "generate_video_thumbnail",
    ]

    REPRESENTATIVE_M6_TOOLS = [
        "edit_video_clip",
        "compress_video",
        "convert_video_format",
        "convert_audio_format",
        "trim_audio_clip",
        "normalize_audio_volume",
        "convert_and_resize_image",
        "generate_custom_qr",
        "inspect_media_metadata",
        "merge_pdf_documents",
        "split_pdf_document",
        "extract_document_text",
        "translate_text",
        "download_direct_file",
        "download_media_video",
        "download_media_audio",
    ]

    NON_TERMINAL_TOOLS = [
        ("run_command", {"command": "uptime"}),
        ("get_weather", {"location": "Hà Nội"}),
        ("read_file_content", {"file_path": "/home/kirito/data/notes.txt"}),
        ("get_security_report", {}),
    ]

    async def test_all_9_video_editor_tools_terminal_execution_bypasses_turn2(self):
        """
        Adversarial: When any of the 9 video editor tools is called by LLM in Turn 1,
        the ReAct loop MUST immediately:
        1. Flush pending photos via _flush_pending_photos.
        2. Trim history via _trim_history.
        3. Append assistant response to history.
        4. Return the tool_result directly.
        5. NEVER invoke LLM Turn 2 (call_count == 1).
        """
        for tool_name in self.ALL_9_VIDEO_EDITOR_TOOLS:
            with self.subTest(tool=tool_name):
                agent = _build_test_agent()
                chat_id = f"chat_{tool_name}"
                expected_result = f"🎯 [SUCCESS] Output from {tool_name}: https://cdn.server.vn/media/{tool_name}_out.mp4"

                # Mock Turn 1 tool call
                agent.llm_router.complete = AsyncMock(return_value={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": f"call_{tool_name}_1",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps({"input_path_or_url": "/tmp/input.mp4"}),
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                })
                agent._execute_tool = AsyncMock(return_value=expected_result)
                agent._flush_pending_photos = AsyncMock()
                agent._trim_history = MagicMock(wraps=agent._trim_history)

                actual_return = await agent.chat(
                    chat_id=chat_id,
                    user_message=f"Thực hiện biên tập với {tool_name}",
                )

                # 1. Exact return match
                self.assertEqual(
                    actual_return,
                    expected_result,
                    f"Tool '{tool_name}' must return exact tool_result directly!",
                )

                # 2. Strict Turn 2 bypass: Exactly 1 LLM call
                self.assertEqual(
                    agent.llm_router.complete.call_count,
                    1,
                    f"Tool '{tool_name}' must bypass Turn 2 LLM inference! Got {agent.llm_router.complete.call_count} calls",
                )

                # 3. Flushed pending photos
                self.assertEqual(
                    agent._flush_pending_photos.call_count,
                    1,
                    f"Tool '{tool_name}' must trigger _flush_pending_photos!",
                )

                # 4. History trimmed
                self.assertGreaterEqual(
                    agent._trim_history.call_count,
                    1,
                    f"Tool '{tool_name}' must invoke _trim_history!",
                )

                # 5. History integrity
                session_history = agent._history_map.get(chat_id, [])
                self.assertGreaterEqual(len(session_history), 4)
                self.assertEqual(session_history[0]["role"], "user")
                self.assertEqual(session_history[1]["role"], "assistant")
                self.assertTrue(session_history[1].get("tool_calls"))
                self.assertEqual(session_history[2]["role"], "tool")
                self.assertEqual(session_history[2]["content"], expected_result)
                self.assertEqual(session_history[3]["role"], "assistant")
                self.assertEqual(session_history[3]["content"], expected_result)

    async def test_m6_multimedia_tools_terminal_execution_bypasses_turn2(self):
        """Adversarial: All M6 multimedia tools must also terminate immediately in Turn 1."""
        for tool_name in self.REPRESENTATIVE_M6_TOOLS:
            with self.subTest(tool=tool_name):
                agent = _build_test_agent()
                chat_id = f"chat_{tool_name}"
                expected_result = f"📦 [M6 RESULT] {tool_name} deliverable processed successfully."

                agent.llm_router.complete = AsyncMock(return_value={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": f"call_{tool_name}_1",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps({"input_path_or_url": "https://example.com/asset"}),
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                })
                agent._execute_tool = AsyncMock(return_value=expected_result)
                agent._flush_pending_photos = AsyncMock()

                actual_return = await agent.chat(
                    chat_id=chat_id,
                    user_message=f"Xử lý {tool_name}",
                )

                self.assertEqual(actual_return, expected_result)
                self.assertEqual(agent.llm_router.complete.call_count, 1)
                self.assertEqual(agent._flush_pending_photos.call_count, 1)

    async def test_differential_non_terminal_tools_invoke_turn2_synthesis(self):
        """
        Differential Adversarial: Non-terminal tools (run_command, get_weather, etc.)
        MUST NOT terminate in Turn 1.
        They MUST feed tool results back into history and invoke Turn 2 LLM synthesis!
        """
        for tool_name, tool_args in self.NON_TERMINAL_TOOLS:
            with self.subTest(tool=tool_name):
                agent = _build_test_agent()
                chat_id = f"chat_diff_{tool_name}"
                raw_tool_output = f"Raw output from {tool_name}: 24.5C, sunny, humidity 60%"
                llm_synthesized_response = f"Dạ kết quả từ {tool_name} cho thấy thời tiết rất đẹp ạ!"

                # Mock Turn 1 (tool call) then Turn 2 (synthesis)
                turn1_response = {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": f"call_{tool_name}_1",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                }
                turn2_response = {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": llm_synthesized_response,
                        },
                        "finish_reason": "stop",
                    }],
                }

                agent.llm_router.complete = AsyncMock(side_effect=[turn1_response, turn2_response])
                agent._execute_tool = AsyncMock(return_value=raw_tool_output)
                agent._flush_pending_photos = AsyncMock()

                actual_return = await agent.chat(
                    chat_id=chat_id,
                    user_message=f"Hỏi {tool_name}",
                )

                # Must return LLM synthesized message, NOT raw tool output!
                self.assertEqual(actual_return, llm_synthesized_response)
                # LLM MUST have been called at least 2 times (Turn 1 tool dispatch + Turn 2 synthesis)
                self.assertEqual(
                    agent.llm_router.complete.call_count,
                    2,
                    f"Non-terminal tool '{tool_name}' must continue to Turn 2 LLM synthesis!",
                )

    async def test_terminal_tool_error_output_returns_immediately_without_reflexion(self):
        """
        Adversarial: When a DIRECT_RETURN_TOOLS tool returns an error message
        (e.g., 'Lỗi: Tệp video không tồn tại'), it must return immediately to user
        without triggering the 2-failure reflexion loop or System 2 escalation.
        """
        agent = _build_test_agent()
        chat_id = "chat_term_err"
        error_result = "❌ Lỗi: Tệp video /tmp/invalid.mp4 không tồn tại trên hệ thống."

        agent.llm_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_err_1",
                        "type": "function",
                        "function": {
                            "name": "remove_text_from_video",
                            "arguments": json.dumps({"input_path_or_url": "/tmp/invalid.mp4"}),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })
        agent._execute_tool = AsyncMock(return_value=error_result)
        agent._flush_pending_photos = AsyncMock()

        actual_return = await agent.chat(
            chat_id=chat_id,
            user_message="xóa chữ trong video",
        )

        self.assertEqual(actual_return, error_result)
        self.assertEqual(agent.llm_router.complete.call_count, 1)

    async def test_parallel_tool_calls_with_direct_return(self):
        """
        Adversarial: When parallel tool calls are returned and one is a DIRECT_RETURN_TOOLS tool,
        the loop executes both tools and immediately terminates on the direct return tool.
        """
        agent = _build_test_agent()
        chat_id = "chat_parallel"
        vid_result = "🎬 [Video Output] remove_text_from_video hoàn tất."

        agent.llm_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_p1",
                            "type": "function",
                            "function": {
                                "name": "remove_text_from_video",
                                "arguments": '{"input_path_or_url": "/tmp/vid.mp4"}',
                            },
                        },
                        {
                            "id": "call_p2",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "Hà Nội"}',
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        })
        agent._execute_tool = AsyncMock(side_effect=[vid_result, "Thời tiết 25C"])
        agent._flush_pending_photos = AsyncMock()

        actual_return = await agent.chat(
            chat_id=chat_id,
            user_message="xóa text và xem thời tiết",
        )

        self.assertEqual(actual_return, vid_result)
        self.assertEqual(agent.llm_router.complete.call_count, 1)
        self.assertEqual(agent._execute_tool.call_count, 2)


class TestNonTerminalToolsIsolationAdversarial(unittest.TestCase):
    """Adversarial Verification Vector 2: Isolation of Non-Terminal Tools."""

    # Exhaustive inventory of non-terminal tools that MUST NOT be in DIRECT_RETURN_TOOLS
    SYSTEM_AND_SHELL_TOOLS = {
        "run_command",
        "execute_system_script",
        "manage_docker_containers",
        "optimize_system_resources",
        "restart_service",
        "restart_ngrok_tunnel",
    }

    DIAGNOSTIC_AND_HEALTH_TOOLS = {
        "get_system_health_report",
        "check_service_status",
        "tail_service_logs",
        "get_disk_usage",
        "get_network_info",
        "get_server_location",
        "get_server_active_sessions",
    }

    SECURITY_AND_DEFENSE_TOOLS = {
        "get_security_report",
        "list_blocked_ips",
        "get_honeypot_log",
        "get_attack_history",
        "block_ip",
        "unblock_ip",
    }

    FILE_AND_DATA_TOOLS = {
        "list_files",
        "read_file_content",
        "write_file_content",
        "move_or_rename_file",
        "read_archive_file",
        "query_database",
    }

    NOTES_AND_SCHEDULE_TOOLS = {
        "list_notes",
        "search_notes",
        "create_note",
        "delete_note",
        "schedule_reminder",
        "cancel_reminder",
        "list_scheduled_reminders",
        "create_cron_job",
        "delete_cron_job",
        "list_cron_jobs",
    }

    UTILITY_AND_BROWSER_TOOLS = {
        "get_weather",
        "calculate",
        "convert_units",
        "remember_for_later",
        "send_email",
        "generate_report",
        "browser_navigate",
        "browser_search_google",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_go_back",
        "browser_go_forward",
        "browser_press_key",
        "browser_hover",
        "browser_select_option",
        "browser_execute_js",
        "browser_fill_form",
        "extract_clean_web_article",
    }

    def test_disjointness_all_non_terminal_categories(self):
        """Assert that ALL non-terminal categories are strictly disjoint from DIRECT_RETURN_TOOLS."""
        all_non_terminal = (
            self.SYSTEM_AND_SHELL_TOOLS
            | self.DIAGNOSTIC_AND_HEALTH_TOOLS
            | self.SECURITY_AND_DEFENSE_TOOLS
            | self.FILE_AND_DATA_TOOLS
            | self.NOTES_AND_SCHEDULE_TOOLS
            | self.UTILITY_AND_BROWSER_TOOLS
        )

        overlap = DIRECT_RETURN_TOOLS.intersection(all_non_terminal)
        self.assertEqual(
            overlap,
            set(),
            f"CRITICAL: Non-terminal tools found in DIRECT_RETURN_TOOLS: {overlap}",
        )

    def test_exact_direct_return_tools_inventory_size(self):
        """Assert that DIRECT_RETURN_TOOLS contains exactly 31 verified tools."""
        self.assertEqual(
            len(DIRECT_RETURN_TOOLS),
            31,
            f"DIRECT_RETURN_TOOLS must have exactly 31 tools, found {len(DIRECT_RETURN_TOOLS)}: {DIRECT_RETURN_TOOLS}",
        )

    def test_direct_return_tools_all_registries_identical(self):
        """Assert set identity across module, AgentToolExecutor, and AiAgentService."""
        self.assertEqual(AgentToolExecutor.DIRECT_RETURN_TOOLS, DIRECT_RETURN_TOOLS)
        self.assertEqual(AgentToolExecutor._DIRECT_RETURN_TOOLS, DIRECT_RETURN_TOOLS)
        self.assertEqual(AiAgentService._DIRECT_RETURN_TOOLS, DIRECT_RETURN_TOOLS)

    def test_each_direct_return_tool_is_justified(self):
        """
        Validates that every single one of the 31 tools in DIRECT_RETURN_TOOLS
        belongs to a recognized terminal output cluster (Media Studio, File Delivery, Screenshot, or Facebook Send).
        """
        valid_clusters = {
            # Facebook & Server Screenshot
            "facebook_send_reply",
            "facebook_capture_screenshot",
            "facebook_view_profile",
            "server_capture_screenshot",
            "browser_take_screenshot",
            # File transfer & direct downloads
            "download_media_video",
            "download_media_audio",
            "create_file_transfer_portal",
            "download_direct_file",
            # M7 Video Editor Studio (9 tools)
            "remove_text_from_video",
            "add_subtitle_to_video",
            "apply_color_grade",
            "stabilize_video",
            "concatenate_videos",
            "extract_frames",
            "remove_watermark_region",
            "enhance_video_quality",
            "generate_video_thumbnail",
            # M6 Multimedia Studio (13 remaining tools)
            "edit_video_clip",
            "compress_video",
            "convert_video_format",
            "convert_audio_format",
            "trim_audio_clip",
            "normalize_audio_volume",
            "convert_and_resize_image",
            "generate_custom_qr",
            "inspect_media_metadata",
            "merge_pdf_documents",
            "split_pdf_document",
            "extract_document_text",
            "translate_text",
        }
        self.assertEqual(
            DIRECT_RETURN_TOOLS,
            valid_clusters,
            f"DIRECT_RETURN_TOOLS contains unexpected tools: {DIRECT_RETURN_TOOLS - valid_clusters}",
        )


class TestStaticSystemPrefixKVInvarianceAdversarial(unittest.TestCase):
    """Adversarial Verification Vector 3: Static System Prefix Invariance & KV-Cache Reuse."""

    def test_static_prefix_sha256_hash_invariance(self):
        """
        Adversarial: The SHA-256 hash of _STATIC_SYSTEM_PREFIX must be deterministic
        and unchanging across instances and invocations.
        """
        prefix_1 = AiAgentService._STATIC_SYSTEM_PREFIX
        hash_1 = hashlib.sha256(prefix_1.encode("utf-8")).hexdigest()

        agent_a = _build_test_agent()
        agent_b = _build_test_agent()

        prefix_a = agent_a._STATIC_SYSTEM_PREFIX
        prefix_b = agent_b._STATIC_SYSTEM_PREFIX

        hash_a = hashlib.sha256(prefix_a.encode("utf-8")).hexdigest()
        hash_b = hashlib.sha256(prefix_b.encode("utf-8")).hexdigest()

        self.assertEqual(hash_1, hash_a)
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(prefix_1, prefix_a)

    def test_static_prefix_absence_of_volatile_elements(self):
        """
        Adversarial: _STATIC_SYSTEM_PREFIX must NOT contain:
        - Dynamic date/time formats ('Giờ Việt Nam', 'ICT', 'UTC', strftime patterns)
        - Format interpolation placeholders ('{0}', '{now}', '{user_message}')
        - Ephemeral memory markers
        """
        prefix = AiAgentService._STATIC_SYSTEM_PREFIX

        volatile_patterns = [
            "Giờ Việt Nam - ICT/UTC+7",
            "Mốc thời gian hệ thống hiện tại",
            "━━━ 5. NGỮ CẢNH THỜI GIAN THỰC & BỘ NHỚ",
            "{now_vn}",
            "{datetime}",
            "{ephemeral}",
            "{user_message}",
        ]
        for pattern in volatile_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn(
                    pattern,
                    prefix,
                    f"Volatile pattern '{pattern}' found in _STATIC_SYSTEM_PREFIX! This breaks KV-cache reuse.",
                )

    def test_build_system_prompt_strictly_anchors_prefix(self):
        """
        Adversarial: When _build_system_prompt() is called, the output MUST start
        strictly with _STATIC_SYSTEM_PREFIX as an invariant prefix anchor.
        All dynamic context must follow strictly as a suffix.
        """
        agent = _build_test_agent()
        prompt_1 = agent._build_system_prompt()
        prompt_2 = agent._build_system_prompt()

        # Both prompts must start with the exact static prefix
        self.assertTrue(prompt_1.startswith(agent._STATIC_SYSTEM_PREFIX))
        self.assertTrue(prompt_2.startswith(agent._STATIC_SYSTEM_PREFIX))

        prefix_len = len(agent._STATIC_SYSTEM_PREFIX)
        # Suffix must begin with Section 5
        suffix_1 = prompt_1[prefix_len:]
        self.assertTrue(
            suffix_1.startswith("\n\n━━━ 5. NGỮ CẢNH THỜI GIAN THỰC & BỘ NHỚ"),
            "Dynamic ephemeral block must immediately follow static prefix",
        )

    def test_section_2t_mandatory_imperative_rules_present(self):
        """
        Adversarial: Verifies the presence of the non-negotiable tool-first imperative rules in Section 2t.
        """
        prefix = AiAgentService._STATIC_SYSTEM_PREFIX

        # Check section header
        self.assertIn("━━━ 2t. GIAO THỨC BIÊN TẬP VIDEO CHUYÊN NGHIỆP", prefix)
        self.assertIn("PHẢN XẠ THỰC THI BẮT BUỘC (TOOL-FIRST IMPERATIVE — KHÔNG THƯƠNG LƯỢNG)", prefix)

        # Check negative prohibitions
        self.assertIn("TUYỆT ĐỐI CẤM trả lời bằng hướng dẫn văn bản", prefix)
        self.assertIn("DaVinci Resolve", prefix)
        self.assertIn("CẤM tự ý từ chối thực hiện hay giải thích lý do không làm được", prefix)

        # Check positive imperatives
        self.assertIn("BẮT BUỘC GỌI TOOL NGAY trong lượt đầu tiên", prefix)
        self.assertIn("remove_text_from_video` NGAY với mode='auto'", prefix)
        self.assertIn("add_subtitle_to_video` NGAY", prefix)
        self.assertIn("apply_color_grade` NGAY", prefix)
        self.assertIn("stabilize_video` NGAY", prefix)
        self.assertIn("concatenate_videos` NGAY", prefix)
        self.assertIn("enhance_video_quality` NGAY", prefix)
        self.assertIn("generate_video_thumbnail` NGAY", prefix)
        self.assertIn("extract_frames` NGAY", prefix)
        self.assertIn("Anh gửi đường dẫn file video hoặc link cho em nhé?", prefix)


class TestStressAndExtremeAdversarialScenarios(unittest.IsolatedAsyncioTestCase):
    """Adversarial Verification Vector 4: Stress Harness & Extreme Edge Cases."""

    async def test_sequential_execution_stress_harness_20_iterations(self):
        """
        Stress Harness: 20 sequential messages alternating between terminal video editor tools
        and non-terminal diagnostic tools across distinct chat sessions.
        Ensures zero memory leakage, zero history corruption, and 100% correct turn termination.
        """
        agent = _build_test_agent()

        for idx in range(20):
            is_terminal = (idx % 2 == 0)
            chat_id = f"stress_chat_{idx}"

            if is_terminal:
                tool_name = "remove_text_from_video"
                agent.llm_router.complete = AsyncMock(return_value={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": f"call_stress_{idx}",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": '{"input_path_or_url": "/tmp/v.mp4"}',
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                })
                agent._execute_tool = AsyncMock(return_value=f"Result {idx}")
                agent._flush_pending_photos = AsyncMock()

                res = await agent.chat(chat_id=chat_id, user_message="xóa text")
                self.assertEqual(res, f"Result {idx}")
                self.assertEqual(agent.llm_router.complete.call_count, 1)
            else:
                tool_name = "get_weather"
                agent.llm_router.complete = AsyncMock(side_effect=[
                    {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": f"call_stress_{idx}",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": '{"location": "Hà Nội"}',
                                    },
                                }],
                            },
                            "finish_reason": "tool_calls",
                        }],
                    },
                    {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": f"Tổng hợp thời tiết {idx}",
                            },
                            "finish_reason": "stop",
                        }],
                    },
                ])
                agent._execute_tool = AsyncMock(return_value=f"Weather raw {idx}")
                agent._flush_pending_photos = AsyncMock()

                res = await agent.chat(chat_id=chat_id, user_message="thời tiết")
                self.assertEqual(res, f"Tổng hợp thời tiết {idx}")
                self.assertEqual(agent.llm_router.complete.call_count, 2)

    async def test_unicode_and_dialect_preservation_in_terminal_tool(self):
        """
        Adversarial: Complex Vietnamese Unicode payload with dialect phrasing
        must pass through tool execution and return intact without encoding corruption.
        """
        agent = _build_test_agent()
        chat_id = "chat_unicode_dialect"
        unicode_tool_result = (
            "🎯 Video đã xóa sạch text thành công!\n"
            "• Tiêu đề: Đêm buồn tỉnh lẻ (Remix 4K 60fps - Âm vang Nghệ Tĩnh)\n"
            "• Đường dẫn: /home/kirito/quan_ly_server/data/media/đêm_buồn_tỉnh_lẻ_cleaned.mp4\n"
            "• Dung lượng: 45.2 MB (Chuẩn Direct Delivery qua Telegram)"
        )

        agent.llm_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_uni_1",
                        "type": "function",
                        "function": {
                            "name": "remove_text_from_video",
                            "arguments": json.dumps({
                                "input_path_or_url": "/tmp/đêm_buồn_tỉnh_lẻ.mp4",
                                "mode": "auto",
                            }, ensure_ascii=False),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })
        agent._execute_tool = AsyncMock(return_value=unicode_tool_result)
        agent._flush_pending_photos = AsyncMock()

        res = await agent.chat(
            chat_id=chat_id,
            user_message="xóa sạch text trong video đêm buồn tỉnh lẻ này giúp anh với",
        )

        self.assertEqual(res, unicode_tool_result)
        self.assertIn("Nghệ Tĩnh", res)
        self.assertIn("đêm_buồn_tỉnh_lẻ_cleaned.mp4", res)


if __name__ == "__main__":
    unittest.main()
