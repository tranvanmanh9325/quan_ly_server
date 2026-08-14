import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

VN_TZ = timezone(timedelta(hours=7))
HISTORY_LIMIT = 50


class MessageEntry(BaseModel):
    sender_name: str
    incoming_messages: List[str] = Field(default_factory=list)
    last_reply_sent: str = ""
    thread_href: str = ""
    detected_at: datetime = Field(default_factory=lambda: datetime.now(VN_TZ))
    was_auto_replied: bool = False


class FacebookMessageCache:
    """
    In-memory thread-safe cache for Facebook Messenger activity.
    Stores structured incoming messages separated from bot auto-replies.
    """

    def __init__(self):
        self._entries: List[MessageEntry] = []
        self._last_scan_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def add_or_update(
        self,
        sender_name: str,
        incoming_messages: Optional[List[str]] = None,
        last_reply_sent: Optional[str] = None,
        thread_href: Optional[str] = None,
        was_auto_replied: bool = False,
    ) -> None:
        if not sender_name or not sender_name.strip():
            return

        clean_sender = sender_name.strip()
        clean_incoming = [m.strip() for m in (incoming_messages or []) if m and m.strip()]

        async with self._lock:
            existing = self._find_entry_sync(clean_sender)

            if not clean_incoming and existing and existing.incoming_messages:
                clean_incoming = list(existing.incoming_messages)

            reply_to_store = (
                last_reply_sent.strip()
                if last_reply_sent and last_reply_sent.strip()
                else (existing.last_reply_sent if existing else "")
            )

            href_to_store = (
                thread_href.strip()
                if thread_href and thread_href.strip()
                else (existing.thread_href if existing else "")
            )

            auto_replied_to_store = was_auto_replied or (existing.was_auto_replied if existing else False)

            # Remove old entry if present
            self._entries = [e for e in self._entries if e.sender_name.lower() != clean_sender.lower()]

            entry = MessageEntry(
                sender_name=clean_sender,
                incoming_messages=clean_incoming,
                last_reply_sent=reply_to_store,
                thread_href=href_to_store,
                detected_at=datetime.now(VN_TZ),
                was_auto_replied=auto_replied_to_store,
            )
            self._entries.insert(0, entry)

            while len(self._entries) > HISTORY_LIMIT:
                self._entries.pop()

    async def record_direct_reply(self, sender_name: str, reply_message: str) -> None:
        if not sender_name or not sender_name.strip():
            return
        async with self._lock:
            existing = self._find_entry_sync(sender_name)
            if existing:
                await self.add_or_update(
                    existing.sender_name,
                    existing.incoming_messages,
                    reply_message,
                    existing.thread_href,
                    True,
                )

    async def mark_scan_completed(self) -> None:
        async with self._lock:
            self._last_scan_at = datetime.now(VN_TZ)

    def _find_entry_sync(self, sender_name: str) -> Optional[MessageEntry]:
        if not sender_name or not self._entries:
            return None
        import unicodedata
        import re

        def _norm(s: str) -> str:
            nfkd = unicodedata.normalize("NFKD", s.lower())
            no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
            no_marks = no_marks.replace("đ", "d").replace("Đ", "D")
            cleaned = re.sub(r"[^a-z0-9\s]", " ", no_marks)
            return " ".join(cleaned.split())

        q_norm = _norm(sender_name)
        if not q_norm:
            return None

        # 1. Exact or substring match on normalized text
        for e in self._entries:
            e_norm = _norm(e.sender_name)
            if q_norm == e_norm or q_norm in e_norm or e_norm in q_norm:
                return e

        # 2. Token set overlap match (e.g. 'Mạnh Văn Trần' vs 'Trần Văn Mạnh')
        q_tokens = set(q_norm.split())
        best_match: Optional[MessageEntry] = None
        best_score = 0.0

        for e in self._entries:
            e_tokens = set(_norm(e.sender_name).split())
            if not e_tokens:
                continue
            overlap = len(q_tokens.intersection(e_tokens))
            score = overlap / max(len(q_tokens), len(e_tokens))
            if score > best_score and score >= 0.5:
                best_score = score
                best_match = e

        return best_match

    async def find_thread_href(self, sender_name: str) -> Optional[str]:
        async with self._lock:
            e = self._find_entry_sync(sender_name)
            return e.thread_href if e else None

    async def get_all(self) -> List[MessageEntry]:
        async with self._lock:
            return list(self._entries)

    async def to_ai_summary(self) -> str:
        async with self._lock:
            if not self._entries:
                scan_info = (
                    f" Lần quét gần nhất: {self._last_scan_at.strftime('%H:%M %d/%m/%Y')}."
                    if self._last_scan_at
                    else " Chưa có lần quét nào hoàn thành."
                )
                return f"Không có tin nhắn Facebook nào được ghi nhận kể từ lần quét gần nhất.{scan_info}"

            lines = []
            if self._last_scan_at:
                lines.append(f"Lần quét Facebook gần nhất: {self._last_scan_at.strftime('%H:%M %d/%m/%Y')}\n")

            lines.append(f"Danh sách tin nhắn Facebook được ghi nhận ({len(self._entries)} người):\n")

            for idx, e in enumerate(self._entries, start=1):
                lines.append(f"{idx}. 👤 Người gửi: {e.sender_name}")
                if e.incoming_messages:
                    lines.append("   📩 Nội dung tin nhắn người gửi đã nhắn:")
                    for m in e.incoming_messages:
                        lines.append(f'      • "{m}"')
                else:
                    lines.append("   📩 Nội dung tin nhắn người gửi đã nhắn: (Không có tin nhắn mới)")

                if e.last_reply_sent:
                    lines.append(f'   🤖 Trợ lý AI đã trả lời: "{e.last_reply_sent}"')

                status = "✅ Trạng thái: Đã gửi phản hồi tự động." if e.was_auto_replied else "⏳ Trạng thái: Chưa trả lời."
                lines.append(f"   {status}")
                lines.append(f"   🕐 Ghi nhận lúc: {e.detected_at.strftime('%H:%M %d/%m/%Y')}")
                lines.append(f"   🔗 Thread URL: {e.thread_href}\n")

            return "\n".join(lines).strip()
