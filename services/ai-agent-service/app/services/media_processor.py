"""
Media Processor — Multimodal input pipeline for Tiểu Bảo Bảo AI Agent.

Handles three input modalities received via Telegram:
  1. Voice / Audio  → Groq Whisper STT (turbo → v3 fallback)
  2. Image / Photo  → Groq Vision (qwen3.8-27b → qwen3.6-27b)
                      → OpenRouter Vision (gemma-4-31b:free → gemma-4-26b:free → openrouter/free)
  3. Document       → Local offline extraction (PyMuPDF / python-docx / openpyxl / builtin)
"""

import base64
import csv
import io
import json
import logging
from pathlib import Path
from typing import List, Optional

import httpx
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# Max document text fed into LLM context to avoid token overflow
_MAX_DOC_CHARS = 8_000
# Max image dimension before resizing (Groq 4MB base64 limit)
_MAX_IMG_DIMENSION = 1024
_IMG_QUALITY = 85

# OpenRouter fallback chain for vision (verified free tier, Aug 2026)
_OR_VISION_MODELS = [
    settings.OPENROUTER_VISION_MODEL,           # google/gemma-4-31b-it:free
    settings.OPENROUTER_VISION_MODEL_FALLBACK,  # google/gemma-4-26b-a4b-it:free
    "openrouter/free",                          # auto-router last resort
]

_OR_VISION_HEADERS_BASE = {
    "HTTP-Referer": "https://dashboard.kirito.server",
    "X-Title": "Tiểu Bảo Bảo AI Agent",
    "Content-Type": "application/json",
}

_VISION_SYSTEM_PROMPT = (
    "Bạn là trợ lý AI thông minh tên Tiểu Bảo Bảo. "
    "Hãy phân tích hình ảnh được cung cấp và mô tả chi tiết, chính xác nội dung. "
    "Trả lời hoàn toàn bằng tiếng Việt, ngắn gọn và súc tích."
)


class MediaProcessor:
    """
    Processes multimodal inputs from Telegram: voice, photo, document.
    Designed to be injected into TelegramBot and reuse its httpx.AsyncClient.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        # Reuse caller's client if provided to avoid extra connection pools
        self._http = http_client or httpx.AsyncClient(timeout=60.0)
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # ─── Step 1: Download file from Telegram ─────────────────────────────────

    async def download_telegram_file(self, file_id: str) -> bytes:
        """
        Two-step Telegram file download:
        1. getFile → resolve file_path
        2. Stream download from file CDN URL
        Max file size allowed by Telegram Bot API: 20 MB.
        """
        token = settings.TELEGRAM_BOT_TOKEN
        get_file_url = f"https://api.telegram.org/bot{token}/getFile"
        resp = await self._http.get(get_file_url, params={"file_id": file_id})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise ValueError(f"Telegram getFile failed: {data.get('description')}")
        file_path = data["result"]["file_path"]

        cdn_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        dl_resp = await self._http.get(cdn_url, timeout=60.0)
        dl_resp.raise_for_status()
        return dl_resp.content

    # ─── Modality 1: Voice → Groq Whisper STT ────────────────────────────────

    # Known Whisper hallucination patterns (trained on YouTube/podcast data).
    # Whisper "fills in" these phrases when audio is short, quiet, or ambiguous.
    # We reject transcriptions that are ONLY these patterns to avoid false positives.
    _HALLUCINATION_BLACKLIST = [
        # Vietnamese YouTube/livestream patterns
        "cảm ơn các bạn đã theo dõi",
        "đăng ký kênh",
        "subscribe",
        "hẹn gặp lại",
        "like và subscribe",
        "nhấn chuông thông báo",
        "cảm ơn các bạn",
        "xin chào các bạn",
        "chúc các bạn",
        "ghiền mì gõ",
        "cảm ơn bạn đã xem",
        # English YouTube patterns
        "thank you for watching",
        "please subscribe",
        "don't forget to subscribe",
        "see you in the next video",
        "like and subscribe",
        "hit the bell",
        # Common noise/silence patterns
        ".",
        " .",
        "...",
        "thank you",
        "thanks for watching",
    ]

    @staticmethod
    def _is_hallucination(text: str, duration_seconds: int) -> bool:
        """
        Detects Whisper hallucinations by checking:
        1. Known hallucination phrases (YouTube/livestream patterns)
        2. Suspiciously long transcription for very short audio (ratio check)
        """
        if not text:
            return False
        t_lower = text.lower().strip()

        # Check against known hallucination patterns
        for pattern in MediaProcessor._HALLUCINATION_BLACKLIST:
            if pattern in t_lower:
                # Only reject if the hallucination pattern DOMINATES the transcription
                # (i.e., the pattern makes up >60% of total text length)
                if len(pattern) / max(len(t_lower), 1) > 0.6:
                    return True

        # Suspiciously verbose for very short audio (< 4s producing > 60 chars is suspect)
        if duration_seconds <= 3 and len(text) > 60:
            return True

        return False

    async def transcribe_voice(
        self,
        audio_bytes: bytes,
        filename: str = "voice.oga",
        language: str = "vi",
        duration: int = 0,
    ) -> str:
        """
        Sends audio to Groq Whisper STT.
        Primary: whisper-large-v3-turbo (216x real-time, 20 RPM, 28,800 audio-sec/day).
        Fallback: whisper-large-v3.

        Anti-hallucination measures:
        - temperature=0: greedy decoding — no random sampling → far fewer hallucinations
        - prompt anchor: primes model toward conversational Vietnamese (away from YouTube patterns)
        - blacklist filter: rejects known hallucination phrases post-transcription

        NOTE: Groq Whisper rejects .oga extension (Telegram native format).
        We rename to .ogg which Groq accepts — same OGG container, Opus codec.
        """
        groq_keys = settings.groq_keys
        if not groq_keys:
            return ""

        # Groq whitelist: flac, mp3, mp4, mpeg, mpga, m4a, ogg, opus, wav, webm
        # Telegram voice messages use .oga (OGG Opus) which is NOT in Groq's whitelist.
        ext = Path(filename).suffix.lower()
        if ext == ".oga":
            filename = Path(filename).with_suffix(".ogg").name
        _GROQ_AUDIO_EXTS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".opus", ".wav", ".webm"}
        if Path(filename).suffix.lower() not in _GROQ_AUDIO_EXTS:
            filename = "voice.ogg"

        # Prompt anchor: steers model toward conversational Vietnamese.
        # Whisper was trained heavily on YouTube → biased toward "Thank you for watching".
        # Providing a conversational context shifts probability mass away from those patterns.
        _STT_PROMPT = "Cuộc trò chuyện bằng tiếng Việt:"

        models = [settings.GROQ_WHISPER_MODEL, settings.GROQ_WHISPER_MODEL_FALLBACK]

        for model in models:
            for key in groq_keys[:3]:
                try:
                    resp = await self._http.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"},
                        data={
                            "model": model,
                            "language": language,
                            "response_format": "json",
                            "temperature": "0",        # greedy decoding → minimal hallucination
                            "prompt": _STT_PROMPT,     # anchor away from YouTube patterns
                        },
                        files={"file": (filename, audio_bytes, "audio/ogg")},
                        timeout=90.0,
                    )
                    if resp.status_code == 200:
                        text = resp.json().get("text", "").strip()
                        # Post-processing: reject known hallucination patterns
                        if self._is_hallucination(text, duration):
                            logger.warning(
                                "[MediaProcessor] STT hallucination detected (model=%s): '%s' → discarding",
                                model, text[:80]
                            )
                            # Return empty string → caller will ask user to repeat
                            return ""
                        logger.info("[MediaProcessor] STT ✅ model=%s len=%d text='%s'", model, len(text), text[:60])
                        return text
                    if resp.status_code == 429:
                        logger.warning("[MediaProcessor] STT 429 key=%s... model=%s", key[:8], model)
                        continue
                    logger.warning("[MediaProcessor] STT HTTP %d: %s", resp.status_code, resp.text[:200])
                except Exception as exc:
                    logger.error("[MediaProcessor] STT error: %s", exc)

        logger.error("[MediaProcessor] STT failed — all Groq keys exhausted")
        return ""

    # ─── Modality 2: Image → Vision (Groq → OpenRouter fallback) ─────────────

    @staticmethod
    def _encode_image(image_bytes: bytes) -> str:
        """Resize to max 1024px JPEG and encode as base64 to keep payload < 4MB."""
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            img.thumbnail((_MAX_IMG_DIMENSION, _MAX_IMG_DIMENSION), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_IMG_QUALITY)
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    @staticmethod
    def _build_vision_messages(b64: str, caption: str) -> list:
        user_text = caption if caption else "Hãy phân tích và mô tả chi tiết nội dung hình ảnh này."
        return [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ]

    async def _analyze_image_groq(self, b64: str, caption: str) -> Optional[str]:
        """
        Try Groq Vision: qwen3.8-27b → qwen3.6-27b.
        Note: tool_calls not passed — Groq vision runs in analysis-only mode,
        result is then forwarded to ai_agent.chat() for full ReAct processing.
        """
        groq_keys = settings.groq_keys
        if not groq_keys:
            return None

        models = [settings.GROQ_VISION_MODEL, settings.GROQ_VISION_MODEL_FALLBACK]
        messages = self._build_vision_messages(b64, caption)

        for model in models:
            for key in groq_keys[:3]:
                try:
                    resp = await self._http.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1024},
                        timeout=60.0,
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        logger.info("[MediaProcessor] Vision-Groq ✅ model=%s", model)
                        return content.strip()
                    if resp.status_code == 429:
                        logger.warning("[MediaProcessor] Vision-Groq 429 key=%s... model=%s", key[:8], model)
                        continue
                    logger.warning("[MediaProcessor] Vision-Groq HTTP %d: %s", resp.status_code, resp.text[:150])
                except Exception as exc:
                    logger.error("[MediaProcessor] Vision-Groq error: %s", exc)

        return None

    async def _analyze_image_openrouter(self, b64: str, caption: str) -> Optional[str]:
        """
        OpenRouter Vision fallback chain:
        gemma-4-31b:free → gemma-4-26b:free → openrouter/free (auto-router).
        These models support vision + tool_calls simultaneously.
        """
        or_keys = settings.openrouter_keys
        if not or_keys:
            return None

        messages = self._build_vision_messages(b64, caption)

        for model in _OR_VISION_MODELS:
            for key in or_keys[:2]:
                try:
                    resp = await self._http.post(
                        settings.OPENROUTER_API_URL,
                        headers={**_OR_VISION_HEADERS_BASE, "Authorization": f"Bearer {key}"},
                        json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1024},
                        timeout=60.0,
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        logger.info("[MediaProcessor] Vision-OR ✅ model=%s", model)
                        return content.strip()
                    if resp.status_code == 429:
                        logger.warning("[MediaProcessor] Vision-OR 429 key=%s... model=%s", key[:8], model)
                        continue
                    logger.warning("[MediaProcessor] Vision-OR HTTP %d: %s", resp.status_code, resp.text[:150])
                except Exception as exc:
                    logger.error("[MediaProcessor] Vision-OR error: %s", exc)

        return None

    async def analyze_image(self, image_bytes: bytes, caption: str = "") -> str:
        """
        Orchestrator: Groq Vision → OpenRouter Vision → graceful text fallback.
        Returns a string description to be prepended and passed to ai_agent.chat().
        """
        try:
            b64 = self._encode_image(image_bytes)
        except Exception as exc:
            logger.error("[MediaProcessor] Image encode error: %s", exc)
            return "(Không thể đọc định dạng ảnh này)"

        result = await self._analyze_image_groq(b64, caption)
        if not result:
            logger.info("[MediaProcessor] Groq vision failed, trying OpenRouter...")
            result = await self._analyze_image_openrouter(b64, caption)

        if result:
            return result

        logger.error("[MediaProcessor] All vision providers failed")
        return (
            "(Em nhận được ảnh nhưng chưa thể phân tích lúc này do rate limit. "
            "Anh Mạnh vui lòng mô tả nội dung ảnh để em hỗ trợ.)"
        )

    # ─── Modality 3: Document → Text Extraction (offline) ────────────────────

    @staticmethod
    def _extract_pdf(data: bytes) -> str:
        import fitz  # PyMuPDF — lazy import
        pages: List[str] = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page_num in range(min(len(doc), 50)):
                text = doc[page_num].get_text("text").strip()
                if text:
                    pages.append(f"--- [Trang {page_num + 1}] ---\n{text}")
        return "\n\n".join(pages)

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        import docx  # python-docx — lazy import
        doc = docx.Document(io.BytesIO(data))
        parts: List[str] = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        for idx, table in enumerate(doc.tables, 1):
            parts.append(f"\n[Bảng {idx}]:")
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells))
        return "\n".join(parts)

    @staticmethod
    def _extract_xlsx(data: bytes) -> str:
        import openpyxl  # lazy import
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        sheets: List[str] = []
        for name in wb.sheetnames:
            ws = wb[name]
            rows: List[str] = [f"=== Sheet: {name} ==="]
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                if row_idx > 200:
                    rows.append("... (cắt bớt sau 200 dòng)")
                    break
                if any(v is not None for v in row):
                    rows.append(" | ".join(str(v) if v is not None else "" for v in row))
            if len(rows) > 1:
                sheets.append("\n".join(rows))
        wb.close()
        return "\n\n".join(sheets)

    @staticmethod
    def _extract_csv(data: bytes) -> str:
        text = data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows: List[str] = []
        for idx, row in enumerate(reader, 1):
            if idx > 200:
                rows.append("... (cắt bớt sau 200 dòng)")
                break
            rows.append(" | ".join(row))
        return "\n".join(rows)

    # Supported plain-text extensions (read directly)
    _TEXT_EXTENSIONS = frozenset({
        ".txt", ".md", ".py", ".js", ".ts", ".sh", ".bash",
        ".yaml", ".yml", ".toml", ".ini", ".env", ".log",
        ".html", ".xml", ".css", ".sql", ".rs", ".go",
        ".java", ".c", ".cpp", ".h", ".conf", ".cfg",
    })

    def extract_document_text(
        self,
        file_bytes: bytes,
        mime_type: Optional[str],
        filename: str,
    ) -> str:
        """
        Auto-dispatches to the right extractor based on file extension + MIME type.
        Returns extracted text, capped at _MAX_DOC_CHARS to protect token budget.
        """
        ext = Path(filename).suffix.lower()
        mime = (mime_type or "").lower()

        try:
            if ext == ".pdf" or "pdf" in mime:
                raw = self._extract_pdf(file_bytes)
            elif ext == ".docx" or "wordprocessingml" in mime or "msword" in mime:
                raw = self._extract_docx(file_bytes)
            elif ext in (".xlsx", ".xlsm") or "spreadsheetml" in mime or "ms-excel" in mime:
                raw = self._extract_xlsx(file_bytes)
            elif ext == ".csv" or "csv" in mime:
                raw = self._extract_csv(file_bytes)
            elif ext == ".json" or "json" in mime:
                parsed = json.loads(file_bytes.decode("utf-8", errors="replace"))
                raw = json.dumps(parsed, indent=2, ensure_ascii=False)
            elif ext in self._TEXT_EXTENSIONS or mime.startswith("text/"):
                raw = file_bytes.decode("utf-8", errors="replace")
            else:
                return (
                    f"(Định dạng file `{ext or 'không rõ'}` chưa được hỗ trợ đọc tự động. "
                    "Hỗ trợ: PDF, DOCX, XLSX, CSV, JSON, TXT và các file source code.)"
                )
        except ImportError as exc:
            logger.error("[MediaProcessor] Missing package for %s: %s", ext, exc)
            return f"(Lỗi: thiếu thư viện để đọc file `{ext}`. Chi tiết: {exc})"
        except Exception as exc:
            logger.error("[MediaProcessor] Extract error for %s: %s", filename, exc)
            return f"(Không thể đọc file `{filename}`: {exc})"

        # Hard cap to avoid context window overflow
        if len(raw) > _MAX_DOC_CHARS:
            raw = raw[:_MAX_DOC_CHARS] + f"\n\n... (nội dung bị cắt bớt, chỉ hiển thị {_MAX_DOC_CHARS} ký tự đầu)"

        return raw.strip()
