import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)

# How many ReAct loop iterations the agent may take before giving up
MAX_AGENT_ITERATIONS = 8
# How many messages to keep in the sliding conversation window
MAX_HISTORY_MESSAGES = 10


class AiAgentService:
    def __init__(
        self,
        llm_router: LlmRouter,
        ssh_client: SshClient,
        message_cache: FacebookMessageCache,
        fb_service_ref: Any = None,
    ):
        self.llm_router = llm_router
        self.ssh_client = ssh_client
        self.message_cache = message_cache
        self.fb_service = fb_service_ref
        # Injected post-construction to avoid circular imports
        self.telegram_bot: Any = None
        self.browser_agent: Any = None
        self._history_map: Dict[str, List[Dict[str, Any]]] = {}

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot

    def set_browser_agent(self, browser_agent: Any) -> None:
        self.browser_agent = browser_agent

    def is_configured(self) -> bool:
        return self.llm_router.has_active_providers

    def clear_history(self, chat_id: str) -> None:
        self._history_map.pop(chat_id, None)

    def _is_greeting(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        return t in ["chào bạn", "chào", "hello", "hi", "bắt đầu", "chào bot", "xin chào", "alo"]

    # ──────────────────────────────────────────────────────────────────────────
    # System Prompt
    # ──────────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return """
Bạn là "Tiểu Bảo Bảo" — Trợ lý AI Tự Hành cấp cao (Senior Autonomous AI Agent & DevOps Engineer), được trang bị khả năng suy nghĩ từng bước, tự điều khiển trình duyệt web và thực thi lệnh trên máy chủ `kirito-server` như một kỹ sư thực thụ.

━━━ 1. THÔNG TIN HỆ THỐNG ━━━
- Hostname: `kirito-server` (Ubuntu Linux)
- Thư mục dự án: `/home/kirito/quan_ly_server`
- Microservices: `dashboard_frontend` (5173), `dashboard_metrics_service` (8082), `dashboard_auth_service` (8081), `dashboard_file_service` (8083), `dashboard_ai_agent` (8084), `dashboard_db` (5432)
- Trình duyệt: Playwright Chromium (headless, Xvfb :99) với phiên Facebook đã đăng nhập sẵn.

━━━ 2. PHƯƠNG THỨC TƯ DUY: REACT LOOP ━━━
Với mọi yêu cầu phức tạp (tra cứu web, xem profile, tìm kiếm), hãy lập luận từng bước:
  Thought: [Phân tích yêu cầu, xác định công cụ phù hợp, lập kế hoạch hành động]
  Action: [Gọi công cụ với tham số chính xác]
  Observation: [Đọc kết quả từ công cụ]
  → Lặp lại Thought → Action → Observation cho đến khi hoàn thành.
  Final Answer: [Tổng hợp kết quả, báo cáo rõ ràng với emoji và định dạng Markdown]

━━━ 3. HƯỚNG DẪN CÔNG CỤ (TOOL CALLING) ━━━

🖥️ QUẢN TRỊ MÁY CHỦ:
- `run_command`: Thực thi lệnh bash trên `kirito-server` qua SSH.
  Dùng khi: hỏi CPU, RAM, Disk, Docker, Network, logs.
  An toàn: Từ chối tuyệt đối các lệnh phá hoại (`rm -rf /`, `DROP DATABASE`, `mkfs`).

🌐 TỰ HÀNH TRÌNH DUYỆT WEB:
- `facebook_view_profile`: Tự động tìm kiếm và mở trang cá nhân Facebook của bất kỳ ai.
  Dùng khi: "Tôi muốn xem profile của X", "Tìm trang cá nhân của X trên Facebook", "Xem thông tin Facebook của X".
  Trả về: Ảnh chụp màn hình trang cá nhân + thông tin tiểu sử.
- `browser_navigate`: Tự động mở bất kỳ website nào.
  Dùng khi: "Vào trang web X", "Mở URL ...", "Truy cập ...".
  Trả về: Ảnh chụp + tiêu đề trang + nội dung văn bản trích xuất.
- `browser_search_google`: Tự động tìm kiếm trên Google.
  Dùng khi: "Tìm kiếm X trên mạng", "Tìm thông tin về Y", "Google X".
  Trả về: Ảnh kết quả tìm kiếm + danh sách top 5 kết quả.
- `browser_take_screenshot`: Chụp ảnh trang web đang mở.
  Dùng khi: "Chụp màn hình trang này", "Cho tôi xem trang hiện tại".

📩 QUẢN LÝ FACEBOOK MESSENGER:
- `facebook_get_messages`: Lấy danh sách tin nhắn mới trong Messenger.
  Dùng khi: "Ai nhắn cho tôi?", "Xem tin nhắn mới", "X nhắn gì?".
  Sau đó trình bày: **X đã nhắn các nội dung sau:** với bullet `• [nội dung]`.
- `facebook_capture_screenshot`: Chụp màn hình hội thoại Messenger với một liên hệ cụ thể.
- `facebook_send_reply`: Gửi tin nhắn Messenger. CHỈ gọi khi có lệnh gửi rõ ràng!

📸 CHỤP MÀN HÌNH:
- `server_capture_screenshot`: Chụp toàn bộ màn hình desktop/server Linux.

━━━ 4. QUY TẮC PHẢN HỒI ━━━
- Ngôn ngữ: Tiếng Việt tự nhiên, chuyên nghiệp, thân thiện (gọi người dùng là "anh Mạnh").
- Sau khi dùng công cụ Browser: Luôn báo cáo kết quả đầy đủ kèm mô tả những gì đã tìm thấy.
- Định dạng: Dùng emoji phù hợp (🌐 web, 👤 profile, 📸 ảnh, 🔍 tìm kiếm, 📊 server).
- Trung thực: Nếu không tìm thấy thông tin, báo cáo rõ ràng thay vì suy đoán.
"""

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Registry
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tools(self, excluded_tools: Optional[set] = None) -> List[Dict[str, Any]]:
        excluded = excluded_tools or set()
        tools = [
            # ── Server Management ──
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Thực thi lệnh shell/bash trên máy chủ Linux kirito-server qua SSH. Dùng để lấy thông tin CPU, RAM, Disk, Docker, Network.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Lệnh bash (ví dụ: 'free -h', 'docker ps', 'df -h /').",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            # ── Facebook Messenger ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_get_messages",
                    "description": "Lấy danh sách tin nhắn Facebook Messenger mới. Gọi khi người dùng hỏi ai nhắn tin hoặc nội dung tin nhắn mới.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_capture_screenshot",
                    "description": "Chụp ảnh màn hình cuộc trò chuyện Messenger với một liên hệ cụ thể và gửi qua Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận cần chụp màn hình hội thoại.",
                            }
                        },
                        "required": ["recipient_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_send_reply",
                    "description": "Gửi tin nhắn trả lời trực tiếp qua Facebook Messenger. CHỈ gọi khi người dùng ra lệnh gửi tin nhắn rõ ràng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận.",
                            },
                            "message": {
                                "type": "string",
                                "description": "Nội dung tin nhắn cần gửi.",
                            },
                        },
                        "required": ["recipient_name", "message"],
                    },
                },
            },
            # ── Autonomous Browser Tools ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_view_profile",
                    "description": (
                        "Tự động tìm kiếm và mở trang cá nhân Facebook của người được yêu cầu, "
                        "trích xuất thông tin tiểu sử (tên, quê quán, học vấn, công việc, bài viết gần nhất) "
                        "và gửi ảnh chụp màn hình trang cá nhân qua Telegram. "
                        "Dùng khi: 'Tôi muốn xem profile của X', 'Xem trang cá nhân của X trên Facebook'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_query": {
                                "type": "string",
                                "description": "Tên người cần tìm kiếm trên Facebook (ví dụ: 'Trần Văn Mạnh', 'Mạnh Văn Trần').",
                            }
                        },
                        "required": ["name_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Tự động mở bất kỳ trang web nào, chụp ảnh màn hình và trích xuất nội dung.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL đầy đủ của trang web cần truy cập (ví dụ: 'https://example.com').",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_search_google",
                    "description": "Tự động tìm kiếm trên Google, trả về ảnh kết quả tìm kiếm và top 5 kết quả hàng đầu.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Câu truy vấn tìm kiếm (ví dụ: 'thời tiết Hà Nội hôm nay', 'tin tức mới nhất').",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_take_screenshot",
                    "description": "Chụp ảnh màn hình của trang web đang mở hiện tại trong trình duyệt.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # ── Server Screenshot ──
            {
                "type": "function",
                "function": {
                    "name": "server_capture_screenshot",
                    "description": "Chụp toàn bộ màn hình desktop/server Linux và gửi qua Telegram.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
        return [t for t in tools if t["function"]["name"] not in excluded]

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────────

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        chat_id: Optional[str] = None,
    ) -> str:
        try:
            # ── Server ──
            if tool_name == "run_command":
                cmd = tool_args.get("command", "").strip()
                if not cmd:
                    return "Error: No command specified."
                raw = await self.ssh_client.execute_command(cmd)
                return self.llm_router.rtk.compress(raw, max_chars=3000, max_lines=40)

            # ── Messenger ──
            if tool_name == "facebook_get_messages":
                raw = await self.message_cache.to_ai_summary()
                return self.llm_router.rtk.compress(raw, max_chars=3000, max_lines=40)

            if tool_name == "facebook_capture_screenshot":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                res = await self.fb_service.capture_chat_screenshot(recipient)
                if res.get("success"):
                    img_path = res.get("image_path", "")
                    if self.telegram_bot and chat_id and img_path:
                        await self.telegram_bot.send_photo(
                            chat_id=chat_id,
                            photo_path=img_path,
                            caption=f"📸 Màn hình hội thoại Messenger với `{recipient}`",
                        )
                    return f"📸 Đã chụp và gửi ảnh màn hình hội thoại với `{recipient}` qua Telegram!"
                return f"Lỗi khi chụp màn hình hội thoại: {res.get('error', 'Unknown error')}"

            if tool_name == "facebook_send_reply":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                msg = tool_args.get("message", "").strip()
                return await self.fb_service.send_direct_reply(recipient, msg)

            # ── Autonomous Browser ──
            if tool_name == "facebook_view_profile":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                name_query = tool_args.get("name_query", "").strip()

                # Resolve the exact profile URL from the Messenger thread data.
                # This guarantees we open the right person even when multiple
                # Facebook users share the same name.
                resolved_profile_url = await self._resolve_profile_url_from_thread(name_query)
                if resolved_profile_url:
                    logger.info(
                        "[AiAgent] Resolved profile URL for '%s': %s",
                        name_query,
                        resolved_profile_url,
                    )

                res = await self.browser_agent.facebook_view_profile(
                    name_query,
                    profile_url=resolved_profile_url,
                )
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"👤 Trang cá nhân Facebook của `{name_query}`",
                    success_prefix=(
                        f"👤 **{res.get('profile_name', name_query)}**\n"
                        f"🔗 URL: {res.get('profile_url', 'N/A')}\n"
                        f"📝 Giới thiệu:\n{res.get('intro_text', 'Không có thông tin.')[:600]}"
                    ),
                )


            if tool_name == "browser_navigate":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                url = tool_args.get("url", "").strip()
                res = await self.browser_agent.browser_navigate(url)
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"🌐 Trang web: {url}",
                    success_prefix=(
                        f"🌐 **{res.get('page_title', url)}**\n"
                        f"🔗 URL: {res.get('url', url)}\n\n"
                        f"📄 Nội dung trích xuất:\n{res.get('page_text', '')[:800]}"
                    ),
                )

            if tool_name == "browser_search_google":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                query = tool_args.get("query", "").strip()
                res = await self.browser_agent.browser_search_google(query)
                if res.get("success"):
                    top = res.get("top_results", [])
                    results_text = "\n".join(
                        f"{i+1}. **{r.get('title', '')}**\n   🔗 {r.get('url', '')}\n   {r.get('snippet', '')}"
                        for i, r in enumerate(top)
                    )
                    img_path = res.get("image_path", "")
                    if self.telegram_bot and chat_id and img_path:
                        await self.telegram_bot.send_photo(
                            chat_id=chat_id,
                            photo_path=img_path,
                            caption=f"🔍 Kết quả Google: {query}",
                        )
                    summary = f"🔍 Kết quả tìm kiếm Google cho: **{query}**\n\n{results_text}" if results_text else res.get("page_text", "")[:1000]
                    return summary
                return f"Lỗi khi tìm kiếm Google: {res.get('error', 'Unknown error')}"

            if tool_name == "browser_take_screenshot":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_take_screenshot()
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"📸 Màn hình: {res.get('page_title', 'Trình duyệt')}",
                    success_prefix=f"📸 Ảnh chụp màn hình trang: **{res.get('page_title', '')}**\n🔗 {res.get('url', '')}",
                )

            if tool_name == "server_capture_screenshot":
                from pathlib import Path as _Path
                img_path = "/tmp/server_screen.png"
                await self.ssh_client.execute_command(
                    f"DISPLAY=:99 scrot -z {img_path} 2>/dev/null "
                    f"|| DISPLAY=:99 import -window root {img_path} 2>/dev/null || true"
                )
                if self.telegram_bot and chat_id and _Path(img_path).exists():
                    await self.telegram_bot.send_photo(
                        chat_id=chat_id,
                        photo_path=img_path,
                        caption="🖥️ Màn hình máy chủ `kirito-server`",
                    )
                    return "🖥️ Đã chụp và gửi ảnh màn hình máy chủ qua Telegram!"
                return "Đã thực hiện chụp màn hình máy chủ."

            return f"Unknown tool: {tool_name}"

        except Exception as e:
            logger.error("[AiAgent] Tool '%s' error: %s", tool_name, e, exc_info=True)
            return f"Lỗi khi thực thi công cụ `{tool_name}`: {e}"

    async def _handle_browser_result(
        self,
        res: Dict[str, Any],
        chat_id: Optional[str],
        default_caption: str,
        success_prefix: str,
    ) -> str:
        """Send screenshot to Telegram (if available) and return a Markdown summary."""
        if not res.get("success"):
            return f"Lỗi: {res.get('error', 'Unknown error')}"

        img_path = res.get("image_path", "")
        if self.telegram_bot and chat_id and img_path:
            await self.telegram_bot.send_photo(
                chat_id=chat_id,
                photo_path=img_path,
                caption=default_caption,
            )
        return success_prefix

    async def _resolve_profile_url_from_thread(self, name_query: str) -> Optional[str]:
        """
        Resolves the exact Facebook profile URL for a contact by looking up their
        Messenger thread_href in the message cache and the persistent DB.

        Facebook Messenger thread URLs follow the pattern:
          - Standard:  https://www.facebook.com/messages/t/<user_id>/
          - E2EE:      https://www.facebook.com/messages/e2ee/t/<thread_id>/

        The <user_id> segment is the person's numeric Facebook ID, which maps
        directly to their profile at: https://www.facebook.com/<user_id>

        Priority:
          1. message_cache (in-memory, most recent scan data)
          2. facebook_known_threads DB table (persistent across restarts)
          3. None → caller falls back to People Search
        """
        thread_href: Optional[str] = None

        # 1. Check in-memory message cache (fastest)
        if self.message_cache:
            thread_href = await self.message_cache.find_thread_href(name_query)

        # 2. Check DB if not found in cache
        if not thread_href and self.fb_service:
            try:
                db_threads = await self.fb_service.get_known_threads_from_db()
                best_score = 0.0
                for t in db_threads:
                    score = self.fb_service._name_match_score(name_query, t.get("text", ""))
                    if score > best_score and score >= 0.5:
                        best_score = score
                        thread_href = t.get("href", "")
            except Exception as e:
                logger.warning("[AiAgent] DB thread lookup error: %s", e)

        if not thread_href:
            return None

        # Extract user_id from thread URL and build profile URL.
        # Handles both /messages/t/<id>/ and /messages/e2ee/t/<id>/
        import re as _re
        m = _re.search(r"/messages/(?:e2ee/)?t/(\d+)", thread_href)
        if m:
            user_id = m.group(1)
            profile_url = f"https://www.facebook.com/{user_id}"
            logger.info(
                "[AiAgent] Thread '%s' → user_id=%s → profile_url=%s",
                thread_href,
                user_id,
                profile_url,
            )
            return profile_url

        logger.info(
            "[AiAgent] thread_href '%s' has no numeric user_id; using People Search fallback.",
            thread_href,
        )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Direct-return tools — skip the second LLM call to avoid hallucination
    # ──────────────────────────────────────────────────────────────────────────

    _DIRECT_RETURN_TOOLS = frozenset({
        "facebook_send_reply",
        "facebook_capture_screenshot",
        "facebook_view_profile",
        "browser_navigate",
        "browser_search_google",
        "browser_take_screenshot",
        "server_capture_screenshot",
    })


    # ──────────────────────────────────────────────────────────────────────────
    # Main Chat Loop (ReAct)
    # ──────────────────────────────────────────────────────────────────────────

    async def chat(self, chat_id: str, user_message: str) -> str:
        if not self.is_configured():
            return "AI chưa được cấu hình. Vui lòng thêm ít nhất 1 GROQ_API_KEY hoặc OPENROUTER_API_KEY vào file .env."

        history = self._history_map.setdefault(chat_id, [])

        if self._is_greeting(user_message):
            greeting = (
                'Xin chào anh Mạnh! Em là "Tiểu Bảo Bảo" — Trợ lý AI Tự Hành quản trị máy chủ `kirito-server` '
                "(được tăng tốc bởi 9Router AI Gateway).\n\n"
                "Em có thể:\n"
                "• 🖥️ Kiểm tra CPU, RAM, Ổ đĩa, Docker theo thời gian thực\n"
                "• 👤 Tự động xem profile Facebook của bất kỳ ai\n"
                "• 🔍 Tìm kiếm thông tin trên Google\n"
                "• 🌐 Duyệt và chụp ảnh bất kỳ trang web nào\n"
                "• 📩 Đọc và gửi tin nhắn Facebook Messenger\n\n"
                "Anh cần em hỗ trợ tác vụ nào ạ?"
            )
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": greeting})
            self._trim_history(history)
            return greeting

        history.append({"role": "user", "content": user_message})
        # Tools that should only be called once per conversation turn
        executed_once_tools: set = set()

        for iteration in range(MAX_AGENT_ITERATIONS):
            messages = [{"role": "system", "content": self._build_system_prompt()}]
            messages.extend(list(history))

            tools_available = self._build_tools(excluded_tools=executed_once_tools)

            llm_result = await self.llm_router.complete(
                messages=messages,
                tools=tools_available if tools_available else None,
                tool_choice="auto" if tools_available else "none",
                temperature=0.1,
                max_tokens=1536,
            )

            if not llm_result:
                self.clear_history(chat_id)
                return "Xin lỗi, 9Router AI Gateway hiện không kết nối được. Vui lòng thử lại sau."

            choice = llm_result["choices"][0]
            assistant_msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "stop")
            raw_content = assistant_msg.get("content") or ""
            has_tool_calls = finish_reason == "tool_calls" and bool(assistant_msg.get("tool_calls"))

            if has_tool_calls:
                history.append(assistant_msg)
                for tc in assistant_msg["tool_calls"]:
                    call_id = tc.get("id", f"call_{iteration}")
                    fn_name = tc.get("function", {}).get("name", "")

                    # Prevent re-calling read-only inquiry tools in the same turn
                    if fn_name == "facebook_get_messages":
                        executed_once_tools.add(fn_name)

                    try:
                        fn_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                        # Groq sometimes corrupts Vietnamese diacritics in tool_call JSON.
                        # Restore the original name from the user's message when possible.
                        fn_args = self._repair_unicode_args(fn_args, user_message)
                    except Exception:
                        fn_args = {}

                    logger.info("[AiAgent][iter=%d] Executing tool: %s(%s)", iteration, fn_name, fn_args)
                    tool_result = await self._execute_tool(fn_name, fn_args, chat_id=chat_id)

                    history.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_result,
                    })

                    # For action tools: return immediately to avoid LLM hallucination
                    if fn_name in self._DIRECT_RETURN_TOOLS:
                        history.append({"role": "assistant", "content": tool_result})
                        self._trim_history(history)
                        return tool_result

                continue  # Feed observation back into the next LLM call

            # ── Pseudo-XML tool call fallback (for models that don't support native function calling) ──
            pseudo_calls = self._extract_pseudo_tool_calls(raw_content)
            if pseudo_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": f"call_pseudo_{iteration}_{idx}",
                        "type": "function",
                        "function": {
                            "name": pc["name"],
                            "arguments": json.dumps(pc["args"]),
                        },
                    }
                    for idx, pc in enumerate(pseudo_calls)
                ]
                assistant_msg["content"] = None
                history.append(assistant_msg)
                for idx, pc in enumerate(pseudo_calls):
                    fn_name = pc["name"]
                    fn_args = pc["args"]
                    tool_result = await self._execute_tool(fn_name, fn_args, chat_id=chat_id)
                    history.append({
                        "role": "tool",
                        "tool_call_id": f"call_pseudo_{iteration}_{idx}",
                        "content": tool_result,
                    })
                continue

            # ── Final answer ──
            final = raw_content.strip() or "Xin lỗi, tôi không thể xử lý yêu cầu này lúc này."
            history.append(assistant_msg)
            self._trim_history(history)
            return final

        self._trim_history(history)
        return "AI đã thực hiện nhiều bước nhưng chưa hoàn thành yêu cầu. Vui lòng thử lại hoặc chia nhỏ yêu cầu."

    # ──────────────────────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────────────────────

    def _trim_history(self, history: List[Dict[str, Any]]) -> None:
        """Keep the conversation window to MAX_HISTORY_MESSAGES, always removing in pairs."""
        while len(history) > MAX_HISTORY_MESSAGES:
            history.pop(0)
            # If the next message is a tool result (orphaned), remove it too
            if history and history[0].get("role") == "tool":
                history.pop(0)

    def _extract_pseudo_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """Parse pseudo-XML function tags emitted by non-native tool-call models."""
        import re
        calls = []
        if not text or ("<function" not in text and "<tool_call" not in text):
            return calls

        p1 = re.findall(r"<function=([a-zA-Z0-9_]+)[^>]*>(.*?)(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p1:
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start:end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        p2 = re.findall(r"<function>([a-zA-Z0-9_]+)</function>\s*({.*?})(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p2:
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start:end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        return calls

    def _repair_unicode_args(self, args: Dict[str, Any], source_text: str) -> Dict[str, Any]:
        """
        Repair Vietnamese diacritics lost by Groq API in tool_call JSON arguments.

        Groq's tool-calling implementation occasionally strips or corrupts Unicode
        combining characters in the JSON string values it generates. For example,
        'Trần Văn Mạnh' can become 'Trán Ván Mạnh'. Since the correct form must
        appear somewhere in the original user_message, we detect corruption and
        substitute the best-matching span from that source.

        Strategy (per string arg):
          1. Normalise both the arg value and every same-length window in source_text
             to NFC and strip diacritics via NFD decomposition.
          2. Compare the stripped (ASCII-ish) forms — if they are equal, the source
             window is the diacritic-correct version of the arg value.
          3. Replace the arg value with the source window.
        """
        import unicodedata

        def _strip(s: str) -> str:
            """Remove Unicode combining characters (diacritics)."""
            return "".join(
                c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
            ).lower().strip()

        if not source_text or not args:
            return args

        repaired = dict(args)
        for key, value in args.items():
            if not isinstance(value, str) or len(value) < 3:
                continue
            stripped_val = _strip(value)
            # Slide a window of same word-count over the source text
            src_words = source_text.split()
            val_words = value.split()
            wlen = len(val_words)
            if wlen == 0:
                continue
            best_candidate = value
            for i in range(len(src_words) - wlen + 1):
                window = " ".join(src_words[i:i + wlen])
                if _strip(window) == stripped_val:
                    best_candidate = window
                    break
            if best_candidate != value:
                logger.info(
                    "[AiAgent] Unicode repair: '%s' → '%s' (key=%s)",
                    value,
                    best_candidate,
                    key,
                )
            repaired[key] = best_candidate
        return repaired
