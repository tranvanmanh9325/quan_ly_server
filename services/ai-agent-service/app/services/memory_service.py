"""
AgentMemoryService — Search-Grounded Self-Healing Memory Engine for Tiểu Bảo Bảo.

Architecture (3-tier):
  - Short-term  : Managed by AiAgentService._history_map (in-memory sliding window)
  - Episodic    : agent_memories table — raw correction/event log with search evidence
  - Procedural  : agent_lessons table — distilled lessons injected into system prompt

Self-improvement loop (Search-Grounded Reflexion, 2025 standard):
  1. User corrects bot        →  record_correction()
  2. LLM generates search query  →  _generate_search_query()
  3. DuckDuckGo search           →  _search_for_solution()
  4. LLM synthesizes grounded lesson  →  _extract_and_save_lesson(search_results)
  5. Next chat turn            →  get_active_lessons() injected into system prompt

Key principle (Bounded Self-Correction):
  All lessons must be grounded in external search evidence, not just LLM introspection.
  This prevents "confirmation bias" where the model reinforces its own wrong beliefs.
"""
import asyncio
import json
import logging
import re
from datetime import timezone, timedelta
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

# Max characters of search results to include in lesson extraction prompt
_MAX_SEARCH_RESULTS_CHARS = 1200


class AgentMemoryService:
    """Manages persistent memory (episodic + procedural) for the AI agent."""

    def __init__(self) -> None:
        self._lesson_cache: List[Dict[str, Any]] = []
        self._cache_dirty: bool = True  # Force DB load on first access
        self._http: Optional[httpx.AsyncClient] = None

    def set_http_client(self, client: httpx.AsyncClient) -> None:
        """Inject the shared httpx client from LlmRouter to avoid extra connections."""
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
        Records a correction event then asynchronously triggers search-grounded
        lesson extraction. Fire-and-forget — never blocks the chat response path.
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
            # Run search + lesson extraction in background
            asyncio.create_task(
                self._search_grounded_extraction(
                    memory_id=memory_id,
                    error_context=user_input,
                    original_response=original_response,
                    context_snapshot=context_snapshot,
                    event_type="correction",
                )
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

    async def search_and_heal(
        self,
        error_context: str,
        original_tool: str,
        user_message: str,
    ) -> None:
        """
        C3.4 Search-Grounded Healing for repeated tool failures.
        Called when a tool fails ≥2 times in a row. Searches for the best
        solution strategy and saves it as a searchable lesson.
        Fire-and-forget.
        """
        context_snapshot = json.dumps({
            "tool": original_tool,
            "error": error_context[:500],
            "user_message": user_message,
        }, ensure_ascii=False)

        memory_id = await self._insert_memory(
            event_type="tool_failure",
            user_input=user_message,
            original_response=error_context[:500],
            corrected_response=None,
            context_snapshot=context_snapshot,
        )
        if memory_id:
            asyncio.create_task(
                self._search_grounded_extraction(
                    memory_id=memory_id,
                    error_context=error_context,
                    original_response=f"Tool '{original_tool}' thất bại liên tiếp.",
                    context_snapshot=context_snapshot,
                    event_type="tool_failure",
                )
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Public API: Lesson Management
    # ──────────────────────────────────────────────────────────────────────────

    async def get_active_lessons(self, limit: int = 8) -> str:
        """
        Returns formatted lesson block for injection into the system prompt.
        Search-grounded lessons are marked with 🔍 for higher credibility.
        Uses in-memory cache invalidated on every new lesson write.
        """
        if self._cache_dirty:
            await self._refresh_lesson_cache(limit)

        if not self._lesson_cache:
            return ""

        lines = ["📚 *KINH NGHIỆM TỰ HỌC CỦA EM (Bài học từ các lần sai trước):*"]
        for i, lesson in enumerate(self._lesson_cache[:limit], 1):
            grounded_mark = "🔍" if lesson.get("is_search_grounded") else "💭"
            lines.append(f"{i}. {grounded_mark} [{lesson['event_type'].upper()}] {lesson['lesson_text']}")
            asyncio.create_task(self._increment_usage(lesson["id"]))

        lines.append("\n_(🔍 = Đã xác thực qua tìm kiếm web · 💭 = Từ phân tích nội tâm)_")
        return "\n".join(lines)

    async def list_lessons_for_display(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns raw lesson list for Telegram /lessons command display."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, trigger_pattern, lesson_text, event_type,
                               confidence, usage_count, is_active,
                               is_search_grounded, search_query, created_at
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
            is_search_grounded=False,
            search_query=None,
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
                            COUNT(*) FILTER (WHERE event_type = 'correction')    AS corrections,
                            COUNT(*) FILTER (WHERE event_type = 'new_knowledge') AS new_knowledge,
                            COUNT(*) FILTER (WHERE event_type = 'tool_failure')  AS tool_failures,
                            COUNT(*)                                              AS total_memories
                        FROM agent_memories
                        """
                    )
                    mem_row = await cur.fetchone()

                    await cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE is_active = TRUE)              AS active_lessons,
                            COUNT(*) FILTER (WHERE is_active = FALSE)             AS archived_lessons,
                            COUNT(*) FILTER (WHERE is_search_grounded = TRUE
                                             AND is_active = TRUE)                AS grounded_lessons,
                            COALESCE(SUM(usage_count), 0)                         AS total_lesson_usages
                        FROM agent_lessons
                        """
                    )
                    les_row = await cur.fetchone()

            return {
                "total_corrections": mem_row[0] if mem_row else 0,
                "total_new_knowledge": mem_row[1] if mem_row else 0,
                "total_tool_failures": mem_row[2] if mem_row else 0,
                "total_memories": mem_row[3] if mem_row else 0,
                "active_lessons": les_row[0] if les_row else 0,
                "archived_lessons": les_row[1] if les_row else 0,
                "search_grounded_lessons": les_row[2] if les_row else 0,
                "total_lesson_usages": les_row[3] if les_row else 0,
            }
        except Exception as e:
            logger.error("[MemoryService] get_memory_stats error: %s", e)
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Private: Search-Grounded Lesson Extraction Pipeline
    # ──────────────────────────────────────────────────────────────────────────

    async def _search_grounded_extraction(
        self,
        memory_id: int,
        error_context: str,
        original_response: str,
        context_snapshot: str,
        event_type: str,
    ) -> None:
        """
        Full pipeline: Generate query → Search DuckDuckGo → LLM extracts lesson.

        This is the core of Bounded Self-Correction:
        - LLM generates a targeted English search query from the error context
        - DuckDuckGo provides external evidence (web results)
        - LLM synthesizes a lesson grounded in real-world information
        - Lesson is saved with is_search_grounded=True and higher confidence (0.85)

        Runs in background, all exceptions are swallowed.
        """
        try:
            # Step 1: Generate a focused search query via LLM
            search_query = await self._generate_search_query(error_context, original_response, event_type)
            logger.info("[MemoryService] 🔍 Search query generated: %s", search_query)

            # Step 2: Search DuckDuckGo for external evidence
            search_results = ""
            is_search_grounded = False
            if search_query:
                search_results = await self._search_for_solution(search_query)
                is_search_grounded = bool(search_results)
                if search_results:
                    logger.info(
                        "[MemoryService] 🌐 Search returned %d chars of results for: %s",
                        len(search_results), search_query,
                    )
                else:
                    logger.info("[MemoryService] 🌐 Search returned no results — using LLM introspection only.")

            # Step 3: Save search metadata to episodic memory
            if search_query or search_results:
                await self._update_memory_search_data(memory_id, search_query, search_results[:2000])

            # Step 4: LLM synthesizes a lesson (grounded in search results if available)
            await self._extract_and_save_lesson(
                memory_id=memory_id,
                user_correction=error_context,
                original_response=original_response,
                context_snapshot=context_snapshot,
                search_results=search_results,
                event_type=event_type,
                is_search_grounded=is_search_grounded,
                search_query=search_query,
            )

        except Exception as e:
            logger.error("[MemoryService] _search_grounded_extraction error: %s", e, exc_info=True)

    async def _generate_search_query(
        self,
        error_context: str,
        original_response: str,
        event_type: str,
    ) -> str:
        """
        Uses a fast LLM call to generate a focused, English search query.

        Approach (from research, 2025):
        1. Preprocess error text: strip timestamps, paths, UUIDs to reduce noise
        2. Few-shot prompt with JSON output for intent classification
        3. English queries give significantly better search results than Vietnamese
        """
        if not self._http:
            return ""
        groq_keys = settings.groq_keys
        if not groq_keys:
            return ""

        cleaned = self._preprocess_error_text(error_context)

        # Ultra-short prompt works better with reasoning models — fewer tokens = less noise in reasoning chain
        prompt = (
            "Given the AI error below, output a Google search query (English, max 8 words).\n\n"
            "Examples:\n"
            "- 'khong tim thay Tran Van Manh tren Facebook' → Facebook find Vietnamese person profile\n"
            "- 'facebook_view_profile failed not found' → Facebook profile URL search find person\n"
            "- 'docker ps empty container not listed' → docker ps not showing container fix\n\n"
            f"Error: {cleaned[:250]}\n"
            "Search query:"
        )

        try:
            resp = await self._http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_keys[0]}", "Content-Type": "application/json"},
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    # Reasoning models use tokens to think before concluding.
                    # 30 was too low — reasoning chain gets cut off before reaching the answer.
                    "max_tokens": 512,
                },
                timeout=15.0,
            )
            if resp.status_code != 200:
                logger.warning("[MemoryService] _generate_search_query API returned %d", resp.status_code)
                return ""
            msg = resp.json()["choices"][0]["message"]
            raw = (msg.get("content") or "").strip()

            # All models on this Groq account are reasoning models — they put output in
            # the 'reasoning' field while keeping 'content' empty. Extract the query from
            # the reasoning text by finding the search query conclusion.
            if not raw:
                reasoning = (msg.get("reasoning") or "").strip()
                if reasoning:
                    # Priority 1: find explicit "→ <query>" pattern from examples format
                    arrow_match = re.search(r'→\s*([A-Za-z][^\n"\'{}←→]{5,70})', reasoning)
                    if arrow_match:
                        raw = arrow_match.group(1).strip()
                    else:
                        # Priority 2: find "search query: <text>" or "query: <text>"
                        q_match = re.search(
                            r'(?:search query|the query)[:\s]+([A-Za-z][^\n"\'{}]{5,70})',
                            reasoning, re.IGNORECASE
                        )
                        if q_match:
                            raw = q_match.group(1).strip()
                        else:
                            # Priority 3: short English-looking lines near end of reasoning (< 60 chars)
                            lines = [l.strip() for l in reasoning.split('\n') if l.strip()]
                            for line in reversed(lines[-10:]):
                                # Accept short lines that look like search queries (mostly English words)
                                if 5 < len(line) < 70 and not any(x in line.lower() for x in ['we need', 'the user', 'i need', 'i should', 'let me', 'convert']):
                                    raw = line
                                    break

            if not raw:
                return ""
            # Strip surrounding quotes, JSON artifacts, "Output:"/"Query:" prefix
            query = re.sub(r'^(output:|query:)\s*', '', raw, flags=re.IGNORECASE).strip().strip("\"'{}[]")
            # If LLM returned JSON anyway, try to extract query field
            if query.startswith("{"):
                try:
                    query = json.loads(query).get("query", "").strip().strip("\"'")
                except Exception:
                    pass
            return query[:100] if len(query) > 5 else ""
        except Exception as e:
            logger.warning("[MemoryService] _generate_search_query error: %s", e)
            return ""

    @staticmethod
    def _preprocess_error_text(text: str) -> str:
        """
        Cleans error/correction text to remove noise before LLM query generation.
        Strips timestamps, absolute paths, UUIDs, memory addresses.
        Keeps: error class names, library names, human-readable messages.
        """
        # Remove ISO timestamps (2026-08-20T09:38:12 or 2026-08-20 09:38:12)
        text = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "", text)
        # Remove Unix absolute paths
        text = re.sub(r"(/[a-zA-Z0-9_./-]+/)", "[PATH]/", text)
        # Remove Windows paths (use raw string for replacement to avoid bad escape)
        text = re.sub(r"[A-Z]:\\[^\s\\]+\\", r"[PATH]\\", text)
        # Remove memory addresses (0x1a2b3c...)
        text = re.sub(r"0x[0-9a-fA-F]{4,}", "[ADDR]", text)
        # Remove UUIDs
        text = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "[UUID]",
            text,
            flags=re.IGNORECASE,
        )
        # Collapse excessive whitespace
        text = re.sub(r"\s{2,}", " ", text)
        return text[:1000].strip()

    async def _search_for_solution(self, query: str) -> str:
        """
        Searches DuckDuckGo via subprocess + Jina/Bing fallback.

        Root cause of executor failure (diagnosed):
          - ddgs v9 uses 'primp' HTTP client which is NOT thread-safe
          - run_in_executor() returns 'No results' even when sync call works
          - subprocess isolates the HTTP stack completely

        Strategy:
        1. Primary: asyncio.create_subprocess_exec(python -c ddgs) — 3 retries, 3s delay
        2. Fallback A: Jina Reader on first result URL (if DDGS got URLs)
        3. Fallback B: Jina Reader wrapping a Bing search URL (when DDGS returns nothing)
           — covers queries that Bing backend blocks for a specific subprocess call
        """
        import asyncio, urllib.parse

        # Script runs in its own process — completely isolated primp/HTTP stack
        _SEARCH_SCRIPT = (
            "import sys, json; from ddgs import DDGS\n"
            "q = sys.argv[1]\n"
            "try:\n"
            "    r = DDGS().text(q, max_results=4, timelimit='y') or []\n"
            "    print(json.dumps(r))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'error': str(e)}))\n"
        )

        results: list = []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python", "-c", _SEARCH_SCRIPT, query,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=22.0)
                data = json.loads(stdout.decode().strip())
                if isinstance(data, list):
                    results = data
                    if results:
                        break  # Success — exit retry loop
                    # Empty list: Bing blocked this query, retry with delay
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3.0)
                elif isinstance(data, dict) and "error" in data:
                    err_str = data["error"].lower()
                    if ("ratelimit" in err_str or "no results" in err_str) and attempt < max_retries - 1:
                        delay = 3.0 * (attempt + 1)  # 3s → 6s → 9s
                        logger.warning(
                            "[MemoryService] DDGS no results (attempt %d/%d). Retrying in %.1fs...",
                            attempt + 1, max_retries, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.warning("[MemoryService] DDGS subprocess error: %s", data["error"])
                        break
            except (asyncio.TimeoutError, Exception) as err:
                logger.warning("[MemoryService] DDGS subprocess failed: %s", err)
                if attempt < max_retries - 1:
                    await asyncio.sleep(3.0)

        # Format and return DDGS results
        if results:
            parts = []
            for r in results:
                title = r.get("title", "").strip()
                body = r.get("body", "").strip()
                href = r.get("href", "")
                if title and body:
                    parts.append(f"📄 **{title}**\n   {body[:350]}\n   🔗 {href}")
            if parts:
                return "\n\n".join(parts)

        if not self._http:
            return ""

        # Fallback A: Jina Reader on first DDGS result URL (deep content)
        first_url = results[0].get("href", "") if results else ""
        if first_url:
            try:
                resp = await self._http.get(
                    f"https://r.jina.ai/{first_url}",
                    headers={"Accept": "text/markdown", "User-Agent": "TieuBaoBao-Agent/1.0"},
                    timeout=12.0, follow_redirects=True,
                )
                if resp.status_code == 200:
                    content = resp.text.strip()[:1500]
                    if len(content) > 50:
                        logger.info("[MemoryService] Jina A (URL) succeeded: %s", first_url)
                        return f"📖 *Web content:*\n\n{content}"
            except Exception as e:
                logger.warning("[MemoryService] Jina A failed: %s", e)

        # Fallback B: Jina Reader wrapping a Bing search URL
        # This catches queries that DDGS/Bing blocks but Jina can still fetch
        try:
            bing_url = "https://www.bing.com/search?q=" + urllib.parse.quote_plus(query)
            resp = await self._http.get(
                f"https://r.jina.ai/{bing_url}",
                headers={"Accept": "text/markdown", "User-Agent": "TieuBaoBao-Agent/1.0"},
                timeout=15.0, follow_redirects=True,
            )
            if resp.status_code == 200:
                content = resp.text.strip()[:2000]
                if len(content) > 100:
                    logger.info("[MemoryService] Jina B (Bing) succeeded for query: %s", query)
                    return f"📖 *Web content (Bing via Jina):*\n\n{content}"
        except Exception as e:
            logger.warning("[MemoryService] Jina B (Bing) failed: %s", e)

        return ""


    async def _extract_and_save_lesson(
        self,
        memory_id: int,
        user_correction: str,
        original_response: str,
        context_snapshot: str,
        search_results: str,
        event_type: str,
        is_search_grounded: bool,
        search_query: str,
    ) -> None:
        """
        Uses LLM to synthesize a concise, actionable lesson.
        When search_results are available, the lesson is grounded in external evidence
        → higher confidence (0.85) and marked as is_search_grounded=True.
        """
        if not self._http:
            return

        groq_keys = settings.groq_keys
        if not groq_keys:
            return

        # Build search evidence block
        search_block = ""
        if search_results:
            search_block = f"""
--- KẾT QUẢ TÌM KIẾM WEB (Bằng chứng từ bên ngoài) ---
Query đã tìm: "{search_query}"
{search_results[:_MAX_SEARCH_RESULTS_CHARS]}
--- HẾT KẾT QUẢ TÌM KIẾM ---
"""

        prompt = f"""Bạn là AI có khả năng tự phân tích lỗi và học hỏi từ bằng chứng thực tế.

Dựa trên tình huống lỗi và kết quả tìm kiếm web bên dưới, hãy rút ra MỘT bài học ngắn gọn, cụ thể, actionable.

--- TÌNH HUỐNG LỖI ---
Loại: {event_type}
Tin nhắn sửa lỗi: {user_correction[:400]}
Câu trả lời SAI của bot: {original_response[:300] if original_response else "(không có)"}
Ngữ cảnh: {context_snapshot[:500]}
{search_block}
--- YÊU CẦU ---
1. Bài học phải ngắn gọn (1-2 câu), dạng quy tắc hành động: "Khi X, hãy Y."
2. {"Ưu tiên sử dụng thông tin từ kết quả tìm kiếm web để đảm bảo tính chính xác." if search_results else "Phân tích dựa trên ngữ cảnh hội thoại."}
3. Cụ thể và áp dụng được ngay, không mơ hồ.
4. Chỉ trả về NỘI DUNG BÀI HỌC bằng tiếng Việt.

Ví dụ tốt: "Khi tìm người Việt Nam, luôn thử cả thứ tự Họ+Tên và Tên+Họ vì user có thể nhập theo cả hai chiều."
Ví dụ xấu: "Cần cẩn thận hơn."

Bài học:"""

        try:
            resp = await self._http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_keys[0]}", "Content-Type": "application/json"},
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 180,
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.warning("[MemoryService] Lesson extraction API returned %d", resp.status_code)
                return

            lesson_text = resp.json()["choices"][0]["message"]["content"].strip()
            if not lesson_text or len(lesson_text) < 10:
                return

            # Search-grounded lessons get a confidence boost (0.85 vs 0.70)
            confidence = 0.85 if is_search_grounded else 0.70
            trigger_pattern = user_correction[:80].strip()

            lesson_id = await self._insert_lesson(
                trigger_pattern=trigger_pattern,
                lesson_text=lesson_text,
                event_type=event_type,
                confidence=confidence,
                is_search_grounded=is_search_grounded,
                search_query=search_query if is_search_grounded else None,
            )

            if lesson_id:
                await self._link_memory_to_lesson(memory_id, lesson_id)
                self._cache_dirty = True
                grounded_tag = "🔍 [SEARCH-GROUNDED]" if is_search_grounded else "💭 [INTROSPECTION]"
                logger.info(
                    "[MemoryService] 🧠 %s Lesson saved (id=%d, confidence=%.2f): %s",
                    grounded_tag, lesson_id, confidence, lesson_text[:100],
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

    async def _update_memory_search_data(
        self, memory_id: int, search_query: str, search_results: str
    ) -> None:
        """Saves the search query and results back to the episodic memory row."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE agent_memories SET search_query = %s, search_results = %s WHERE id = %s",
                        (search_query, search_results, memory_id),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[MemoryService] _update_memory_search_data error: %s", e)

    async def _insert_lesson(
        self,
        trigger_pattern: str,
        lesson_text: str,
        event_type: str,
        confidence: float,
        is_search_grounded: bool,
        search_query: Optional[str],
    ) -> Optional[int]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agent_lessons
                            (trigger_pattern, lesson_text, event_type, confidence,
                             is_search_grounded, search_query)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (trigger_pattern, lesson_text, event_type, confidence,
                         is_search_grounded, search_query),
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
                        SELECT id, lesson_text, event_type, confidence,
                               usage_count, is_search_grounded
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
                            "is_search_grounded": bool(r[5]),
                        }
                        for r in rows
                    ]
                    self._cache_dirty = False
        except Exception as e:
            logger.warning("[MemoryService] _refresh_lesson_cache error: %s", e)
            self._cache_dirty = False

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
        """Creates/verifies memory tables (idempotent safety net for startup)."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1 FROM agent_lessons LIMIT 1")
                    await cur.execute("SELECT 1 FROM agent_episodes LIMIT 1")
                    await cur.execute("SELECT 1 FROM agent_pending_tasks LIMIT 1")
                    await cur.execute("SELECT 1 FROM agent_proactive_checks LIMIT 1")
            logger.info("[MemoryService] All tables verified ✓ (lessons, episodes, pending_tasks, proactive_checks)")
        except Exception as e:
            logger.warning("[MemoryService] Some tables not found (%s) — Flyway migration may be pending.", e)

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 4: Episodic Memory (Hippocampal model — CoALA 2024)
    # Stores specific events tied to time+context, separate from semantic lessons.
    # High-salience events (Amygdala tagging) are preserved permanently.
    # ──────────────────────────────────────────────────────────────────────────

    async def record_episode(
        self,
        event_summary: str,
        event_type: str = "incident",
        severity: str = "low",
        salience_score: float = 0.5,
        full_context: Optional[str] = None,
        tags: Optional[List[str]] = None,
        expires_days: Optional[int] = 30,
    ) -> Optional[int]:
        """
        Records a specific episodic event (hippocampal memory).
        High-salience events (>= 0.8) are kept permanently (expires_at = NULL).
        Lower-salience events expire after expires_days.
        """
        # Amygdala rule: critical/high severity → permanent storage
        if severity in ("critical", "high") or salience_score >= 0.8:
            expires_at_sql = None
        elif expires_days:
            from datetime import datetime
            expires_at_sql = datetime.now(VN_TZ) + timedelta(days=expires_days)
        else:
            expires_at_sql = None

        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agent_episodes
                            (event_summary, event_type, severity, salience_score,
                             full_context, tags, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (event_summary, event_type, severity, salience_score,
                         full_context, tags or [], expires_at_sql),
                    )
                    await conn.commit()
                    row = await cur.fetchone()
                    episode_id = row[0] if row else None
                    if episode_id:
                        logger.info(
                            "[MemoryService] 🧠 Episode recorded: [%s/%s] salience=%.2f id=%d",
                            severity, event_type, salience_score, episode_id
                        )
                    return episode_id
        except Exception as e:
            logger.error("[MemoryService] record_episode error: %s", e)
            return None

    async def get_recent_episodes(self, limit: int = 5, days_back: int = 30) -> str:
        """
        Returns formatted recent episodes for injection into context.
        Only returns episodes from the last `days_back` days, highest salience first.
        Called from AiAgentService._build_system_prompt() for episodic recall.
        """
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT event_summary, event_type, severity, salience_score,
                               occurred_at, tags
                        FROM agent_episodes
                        WHERE is_active = TRUE
                          AND (expires_at IS NULL OR expires_at > NOW())
                          AND occurred_at > NOW() - INTERVAL '%s days'
                        ORDER BY salience_score DESC, occurred_at DESC
                        LIMIT %s
                        """,
                        (days_back, limit),
                    )
                    rows = await cur.fetchall()
        except Exception as e:
            logger.warning("[MemoryService] get_recent_episodes error: %s", e)
            return ""

        if not rows:
            return ""

        severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        lines = ["🗓️ *SỰ KIỆN GẦN ĐÂY (Episodic Memory):*"]
        for summary, etype, sev, salience, occurred_at, tags in rows:
            icon = severity_icon.get(sev, "⚪")
            ts = occurred_at.astimezone(VN_TZ).strftime("%d/%m %H:%M") if occurred_at else "?"
            tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
            lines.append(f"  {icon} [{ts}] {summary}{tag_str}")
        return "\n".join(lines)

    async def expire_old_episodes(self) -> int:
        """Soft-deletes episodes past their expiry date. Called during nightly consolidation."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE agent_episodes
                        SET is_active = FALSE
                        WHERE is_active = TRUE
                          AND expires_at IS NOT NULL
                          AND expires_at < NOW()
                        """,
                    )
                    await conn.commit()
                    count = cur.rowcount
                    if count:
                        logger.info("[MemoryService] Synaptic pruning: expired %d old episodes.", count)
                    return count
        except Exception as e:
            logger.warning("[MemoryService] expire_old_episodes error: %s", e)
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 5A: Prospective Memory (Prefrontal Cortex model)
    # Remembering to do things in the future — triggered by time or conversation turns.
    # ──────────────────────────────────────────────────────────────────────────

    async def add_pending_task(
        self,
        task_summary: str,
        created_by_msg: str = "",
        remind_turns: int = 3,
    ) -> Optional[int]:
        """
        Records a pending task for future reminder (prospective memory).
        The task gets injected into system prompt every `remind_turns` conversation turns.
        """
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agent_pending_tasks
                            (task_summary, created_by_msg, remind_turns)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (task_summary, created_by_msg[:500], remind_turns),
                    )
                    await conn.commit()
                    row = await cur.fetchone()
                    task_id = row[0] if row else None
                    if task_id:
                        logger.info("[MemoryService] 📋 Pending task recorded: %s (id=%d)", task_summary[:60], task_id)
                    return task_id
        except Exception as e:
            logger.error("[MemoryService] add_pending_task error: %s", e)
            return None

    async def complete_pending_task(self, task_id: int) -> bool:
        """Marks a pending task as done."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE agent_pending_tasks
                        SET status = 'done', completed_at = NOW()
                        WHERE id = %s AND status = 'pending'
                        """,
                        (task_id,),
                    )
                    await conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.warning("[MemoryService] complete_pending_task error: %s", e)
            return False

    async def get_pending_tasks_prompt(self) -> str:
        """
        Returns formatted pending tasks for injection into system prompt.
        Increments turns_elapsed; auto-completes tasks older than 7 days with no action.
        """
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    # Auto-expire tasks older than 7 days
                    await cur.execute(
                        """
                        UPDATE agent_pending_tasks
                        SET status = 'cancelled'
                        WHERE status = 'pending'
                          AND created_at < NOW() - INTERVAL '7 days'
                        """
                    )
                    # Increment turns_elapsed for all pending tasks
                    await cur.execute(
                        "UPDATE agent_pending_tasks SET turns_elapsed = turns_elapsed + 1 WHERE status = 'pending'"
                    )
                    # Fetch tasks due for reminder (turns_elapsed >= remind_turns)
                    await cur.execute(
                        """
                        SELECT id, task_summary, created_at
                        FROM agent_pending_tasks
                        WHERE status = 'pending'
                          AND turns_elapsed >= remind_turns
                        ORDER BY created_at ASC
                        LIMIT 5
                        """
                    )
                    rows = await cur.fetchall()
                    await conn.commit()
        except Exception as e:
            logger.warning("[MemoryService] get_pending_tasks_prompt error: %s", e)
            return ""

        if not rows:
            return ""

        lines = ["📋 *VIỆC CÒN ĐANG CHỜ (Prospective Memory):*"]
        for task_id, summary, created_at in rows:
            ts = created_at.astimezone(VN_TZ).strftime("%d/%m") if created_at else "?"
            lines.append(f"  • [#{task_id} - {ts}] {summary}")
        lines.append("_(Gõ 'xong việc #ID' để đánh dấu hoàn thành)_")
        return "\n".join(lines)

    async def list_pending_tasks(self) -> List[Dict[str, Any]]:
        """Returns raw list of pending tasks for /tasks Telegram command."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, task_summary, status, remind_turns,
                               turns_elapsed, created_at
                        FROM agent_pending_tasks
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        LIMIT 20
                        """
                    )
                    rows = await cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.error("[MemoryService] list_pending_tasks error: %s", e)
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 5B: Proactive Intelligence — Curiosity-Driven Health Checks
    # ──────────────────────────────────────────────────────────────────────────

    async def upsert_proactive_check(
        self,
        check_key: str,
        current_value: str,
        send_alert: bool,
    ) -> None:
        """
        Updates the last known value for a proactive check.
        Sets last_alerted timestamp when an alert is sent (for cooldown logic).
        """
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    if send_alert:
                        await cur.execute(
                            """
                            INSERT INTO agent_proactive_checks
                                (check_key, last_value, last_alerted, alert_count, updated_at)
                            VALUES (%s, %s, NOW(), 1, NOW())
                            ON CONFLICT (check_key) DO UPDATE
                              SET last_value   = EXCLUDED.last_value,
                                  last_alerted = NOW(),
                                  alert_count  = agent_proactive_checks.alert_count + 1,
                                  updated_at   = NOW()
                            """,
                            (check_key, current_value),
                        )
                    else:
                        await cur.execute(
                            """
                            INSERT INTO agent_proactive_checks
                                (check_key, last_value, updated_at)
                            VALUES (%s, %s, NOW())
                            ON CONFLICT (check_key) DO UPDATE
                              SET last_value = EXCLUDED.last_value,
                                  updated_at = NOW()
                            """,
                            (check_key, current_value),
                        )
                    await conn.commit()
        except Exception as e:
            logger.warning("[MemoryService] upsert_proactive_check error: %s", e)

    async def should_send_proactive_alert(
        self,
        check_key: str,
        cooldown_hours: int = 6,
    ) -> bool:
        """
        Returns True if enough time has passed since last alert for this check_key.
        Prevents alert spam with configurable cooldown.
        """
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT last_alerted FROM agent_proactive_checks
                        WHERE check_key = %s
                        """,
                        (check_key,),
                    )
                    row = await cur.fetchone()
                    if not row or row[0] is None:
                        return True
                    from datetime import datetime
                    last = row[0]
                    elapsed = datetime.now(VN_TZ) - last.astimezone(VN_TZ)
                    return elapsed.total_seconds() >= cooldown_hours * 3600
        except Exception as e:
            logger.warning("[MemoryService] should_send_proactive_alert error: %s", e)
            return False
