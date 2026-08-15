import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 6


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
        self._history_map: Dict[str, List[Dict[str, Any]]] = {}

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service

    def is_configured(self) -> bool:
        return self.llm_router.has_active_providers

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
  * `dashboard_ai_agent` (Python FastAPI + Playwright AI Agent & 9Router Gateway - Port 8084)
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
   - When the user asks "Hiện có những tài khoản nào tôi chưa trả lời?", "Ai đang nhắn tin?", "Có tin nhắn mới nào không?", "trong thời gian tôi vắng có ai nhắn cho tôi không", "Tóm tắt tình hình Facebook":
     * Call `facebook_get_messages()` to inspect the inbox.
     * Once you receive the messages list, analyze the results and answer the user directly and concisely in Vietnamese. DO NOT re-invoke `facebook_get_messages()` once you already have the data in this turn.
     * If no incoming messages: State clearly that no new messages were received during their absence.
     * If there are contacts with unreplied messages (or auto-replied by AI): Clearly list out:
       - 👤 Tên người gửi: <Tên>
       - 📩 Nội dung tin nhắn họ đã gửi: <Nội dung chi tiết>
       - ⚠️ Tình trạng: Trợ lý AI đã gửi tin nhắn vắng mặt tự động, nhưng bạn (chủ tài khoản) chưa trực tiếp trả lời.

3. DEVOPS & SERVER MONITORING COMMANDS:
   - When user asks about top CPU / RAM consuming processes: Call `run_command` with `ps aux --sort=-%cpu | head -n 6` or `top -b -n 1 | head -n 15`.
   - When user asks about disk storage: Call `run_command` with `df -h /`.
   - When user asks about memory usage: Call `run_command` with `free -h`.
   - When user asks about Docker container health: Call `run_command` with `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`.
   - Format results cleanly in structured Markdown bullet points with appropriate emojis (📊, 💾, ⚡, 🐳).

4. DIRECT REPLY VERIFICATION:
   - When `facebook_send_reply` succeeds, confirm clearly: `Đã gửi tin nhắn cho "<recipient_name>": "<message>"`.
   - Never hallucinate fake responses. Always rely on actual tool execution returns.

5. LANGUAGE RULE:
   - Answer directly and helpfully in Vietnamese unless requested otherwise.
   - For simple greetings, respond with a warm greeting and brief list of server monitoring capabilities.
"""

    def _build_tools(self, excluded_tools: Optional[set] = None) -> List[Dict[str, Any]]:
        excluded = excluded_tools or set()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Execute a non-interactive bash command on the Linux server via SSH to inspect metrics or system state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The bash command to execute (e.g., 'free -m', 'df -h', 'docker ps', 'top -b -n 1').",
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
                    "description": "Retrieve recent scanned Facebook Messenger conversations, incoming messages, and reply statuses.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_send_reply",
                    "description": "Send a direct reply message to a Facebook contact in Messenger. NEVER invent or send a message unless the user explicitly requested to reply to that specific contact.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "The exact or partial name of the Facebook contact (e.g., 'Trần Văn Mạnh').",
                            },
                            "message": {
                                "type": "string",
                                "description": "The exact message text to send to the recipient.",
                            },
                        },
                        "required": ["recipient_name", "message"],
                    },
                },
            },
        ]
        return [t for t in tools if t["function"]["name"] not in excluded]

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        try:
            if tool_name == "run_command":
                cmd = tool_args.get("command", "")
                if not cmd:
                    return "Error: No command specified."
                raw_output = await self.ssh_client.execute_command(cmd)
                # Apply 9Router RTK output compression to conserve tokens
                return self.llm_router.rtk.compress(raw_output, max_chars=3000, max_lines=40)

            if tool_name == "facebook_get_messages":
                raw_cache = await self.message_cache.to_ai_summary()
                return self.llm_router.rtk.compress(raw_cache, max_chars=3000, max_lines=40)

            if tool_name == "facebook_send_reply":
                if not self.fb_service:
                    return "Facebook service is not initialized."
                recipient = tool_args.get("recipient_name", "").strip()
                msg = tool_args.get("message", "").strip()
                return await self.fb_service.send_direct_reply(recipient, msg)

            return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error("[AiAgentService] Error executing tool '%s': %s", tool_name, e, exc_info=True)
            return f"Lỗi khi thực thi công cụ {tool_name}: {str(e)}"

    async def chat(self, chat_id: str, user_message: str) -> str:
        if not self.is_configured():
            return "AI chưa được cấu hình. Vui lòng thêm ít nhất 1 GROQ_API_KEY hoặc OPENROUTER_API_KEY vào file .env."

        history = self._history_map.setdefault(chat_id, [])

        if self._is_greeting(user_message):
            greeting = (
                'Xin chào! Tôi là "Tiểu Bảo Bảo trợ lí của Mạnh (Cua)", trợ lý tự động giám sát máy chủ Linux (Được tăng tốc bởi 9Router AI Gateway). '
                "Tôi có thể giúp bạn kiểm tra CPU, RAM, Disk, Docker containers, hoặc các tiến trình theo thời gian thực. "
                "Bạn có câu hỏi nào về máy chủ không?"
            )
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": greeting})
            self._trim_history(history)
            return greeting

        history.append({"role": "user", "content": user_message})
        executed_inquiry_tools = set()

        for _ in range(MAX_AGENT_ITERATIONS):
            messages = [{"role": "system", "content": self._build_system_prompt()}]
            messages.extend(list(history))

            tools_available = self._build_tools(excluded_tools=executed_inquiry_tools)

            llm_result = await self.llm_router.complete(
                messages=messages,
                tools=tools_available if tools_available else None,
                tool_choice="auto" if tools_available else "none",
                temperature=0.1,
                max_tokens=1024,
            )

            if not llm_result:
                self.clear_history(chat_id)
                return "Xin lỗi, 9Router AI Gateway hiện không kết nối được tới các nhà cung cấp AI. Vui lòng thử lại sau giây lát."

            choice = llm_result["choices"][0]
            assistant_msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "stop")
            raw_content = assistant_msg.get("content") or ""
            has_tool_calls = finish_reason == "tool_calls" and bool(assistant_msg.get("tool_calls"))

            if has_tool_calls:
                history.append(assistant_msg)
                for tc in assistant_msg["tool_calls"]:
                    call_id = tc.get("id", "call_1")
                    fn_name = tc.get("function", {}).get("name", "")
                    if fn_name in ("facebook_get_messages",):
                        executed_inquiry_tools.add(fn_name)

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
