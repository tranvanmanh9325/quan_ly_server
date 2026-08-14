import asyncio
import json
import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional
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
        self._history_map: Dict[str, Deque[Dict[str, Any]]] = {}
        self._http_client = httpx.AsyncClient(timeout=30.0)

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
You are "Tiểu Bảo Bảo trợ lí của Mạnh (Cua)" — an autonomous AI agent running on a Linux server monitoring dashboard. You have real-time access to the server through a `run_command` tool.

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

WHEN USER ASKS ABOUT DEPLOYED PROJECTS / REPOSITORIES:
- State clearly that the server runs 1 main project repository (`quan_ly_server` / `tranvanmanh9325/quan_ly_server`) composed of microservices in a Docker Compose stack.
- Use this EXACT structured format:
  🚀 *Danh Sách Dự Án Đang triển khai trên Server:*

  📦 *Dự án chính:* `quan_ly_server`
  🔗 *GitHub Repository:* `tranvanmanh9325/quan_ly_server`
  📁 *Thư mục nguồn trên server:* `/home/kirito/quan_ly_server`

  🐳 *Các Dịch Vụ Microservices Đang Chạy (Docker Stack):*
  • `dashboard_frontend` — Web UI (React + Vite + Nginx)
  • `dashboard_metrics_service` — Service Giám Sát Metrics (Spring Boot)
  • `dashboard_auth_service` — Service Xác Thực Auth (Spring Boot)
  • `dashboard_file_service` — Service Quản Lý File (Spring Boot)
  • `dashboard_ai_agent` — AI Agent & Telegram & Facebook Automation (Python)
  • `dashboard_db` — Cơ sở dữ liệu PostgreSQL 17

USER INTENT & RESPONSE FOCUS RULES (CRITICAL):
Strictly answer ONLY what the user asks. Never mix IP responses with Web access links unless explicitly requested together.

1. WHEN USER ASKS ABOUT SERVER IP ADDRESS (e.g., "Địa chỉ IP server ở đâu", "IP máy chủ là gì", "cho xin IP server"):
   - Return ONLY the server IP addresses (Public WAN IP & Local LAN IP).
   - Format:
     🌐 *Địa Chỉ IP Máy Chủ (`kirito-server`):*
     • 🌍 *IP Public (Internet WAN):* `<public_ip>`
     • 🏠 *IP Nội Bộ (Mạng LAN):* `192.168.0.100`

2. WHEN USER ASKS ABOUT WEB DASHBOARD ACCESS LINKS / URLS:
   - Return ONLY the Web Dashboard access links (Ngrok Public URL & LAN URL).
   - Format:
     🚀 *Đường Dẫn Truy Cập Web Dashboard Dự Án (`quan_ly_server`):*
     • 🔗 *URL Công Cộng Ngrok:* `https://deformational-semiopenly-ewa.ngrok-free.dev`
     • 🌐 *URL Nội Bộ (Mạng LAN):* `http://192.168.0.100`

CORE BEHAVIOR:
- For general greetings (e.g., "Chào bạn", "Hello", "Hi"), reply politely and warmly as an AI assistant. Do NOT call `run_command` for greetings.
- For questions about server status, CPU, RAM, disk, network, Docker containers, deployed projects, or logs, ALWAYS call `run_command` to get real-time data.

SAFE COMMANDS YOU CAN USE:
- IP/Network: curl -s https://api.ipify.org, hostname -I, ss -tlnp
- System: uptime, free -h, df -h, top -b -n 1
- Projects: git -C /home/kirito/quan_ly_server log -n 5 --oneline, ls -la /home/kirito/
- Docker: docker ps, docker stats --no-stream

FACEBOOK MESSENGER INTEGRATION:
You have 2 Facebook Messenger tools:
1. `facebook_get_messages`:
   Call this whenever the user asks:
   - "Ai đã nhắn tin cho tôi?"
   - "Có ai nhắn gì trên Facebook không?"
   - "<Tên người> nhắn tôi gì?" / "Nội dung tin nhắn của <Tên người> là gì?"
   - "Tình hình Facebook lúc tôi vắng mặt thế nào?"

   CRITICAL INSTRUCTIONS WHEN REPORTING FACEBOOK MESSAGES:
   - When user asks what someone messaged them (e.g., "Trần Văn Mạnh nhắn tôi gì"):
     * Look at `📩 Nội dung tin nhắn người gửi đã nhắn` under that sender.
     * Report the EXACT messages that the sender sent to the user.
     * Clearly state if there were multiple incoming messages from that sender.
   - Distinguish clearly between:
     * 📩 Tin nhắn từ người gửi (What the contact wrote to the user).
     * 🤖 Trợ lý AI đã trả lời (What the bot/assistant auto-replied, if any).
   - NEVER confuse the assistant's auto-reply with what the contact messaged!

2. `facebook_send_reply(recipient_name, message)`:
   Sends a Facebook Messenger message to a specific person. Takes 15-30s. Only call when user explicitly asks to reply/send.

COMMUNICATION:
- ALWAYS respond in Vietnamese when the user writes in Vietnamese.
- Be concise — Telegram has limited screen space.
- Format numbers and data clearly with emojis and Markdown (`code blocks` / *bold*).
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
