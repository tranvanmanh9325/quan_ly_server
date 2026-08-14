import asyncio
import collections
import functools
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

VN_TZ = timezone(timedelta(hours=7))
HISTORY_LIMIT = 50

# Fast C-level transliteration table for O(1) normalized string matching
_VN_TRANS_TABLE = str.maketrans(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ",
    "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD"
)


@functools.lru_cache(maxsize=2048)
def _fast_normalize_name(text: str) -> str:
    if not text:
        return ""
    s = text.translate(_VN_TRANS_TABLE).lower()
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
    return " ".join(cleaned.split())


class MessageEntry(BaseModel):
    sender_name: str
    incoming_messages: List[str] = Field(default_factory=list)
    last_reply_sent: str = ""
    thread_href: str = ""
    detected_at: datetime = Field(default_factory=lambda: datetime.now(VN_TZ))
    was_auto_replied: bool = False


class FacebookMessageCache:
    """
    Thread-safe, Bounded O(1) LRU Cache for Facebook Messenger activity.
    Uses collections.OrderedDict for strict O(1) eviction and LRU re-ordering.
    Eliminates memory leaks and array-shifting overhead.
    """

    def __init__(self, capacity: int = HISTORY_LIMIT):
        self._capacity = capacity
        self._entries: collections.OrderedDict[str, MessageEntry] = collections.OrderedDict()
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
        norm_key = _fast_normalize_name(clean_sender)
        if not norm_key:
            return

        clean_incoming = [m.strip() for m in (incoming_messages or []) if m and m.strip()]

        async with self._lock:
            existing = self._entries.get(norm_key)

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

            entry = MessageEntry(
                sender_name=clean_sender,
                incoming_messages=clean_incoming,
                last_reply_sent=reply_to_store,
                thread_href=href_to_store,
                detected_at=datetime.now(VN_TZ),
                was_auto_replied=was_auto_replied,
            )

            # O(1) update and move to front (MRU - Most Recently Used)
            self._entries[norm_key] = entry
            self._entries.move_to_end(norm_key, last=False)

            # O(1) pop LRU (Least Recently Used) if capacity exceeded
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=True)

    async def record_direct_reply(self, sender_name: str, reply_message: str) -> None:
        if not sender_name or not sender_name.strip():
            return
        await self.add_or_update(
            sender_name=sender_name,
            last_reply_sent=reply_message,
            was_auto_replied=True,
        )

    async def mark_scan_completed(self) -> None:
        async with self._lock:
            self._last_scan_at = datetime.now(VN_TZ)

    def _find_entry_sync(self, sender_name: str) -> Optional[MessageEntry]:
        if not sender_name or not self._entries:
            return None

        norm_q = _fast_normalize_name(sender_name)
        if not norm_q:
            return None

        # 1. Exact O(1) hash map lookup
        entry = self._entries.get(norm_q)
        if entry:
            return entry

        # 2. Substring & Fuzzy token lookup
        q_tokens = set(norm_q.split())
        best_match: Optional[MessageEntry] = None
        best_score = 0.0

        for key, e in self._entries.items():
            if norm_q in key or key in norm_q:
                return e
            e_tokens = set(key.split())
            if e_tokens:
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
            return list(self._entries.values())

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

            for idx, e in enumerate(self._entries.values(), start=1):
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
