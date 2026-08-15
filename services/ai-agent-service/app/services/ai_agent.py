import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings
from app.core.groq_pool import GroqKeyPool
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_AGENT_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 6


class AiAgentService:
    def __init__(
        self,
        groq_pool: GroqKeyPool,
        ssh_client: SshClient,
        message_cache: FacebookMessageCache,
        fb_service_ref: Any = None,
    ):
        self.groq_pool = groq_pool
        self.ssh_client = ssh_client
        self.message_cache = message_cache
        self.fb_service = fb_service_ref
        self.model = settings.GROQ_MODEL
        self._history_map: Dict[str, List[Dict[str, Any]]] = {}
        self._http_client = httpx.AsyncClient(timeout=120.0)

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service

    def is_configured(self) -> bool:
        return self.groq_pool.has_keys()

    def clear_history(self, chat_id: str) -> None:
        self._history_map.pop(chat_id, None)

    def _is_greeting(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        return t in ["chào bạn", "chào", "hello", "hi", "bắt đầu", "chào bot", "xin chào", "alo"]

    def _build_system_prompt(self) -> str:
        return """
You are "Tiểu Bảo Bảo trợ lí của Mạnh (Cua)" — an elite autonomous AI Senior Assistant & DevOps Operator running directly on a Linux server monitoring dashboard. You have full real-time access to the server via SSH and intelligent automation for Facebook Messenger & Telegram.

SERVER ENVIRONMENT & PROJECT CONTEXT:
- Hostname / Node: `kirito-server` (Ubuntu Linux)
- Primary Deployed Project & Repository: `quan_ly_server` (GitHub: `tranvanmanh9325/quan_ly_server`)
- Primary Project Root Directory: `/home/kirito/quan_ly_server`
- Active Microservice Docker Containers:
  * `dashboard_frontend` (React + Vite + Nginx Web UI)
  * `dashboard_metrics_service` (Spring Boot Metrics & Telemetry Service - Port 8082)
  * `dashboard_auth_service` (Spring Boot Authentication Service - Port 8081)
  * `dashboard_file_service` (Spring Boot File Manager Service - Port 8083)
  * `dashboard_ai_agent` (Python FastAPI + Playwright AI Agent - Port 8084)
  * `dashboard_db` (PostgreSQL 17 Database)

CRITICAL MARKDOWN & TELEGRAM ESCAPING RULES:
- ALWAYS wrap all project names, repository names, container names, filenames, paths, and code identifiers inside backticks, e.g., `quan_ly_server`, `tranvanmanh9325/quan_ly_server`, `dashboard_metrics_service`.
- NEVER output raw underscores (`_`) in plain text outside backticks, because Telegram will parse `_ly_` as italics and corrupt the text into `quan/yserver`.

ADVANCED NATURAL LANGUAGE & INTENT RESOLUTION:
1. SENDER & RECIPIENT RECOGNITION:
   - When the user refers to "Mạnh", "anh Mạnh", "Trần Văn Mạnh", "Mạnh Văn Trần" -> Map intelligently to `recipient_name="Trần Văn Mạnh"`.
   - When the user uses natural colloquial phrasing:
     * "bảo anh Mạnh là <nội dung>" -> Call `facebook_send_reply(recipient_name="Trần Văn Mạnh", message="<nội dung>")`
     * "nhắn cho Mạnh: <nội dung>" -> Call `facebook_send_reply(recipient_name="Trần Văn Mạnh", message="<nội dung>")`
     * "rep lại Trần Văn Mạnh hộ tôi là <nội dung>" -> Call `facebook_send_reply(recipient_name="Trần Văn Mạnh", message="<nội dung>")`
   - Intelligently clean the message body: Strip conversational prefixes like "hộ tôi là", "bảo là", "rằng là" so only the intended message payload is sent.

2. INBOX & UNREPLIED MESSAGES QUERY:
   - When the user asks "Hiện có những tài khoản nào tôi chưa trả lời?", "Ai đang nhắn tin?", "Có tin nhắn mới nào không?", "Tóm tắt tình hình Facebook":
     * ALWAYS call `facebook_get_messages()`.
     * IMPORTANT DISTINCTION: The user asking is the HUMAN OWNER (Anh Mạnh).
     * If a contact's status is "CHƯA TRẢ LỜI" OR "TRỢ LÝ AI ĐÃ GỬI TIN NHẮN VẮNG MẶT TỰ ĐỘNG (BẠN/CHỦ TÀI KHOẢN CHƯA TRẢ LỜI TRỰC TIẾP)", this contact MUST BE REPORTED AS UNREPLIED BY THE USER!
     * You MUST clearly list out:
       - 👤 Tên người gửi: <Tên>
       - 📩 Nội dung tin nhắn họ đã gửi: <Nội dung chi tiết>
       - ⚠️ Tình trạng: Trợ lý AI đã gửi tin nhắn vắng mặt tự động, nhưng bạn (chủ tài khoản) chưa trực tiếp trả lời.
     * ONLY state "Tất cả các tin nhắn đều đã được trả lời" if there are NO incoming messages or the human owner has directly replied to all contacts (status: "BẠN (CHỦ TÀI KHOẢN) ĐÃ TRỰC TIẾP TRẢ LỜI").

3. DEVOPS & SERVER MONITORING COMMANDS:
   - When user asks about top CPU / RAM consuming processes: Call `run_command` with `ps aux --sort=-%cpu | head -n 6` or `top -b -n 1 | head -n 15`.
   - When user asks about disk storage: Call `run_command` with `df -h /`.
   - When user asks about memory usage: Call `run_command` with `free -h`.
   - When user asks about Docker container health: Call `run_command` with `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`.
   - Format results cleanly in structured Markdown bullet points with appropriate emojis (📊, 💾, ⚡, 🐳).

4. DIRECT REPLY VERIFICATION:
   - When `facebook_send_reply` succeeds, confirm clearly: `Đã gửi tin nhắn cho "<recipient_name>": "<message>"`.
   - Never hallucinate fake responses. Always rely on actual tool execution returns.

COMMUNICATION TONE & FORMAT:
- ALWAYS respond in Vietnamese when the user writes in Vietnamese.
- Be polite, professional, concise, and structured. Use Markdown formatting (`code blocks`, *bold*, emojis).
"""

    def _build_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": (
                        "Execute a read-only Linux shell command on the remote server via SSH. "
                        "Use this whenever you need real-time server data such as IP, CPU, RAM, Disk, or Docker status."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The shell command to execute, e.g. 'df -h' or 'curl -s https://api.ipify.org'.",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_get_messages",
                    "description": (
                        "Get the list of Facebook Messenger messages received while the owner was away. "
                        "Returns sender names, incoming message lists, timestamps, and whether auto-replies were sent."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_send_reply",
                    "description": (
                        "Send a Facebook Messenger message to a specific person by name. "
                        "Only call when the user explicitly requests to send a message."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Full or partial name of the Facebook contact.",
                            },
                            "message": {
                                "type": "string",
                                "description": "The message text to send.",
                            },
                        },
                        "required": ["recipient_name", "message"],
                    },
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        if tool_name == "run_command":
            cmd = tool_args.get("command", "").strip()
            if not cmd:
                return "No command provided."
            return await self.ssh_client.execute_command(cmd)

        elif tool_name == "facebook_get_messages":
            return await self.message_cache.to_ai_summary()

        elif tool_name == "facebook_send_reply":
            if not self.fb_service:
                return "Facebook service is not initialized."
            recipient = tool_args.get("recipient_name", "").strip()
            msg = tool_args.get("message", "").strip()
            return await self.fb_service.send_direct_reply(recipient, msg)

        return f"Unknown tool: {tool_name}"

    async def chat(self, chat_id: str, user_message: str) -> str:
        if not self.is_configured():
            return "AI chưa được cấu hình. Vui lòng thêm ít nhất 1 GROQ_API_KEY vào file .env."

        history = self._history_map.setdefault(chat_id, [])

        if self._is_greeting(user_message):
            greeting = (
                'Xin chào! Tôi là "Tiểu Bảo Bảo trợ lí của Mạnh (Cua)", trợ lý tự động giám sát máy chủ Linux. '
                "Tôi có thể giúp bạn kiểm tra CPU, RAM, Disk, Docker containers, hoặc các tiến trình theo thời gian thực. "
                "Bạn có câu hỏi nào về máy chủ không?"
            )
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": greeting})
            self._trim_history(history)
            return greeting

        history.append({"role": "user", "content": user_message})

        for _ in range(MAX_AGENT_ITERATIONS):
            messages = [{"role": "system", "content": self._build_system_prompt()}]
            messages.extend(list(history))

            key = await self.groq_pool.get_next_key()
            if not key:
                return "Không tìm thấy Groq API Key hợp lệ."

            payload = {
                "model": self.model,
                "messages": messages,
                "tools": self._build_tools(),
                "tool_choice": "auto",
                "temperature": 0.1,
                "max_tokens": 1024,
            }

            try:
                response = await self._http_client.post(
                    GROQ_API_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )

                if response.status_code == 429:
                    await self.groq_pool.mark_rate_limited(key)
                    continue

                if response.status_code != 200:
                    # Resilient parser: if Groq model generated inline function text triggering tool_use_failed (400)
                    if response.status_code == 400 and "failed_generation" in response.text:
                        try:
                            err_data = response.json()
                            failed_gen = err_data.get("error", {}).get("failed_generation", "")
                            if failed_gen:
                                import re
                                cleaned_text = re.sub(r"<function=.*?>.*?</function>", "", failed_gen, flags=re.DOTALL).strip()
                                cleaned_text = re.sub(r"<function=.*", "", cleaned_text, flags=re.DOTALL).strip()
                                if cleaned_text:
                                    history.append({"role": "assistant", "content": cleaned_text})
                                    self._trim_history(history)
                                    return cleaned_text
                        except Exception:
                            pass

                    print(f"[AiAgent] Groq error {response.status_code}: {response.text}", flush=True)
                    logger.error("[AiAgent] Groq error %d: %s", response.status_code, response.text)
                    self.clear_history(chat_id)
                    return "Xin lỗi, đã xảy ra lỗi khi gọi AI. Vui lòng thử lại sau giây lát."

                data = response.json()
                choice = data["choices"][0]
                finish_reason = choice.get("finish_reason", "stop")
                assistant_msg = choice.get("message", {})

                raw_content = assistant_msg.get("content") or ""
                has_tool_calls = finish_reason == "tool_calls" and bool(assistant_msg.get("tool_calls"))

                if has_tool_calls:
                    history.append(assistant_msg)
                    for tc in assistant_msg["tool_calls"]:
                        call_id = tc.get("id", "call_1")
                        fn_name = tc.get("function", {}).get("name", "")
                        try:
                            fn_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                        except Exception:
                            fn_args = {}

                        tool_result = await self._execute_tool(fn_name, fn_args)
                        # For direct Facebook message sending, return tool result directly
                        # to eliminate any possible AI LLM hallucination or misreporting
                        if fn_name == "facebook_send_reply":
                            history.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": tool_result,
                            })
                            history.append({
                                "role": "assistant",
                                "content": tool_result,
                            })
                            self._trim_history(history)
                            return tool_result

                        history.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": tool_result,
                        })
                    continue

                # Fallback: Check if model emitted pseudo-XML function tags in plain text
                pseudo_calls = self._extract_pseudo_tool_calls(raw_content)
                if pseudo_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": f"call_pseudo_{idx}",
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
                        tool_result = await self._execute_tool(fn_name, fn_args)
                        history.append({
                            "role": "tool",
                            "tool_call_id": f"call_pseudo_{idx}",
                            "content": tool_result,
                        })
                    continue

                history.append(assistant_msg)
                self._trim_history(history)
                return raw_content.strip() or "Xin lỗi, tôi không thể xử lý yêu cầu lúc này."

            except Exception as e:
                print(f"[AiAgent] Agent execution exception: {e}", flush=True)
                logger.error("[AiAgent] Agent execution exception: %s", e, exc_info=True)
                return f"Đã xảy ra lỗi khi xử lý câu hỏi: {e}"

        self._trim_history(history)
        return "AI đã thử nhiều bước nhưng chưa hoàn thành yêu cầu."

    def _trim_history(self, history: List[Dict[str, Any]]) -> None:
        while len(history) > MAX_HISTORY_MESSAGES:
            history.pop(0)
            if history and history[0].get("role") == "tool":
                history.pop(0)

    def _extract_pseudo_tool_calls(self, text: str) -> List[Dict[str, Any]]:
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
                    args = json.loads(fn_args_str[start:end+1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        p2 = re.findall(r"<function>([a-zA-Z0-9_]+)</function>\s*({.*?})(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p2:
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start:end+1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        return calls
