"""
AgentMemoryService — Procedural & Episodic Memory Engine for Tiểu Bảo Bảo.

Architecture (3-tier):
  - Short-term  : Managed by AiAgentService._history_map (in-memory sliding window)
  - Episodic    : agent_memories table — raw correction/event log
  - Procedural  : agent_lessons table — distilled lessons injected into system prompt

Self-improvement loop:
  1. User corrects bot  →  record_correction()
  2. LLM extracts lesson →  _extract_and_save_lesson()
  3. Next chat turn      →  get_active_lessons() injected into _build_system_prompt()
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
import psycopg

from app.config import settings

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

# Keywords that signal the user is correcting the bot
CORRECTION_TRIGGERS = [
    "sai rồi", "sai roi", "không phải", "khong phai", "nhầm rồi", "nham roi",
    "không đúng", "khong dung", "bị sai", "bi sai", "không chính xác",
    "sửa lại", "sua lai", "anh không hỏi", "nhầm người", "nham nguoi",
    "nhầm tên", "nham ten", "không phải vậy", "không phải thế",
    "đó không phải", "bạn đã nhầm", "em nhầm rồi", "hiểu sai",
]


class AgentMemoryService:
    """Manages persistent memory (episodic + procedural) for the AI agent."""

    def __init__(self) -> None:
        self._lesson_cache: List[Dict[str, Any]] = []
        self._cache_dirty: bool = True  # Force DB load on first access
        self._http: Optional[httpx.AsyncClient] = None

    def set_http_client(self, client: httpx.AsyncClient) -> None:
        """Inject the shared httpx client from LlmRouter to avoid creating extra connections."""
        self._http = client

    # ──────────────────────────────────────────────────────────────────────────
    # Public API: Correction Detection Helper
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def is_correction(text: str) -> bool:
        """Returns True if the user message appears to be correcting the bot."""
        lower = text.lower()
        return any(t in lower for t in CORRECTION_TRIGGERS)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API: Recording Events
    # ──────────────────────────────────────────────────────────────────────────

    async def record_correction(
        self,
        user_input: str,
        original_response: str,
        context_turns: List[Dict[str, Any]],
    ) -> None:
        """
        Records a correction event and asynchronously triggers LLM-based lesson extraction.
        Fire-and-forget: never blocks the main chat response path.
        """
        context_snapshot = json.dumps(context_turns[-5:], ensure_ascii=False)
        memory_id = await self._insert_memory(
            event_type="correction",
            user_input=user_input,
            original_response=original_response,
            corrected_response=None,
            context_snapshot=context_snapshot,
        )
        if memory_id:
            # Run lesson extraction in background — does not delay bot reply
            asyncio.create_task(
                self._extract_and_save_lesson(memory_id, user_input, original_response, context_snapshot)
            )

    async def record_new_knowledge(
        self,
        topic: str,
        fact: str,
        source_message: str,
    ) -> None:
        """Records a new piece of factual knowledge provided by the user."""
        await self._insert_memory(
            event_type="new_knowledge",
            user_input=source_message,
            original_response=None,
            corrected_response=fact,
            context_snapshot=json.dumps({"topic": topic, "fact": fact}, ensure_ascii=False),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Public API: Lesson Management
    # ──────────────────────────────────────────────────────────────────────────

    async def get_active_lessons(self, limit: int = 8) -> str:
        """
        Returns formatted lesson block for injection into the system prompt.
        Uses in-memory cache invalidated on every new lesson write.
        """
        if self._cache_dirty:
            await self._refresh_lesson_cache(limit)

        if not self._lesson_cache:
            return ""

        lines = ["📚 *KINH NGHIỆM TỰ HỌC CỦA EM (Bài học từ các lần sai trước):*"]
        for i, lesson in enumerate(self._lesson_cache[:limit], 1):
            lines.append(f"{i}. [{lesson['event_type'].upper()}] {lesson['lesson_text']}")
            # Track usage asynchronously
            asyncio.create_task(self._increment_usage(lesson["id"]))

        return "\n".join(lines)

    async def list_lessons_for_display(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns raw lesson list for Telegram /lessons command display."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, trigger_pattern, lesson_text, event_type,
                               confidence, usage_count, is_active, created_at
                        FROM agent_lessons
                        WHERE is_active = TRUE
                        ORDER BY confidence DESC, usage_count DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = await cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
        except Exception as e:
            logger.error("[MemoryService] list_lessons_for_display error: %s", e)
            return []

    async def delete_lesson(self, lesson_id: int) -> bool:
        """Soft-delete: sets is_active=FALSE rather than hard-deleting."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE agent_lessons SET is_active = FALSE WHERE id = %s",
                        (lesson_id,),
                    )
                    await conn.commit()
                    deleted = cur.rowcount > 0
                    if deleted:
                        self._cache_dirty = True
                    return deleted
        except Exception as e:
            logger.error("[MemoryService] delete_lesson error: %s", e)
            return False

    async def add_lesson_manually(
        self,
        lesson_text: str,
        event_type: str = "manual",
        confidence: float = 0.90,
    ) -> Optional[int]:
        """Adds a lesson manually (via Telegram /lesson_add command)."""
        lesson_id = await self._insert_lesson(
            trigger_pattern="Manual entry by admin",
            lesson_text=lesson_text,
            event_type=event_type,
            confidence=confidence,
        )
        if lesson_id:
            self._cache_dirty = True
        return lesson_id

    async def get_memory_stats(self) -> Dict[str, Any]:
        """Returns memory statistics for /memory_stats command."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE event_type = 'correction')  AS corrections,
                            COUNT(*) FILTER (WHERE event_type = 'new_knowledge') AS new_knowledge,
                            COUNT(*)                                             AS total_memories
                        FROM agent_memories
                        """
                    )
                    mem_row = await cur.fetchone()

                    await cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE is_active = TRUE)  AS active_lessons,
                            COUNT(*) FILTER (WHERE is_active = FALSE) AS archived_lessons,
                            COALESCE(SUM(usage_count), 0)             AS total_lesson_usages
                        FROM agent_lessons
                        """
                    )
                    les_row = await cur.fetchone()

            return {
                "total_corrections": mem_row[0] if mem_row else 0,
                "total_new_knowledge": mem_row[1] if mem_row else 0,
                "total_memories": mem_row[2] if mem_row else 0,
                "active_lessons": les_row[0] if les_row else 0,
                "archived_lessons": les_row[1] if les_row else 0,
                "total_lesson_usages": les_row[2] if les_row else 0,
            }
        except Exception as e:
            logger.error("[MemoryService] get_memory_stats error: %s", e)
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Private: LLM-powered Lesson Extraction
    # ──────────────────────────────────────────────────────────────────────────

    async def _extract_and_save_lesson(
        self,
        memory_id: int,
        user_correction: str,
        original_response: str,
        context_snapshot: str,
    ) -> None:
        """
        Uses the LLM to analyze a correction and distill a concise, actionable lesson.
        This runs in background — any exception is logged and swallowed.
        """
        if not self._http:
            logger.warning("[MemoryService] No HTTP client set — skipping lesson extraction.")
            return

        prompt = f"""Bạn là một AI có khả năng tự phân tích lỗi và học hỏi.

Phân tích tình huống sau và rút ra MỘT bài học ngắn gọn, cụ thể, actionable để không lặp lại lỗi này.

--- TIN NHẮN SỬA LỖI CỦA USER ---
{user_correction}

--- CÂU TRẢ LỜI SAI CỦA BOT ---
{original_response[:500] if original_response else "(không có)"}

--- NGỮ CẢNH (5 turns gần nhất) ---
{context_snapshot[:800]}

Yêu cầu:
1. Bài học phải ngắn gọn (1-2 câu), viết ở dạng quy tắc hành động ("Khi X, hãy Y").
2. Bài học phải đủ cụ thể để áp dụng được ngay, không mơ hồ.
3. Chỉ trả về NỘI DUNG BÀI HỌC, không cần tiêu đề hay giải thích thêm.
4. Trả lời bằng tiếng Việt.

Ví dụ tốt: "Khi người dùng đề cập tên người Việt Nam, phải kiểm tra cả hai thứ tự Họ+Tên và Tên+Họ trước khi tìm kiếm."
Ví dụ xấu: "Cần cẩn thận hơn." (quá mơ hồ)

Bài học:"""

        try:
            groq_keys = settings.groq_keys
            if not groq_keys:
                return

            # Use the first available key for this background task
            api_key = groq_keys[0]
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 150,
            }

            resp = await self._http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if resp.status_code != 200:
                logger.warning("[MemoryService] Lesson extraction API returned %d", resp.status_code)
                return

            data = resp.json()
            lesson_text = data["choices"][0]["message"]["content"].strip()

            if not lesson_text or len(lesson_text) < 10:
                return

            # Determine trigger pattern (first 80 chars of user correction as key)
            trigger_pattern = user_correction[:80].strip()

            lesson_id = await self._insert_lesson(
                trigger_pattern=trigger_pattern,
                lesson_text=lesson_text,
                event_type="correction",
                confidence=0.70,
            )

            if lesson_id:
                # Link memory row to the new lesson
                await self._link_memory_to_lesson(memory_id, lesson_id)
                self._cache_dirty = True
                logger.info(
                    "[MemoryService] 🧠 New lesson extracted (id=%d): %s",
                    lesson_id,
                    lesson_text[:80],
                )

        except Exception as e:
            logger.error("[MemoryService] _extract_and_save_lesson error: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # Private: DB Helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _insert_memory(
        self,
        event_type: str,
        user_input: str,
        original_response: Optional[str],
        corrected_response: Optional[str],
        context_snapshot: Optional[str],
    ) -> Optional[int]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agent_memories
                            (event_type, user_input, original_response, corrected_response, context_snapshot)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (event_type, user_input, original_response, corrected_response, context_snapshot),
                    )
                    await conn.commit()
                    row = await cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error("[MemoryService] _insert_memory error: %s", e)
            return None

    async def _insert_lesson(
        self,
        trigger_pattern: str,
        lesson_text: str,
        event_type: str,
        confidence: float,
    ) -> Optional[int]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agent_lessons (trigger_pattern, lesson_text, event_type, confidence)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (trigger_pattern, lesson_text, event_type, confidence),
                    )
                    await conn.commit()
                    row = await cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error("[MemoryService] _insert_lesson error: %s", e)
            return None

    async def _link_memory_to_lesson(self, memory_id: int, lesson_id: int) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE agent_memories SET lesson_id = %s WHERE id = %s",
                        (lesson_id, memory_id),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[MemoryService] _link_memory_to_lesson error: %s", e)

    async def _refresh_lesson_cache(self, limit: int) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, lesson_text, event_type, confidence, usage_count
                        FROM agent_lessons
                        WHERE is_active = TRUE
                        ORDER BY confidence DESC, usage_count DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = await cur.fetchall()
                    self._lesson_cache = [
                        {
                            "id": r[0],
                            "lesson_text": r[1],
                            "event_type": r[2],
                            "confidence": float(r[3]),
                            "usage_count": r[4],
                        }
                        for r in rows
                    ]
                    self._cache_dirty = False
        except Exception as e:
            logger.warning("[MemoryService] _refresh_lesson_cache error: %s", e)
            self._cache_dirty = False  # Prevent infinite retry loop

    async def _increment_usage(self, lesson_id: int) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE agent_lessons SET usage_count = usage_count + 1, last_used_at = NOW() WHERE id = %s",
                        (lesson_id,),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[MemoryService] _increment_usage error: %s", e)

    async def ensure_tables(self) -> None:
        """Creates the memory tables if they do not exist yet (idempotent safety net)."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1 FROM agent_lessons LIMIT 1")
            logger.info("[MemoryService] Tables verified ✓")
        except Exception:
            logger.warning("[MemoryService] Tables not found — Flyway migration may be pending.")
