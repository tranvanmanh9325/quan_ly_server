import asyncio
import logging
from typing import Any, Dict, Optional
import httpx
import psycopg

from app.config import settings
from app.core.ssh_client import SshClient
from app.services.ai_agent import AiAgentService

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, ai_agent: AiAgentService, ssh_client: SshClient):
        self.ai_agent = ai_agent
        self.ssh_client = ssh_client
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.polling_enabled = settings.TELEGRAM_POLLING_ENABLED
        self._http_client = httpx.AsyncClient(timeout=35.0)
        self._running = False
        self._last_offset = 0

    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.token or not text:
            return False
        try:
            url = f"{self.api_url}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            res = await self._http_client.post(url, json=payload)
            if res.status_code == 200:
                return True
            # Fallback without parse_mode if Markdown parsing failed
            if "can't parse entities" in res.text.lower():
                payload.pop("parse_mode", None)
                res2 = await self._http_client.post(url, json=payload)
                return res2.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed sending message: %s", e)
        return False

    async def _claim_update(self, update_id: int) -> bool:
        """Ensures at-most-once processing using PostgreSQL unique index."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO processed_telegram_updates (update_id) VALUES (%s) ON CONFLICT (update_id) DO NOTHING",
                        (update_id,),
                    )
                    await conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.warning("[TelegramBot] Error claiming update %d: %s", update_id, e)
            return True

    async def _handle_command(self, command: str, chat_id: str) -> None:
        cmd = command.split("@")[0].lower().strip()
        if cmd in ["/start", "/help"]:
            msg = (
                "🤖 *Tiểu Bảo Bảo — Trợ lý Giám Sát Máy Chủ*\n\n"
                "📌 *Các lệnh nhanh:*\n"
                "• /status — Tổng quan trạng thái server\n"
                "• /cpu — Mức sử dụng CPU\n"
                "• /ram — Dung lượng RAM & Swap\n"
                "• /disk — Dung lượng ổ cứng\n"
                "• /ai — Xóa bộ nhớ ngữ cảnh hội thoại\n\n"
                "💬 *Hoặc bạn có thể hỏi tự nhiên bằng tiếng Việt!*"
            )
            await self.send_message(chat_id, msg)

        elif cmd == "/status":
            uptime = await self.ssh_client.execute_command("uptime")
            docker = await self.ssh_client.execute_command("docker ps --format 'table {{.Names}}\t{{.Status}}'")
            msg = f"📊 *Trạng Thái Máy Chủ:*\n\n⏱ `{uptime}`\n\n🐳 *Containers:*\n```{docker}```"
            await self.send_message(chat_id, msg)

        elif cmd == "/cpu":
            cpu = await self.ssh_client.execute_command("top -b -n 1 | head -n 5")
            await self.send_message(chat_id, f"⚡ *CPU Status:*\n```{cpu}```")

        elif cmd == "/ram":
            ram = await self.ssh_client.execute_command("free -h")
            await self.send_message(chat_id, f"💾 *Bộ Nhớ RAM & Swap:*\n```{ram}```")

        elif cmd == "/disk":
            disk = await self.ssh_client.execute_command("df -hT /")
            await self.send_message(chat_id, f"💿 *Dung Lượng Ổ Đĩa:*\n```{disk}```")

        elif cmd == "/ai":
            self.ai_agent.clear_history(chat_id)
            await self.send_message(chat_id, "🧹 Đã xóa lịch sử hội thoại AI. Bạn có thể bắt đầu phiên hỏi mới.")

        else:
            # Route unrecognized slash command to AI
            reply = await self.ai_agent.chat(chat_id, command)
            await self.send_message(chat_id, reply)

    async def _process_update(self, update: Dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if not update_id or not await self._claim_update(update_id):
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()

        if not text or not chat_id:
            return

        # Security check: If configured with a specific TELEGRAM_CHAT_ID, reject unauthorized users
        if self.chat_id and self.chat_id != chat_id:
            logger.warning("[TelegramBot] Unauthorized message from chat_id %s", chat_id)
            await self.send_message(chat_id, "⛔ Bạn không có quyền truy cập bot này.")
            return

        if text.startswith("/"):
            await self._handle_command(text, chat_id)
        else:
            reply = await self.ai_agent.chat(chat_id, text)
            await self.send_message(chat_id, reply)

    async def start_polling(self) -> None:
        if not self.token or not self.polling_enabled:
            logger.info("[TelegramBot] Polling disabled or token missing.")
            return

        self._running = True
        logger.info("[TelegramBot] Starting async long-polling...")

        backoff = 2
        while self._running:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {
                    "offset": self._last_offset + 1 if self._last_offset > 0 else 0,
                    "timeout": 20,
                }
                res = await self._http_client.get(url, params=params)

                if res.status_code == 200:
                    data = res.json()
                    updates = data.get("result", [])
                    for u in updates:
                        self._last_offset = max(self._last_offset, u.get("update_id", 0))
                        asyncio.create_task(self._process_update(u))
                    backoff = 2

                elif res.status_code == 409:
                    logger.warning("[TelegramBot] 409 Conflict — another polling instance active. Backing off for %ds.", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(60, backoff * 2)

                else:
                    logger.warning("[TelegramBot] getUpdates returned %d: %s", res.status_code, res.text)
                    await asyncio.sleep(5)

            except Exception as e:
                logger.error("[TelegramBot] Polling error: %s", e)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
