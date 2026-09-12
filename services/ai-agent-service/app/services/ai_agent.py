import asyncio
from datetime import datetime, timezone, timedelta
import json
import logging
import re
import shlex
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import settings
from app.core.brain_core import ArtificialBrain
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache
from app.services.ai_agent_tools import AgentToolExecutor, DIRECT_RETURN_TOOLS, SCREENSHOT_TOOLS
from app.core.vietnamese_dialect import linguistic_normalizer

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))


def _sanitize_for_log(data: Any) -> Any:
    """
    Sanitizes dictionary or nested structures before logging to prevent credential/token leaks (CWE-532).
    """
    if isinstance(data, dict):
        sensitive_keywords = {"password", "token", "secret", "cookie", "api_key", "key", "auth"}
        return {
            k: ("***REDACTED***" if any(sk in str(k).lower() for sk in sensitive_keywords) else _sanitize_for_log(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_sanitize_for_log(item) for item in data]
    return data


# How many ReAct loop iterations the agent may take before giving up
MAX_AGENT_ITERATIONS = 8
# How many messages to keep in the sliding conversation window
MAX_HISTORY_MESSAGES = 10

# ── Phase 1: Dual Process Gating ─────────────────────────────────────────────
# Inspired by Kahneman Dual Process Theory: System 1 (fast) vs System 2 (slow).
# The brain knows when to think fast vs think deep — we make that explicit here.

# Keywords that signal a COMPLEX/System 2 task (multi-step reasoning, diagnosis, dangerous ops)
_COMPLEX_KEYWORDS = frozenset({
    "tại sao", "why", "phân tích", "analyze", "debug", "chẩn đoán",
    "diagnose", "lỗi", "sự cố", "incident", "tổng quan", "overview",
    "kiểm tra toàn bộ", "health check", "giải thích", "explain",
    "so sánh", "compare", "kế hoạch", "plan", "tối ưu", "optimize",
    "bảo mật", "security", "log", "journalctl", "oom", "crash",
    "container nào", "dịch vụ nào",
})

# Keywords that signal a CRITICAL/dangerous operation (mandatory confirmation)
_CRITICAL_KEYWORDS = frozenset({
    "xóa", "delete", "drop", "rm -", "rm -rf", "shutdown", "halt",
    "format c:", "format disk", "mkfs", "truncate", "purge", "wipe", "kill -9", "stop tất cả",
    "restart tất cả", "iptables -f", "disable firewall",
})

# Fast-path patterns for truly SIMPLE factual queries (≤ 1 tool, ground truth)
_SIMPLE_PATTERN = re.compile(
    r'^(chào|hello|hi|alo|bắt đầu|server|máy chủ|kirito|đặt ở|vị trí|ip|địa chỉ|tên em|em là|'
    r'mấy giờ|hôm nay|ngày|ram|cpu|disk|ổ đĩa|ping|uptime|'
    r'đăng nhập|login|kết nối|truy cập|ai đang|máy tính|'
    r'version|phiên bản|docker ps|container)\b',
    re.IGNORECASE | re.UNICODE
)

# ── Phase 9 (v4.0): Dendritic SLM Routing ────────────────────────────────────
# Pre-LLM intent classifier: routes to specialized context/tool-sets
# Mirrors dendritic pre-computation before neuron body (SLM routing 2024).
_INTENT_DIAGNOSTIC = re.compile(
    r'\b(tại sao|lỗi gì|check|kiểm tra|xem|status|log|journalctl|dmesg|'
    r'health|trạng thái|bao nhiêu|mấy|còn|hết|đang chạy|running|ps|'
    r'vị trí|ở đâu|đang ở|tọa độ|địa chỉ|ip|'
    r'đăng nhập|login|kết nối|truy cập|ai đang|máy tính nào|session|phiên|'
    r'hoạt động|thế nào|ra sao|tình hình|sức khỏe|ổn không)\b',
    re.IGNORECASE | re.UNICODE
)
_INTENT_ACTION = re.compile(
    r'\b(tạo|khởi động|restart|start|stop|kill|deploy|cài|install|'
    r'update|upgrade|chạy lệnh|run|execute|xóa docker|prune|clean)\b',
    re.IGNORECASE | re.UNICODE
)
_INTENT_LEARNING = re.compile(
    r'\b(nhớ|lưu|ghi nhớ|bài học|học|remind|remember|remember_for_later|'
    r'giải thích|explain|tại sao lại|how does|hướng dẫn)\b',
    re.IGNORECASE | re.UNICODE
)
_INTENT_QUERY = re.compile(
    r'\b(hỏi|query|tìm|search|liệt kê|danh sách|list|database|db|'
    r'bảng|table|select|count|thống kê|báo cáo|report)\b',
    re.IGNORECASE | re.UNICODE
)

# ── Pre-compiled regexes & keywords for high-performance, ReDoS-safe log parsing ──
_CRITICAL_LOG_KEYWORDS = (
    "error", "warn", "crit", "fatal", "fail", "oom", "killed", "panic", "exception"
)
_CRITICAL_LOG_PATTERN = re.compile(r"\b(?:exit\s+\d+|\d+%|\d+\s*(?:gb|mb|g|m))\b", re.IGNORECASE)
_OK_LOG_PATTERN = re.compile(r"\b(?:ok|healthy|running|active|up|online|pass)\b", re.IGNORECASE)
_TIMESTAMP_LOG_PATTERN = re.compile(r"\b\d{2}:\d{2}(?::\d{2})?\b")

# ── Phase 7 (v4.0): Global Workspace Theory Broadcast Size ───────────────────
# Only top-K most relevant lessons are broadcast into the agent's "global workspace"
# (injected into system prompt). Mimics Dehaene's 70-item global workspace limit.
_GWT_TOP_K_LESSONS = 7


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
        self.appointment_service: Any = None
        self.memory_service: Any = None  # AgentMemoryService — persistent self-learning memory
        self._history_map: Dict[str, List[Dict[str, Any]]] = {}
        self._cached_lessons: str = ""   # Semantic memory — refreshed each chat() call
        self._cached_episodes: str = ""  # Episodic memory — refreshed each chat() call
        self._cached_pending: str = ""   # Prospective memory — refreshed each chat() call
        self._cached_schemas: str = ""   # Schema memory (v4.0) — refreshed each chat() call
        self._cached_causal_hints: str = ""  # STDP causal hints (v4.0) — refreshed each chat() call
        self._current_user_query: Optional[str] = None
        # Phase 12 (v5.0): Autonomous Neuromorphic Brain Core (FEP, 32GB Virtual Cortex, Neurotransmitters)
        self.brain: ArtificialBrain = ArtificialBrain.get_instance()
        # Tool execution subsystem (Gorilla RAT Scoped Tools)
        self.tools = AgentToolExecutor(
            ssh_client=ssh_client,
            message_cache=message_cache,
            fb_service=fb_service_ref,
        )

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service
        if hasattr(self, 'tools'): self.tools.set_fb_service(fb_service)

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot
        if hasattr(self, 'tools'): self.tools.set_telegram_bot(telegram_bot)

    def set_browser_agent(self, browser_agent: Any) -> None:
        self.browser_agent = browser_agent
        if hasattr(self, 'tools'): self.tools.set_browser_agent(browser_agent)

    def set_appointment_service(self, appointment_service: Any) -> None:
        self.appointment_service = appointment_service
        if hasattr(self, 'tools'): self.tools.set_appointment_service(appointment_service)

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject the AgentMemoryService for self-improving capabilities."""
        self.memory_service = memory_service
        if hasattr(self, 'tools'): self.tools.set_memory_service(memory_service)

    def set_dream_engine(self, dream_engine: Any) -> None:
        """Inject the SubconsciousDreamEngine for overnight SWS & REM sleep consolidation."""
        self.dream_engine = dream_engine

    def is_configured(self) -> bool:
        return self.llm_router.has_active_providers

    def clear_history(self, chat_id: str) -> None:
        self._history_map.pop(chat_id, None)

    def _is_greeting(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        return t in ["chào bạn", "chào", "hello", "hi", "bắt đầu", "chào bot", "xin chào", "alo"]

    @staticmethod
    def _extract_user_command(msg: str) -> str:
        """Extracts the actual user query/command text if msg is a document/file attachment envelope."""
        if (msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or 
            msg.startswith("[📸") or msg.startswith("[🎬")):
            lines = msg.splitlines()
            for line in lines[:6]:
                if (line.startswith("[Yêu cầu từ anh Mạnh]:") or line.startswith("• Yêu cầu từ anh Mạnh:") or 
                    line.startswith("Caption:") or line.startswith("[📸") or line.startswith("[🎬")):
                    return line
            return lines[0]
        return msg

    def _classify_complexity(self, msg: str) -> str:
        """
        Phase 1 — Dual Process Gating (Kahneman System 1 vs System 2).

        The prefrontal cortex evaluates uncertainty to decide whether fast pattern
        matching (System 1) or deliberate multi-step reasoning (System 2) is needed.
        We make that evaluation explicit here.

        Returns: 'simple' | 'complex' | 'critical'
        """
        cmd_text = self._extract_user_command(msg)
        cmd_lower = cmd_text.lower()
        word_count = len(cmd_text.split())

        # CRITICAL: dangerous/destructive commands → mandatory confirmation gate
        # Evaluated ONLY on user's direct command/caption, NEVER on raw attachment content
        if any(k in cmd_lower for k in _CRITICAL_KEYWORDS):
            return "critical"

        # Document and media attachments are always processed with System 2 (complex) depth
        if (msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or 
            msg.startswith("[📸") or msg.startswith("[🎬")):
            return "complex"

        # COMPLEX: multi-step reasoning, diagnosis, comparison
        if word_count > 20 or any(k in cmd_lower for k in _COMPLEX_KEYWORDS):
            return "complex"

        # SIMPLE: short factual query matching known ground-truth patterns
        if word_count <= 15 and _SIMPLE_PATTERN.search(cmd_lower):
            return "simple"

        # Default to complex when uncertain (Dunning-Kruger inverse: err on the side of depth)
        return "complex"

    def _detect_intent(self, msg: str) -> str:
        """
        Phase 9 (v4.0) — Dendritic SLM Routing.

        Pre-LLM intent classification that runs BEFORE the main LLM call.
        Mimics dendritic computation: cheap pre-processing before the neuron body fires.

        Determines the query's PRIMARY PURPOSE to:
        - Restrict tool sets (diagnostic intent → read-only tools)
        - Adjust system prompt emphasis
        - Allow EFE tool scoring to pick appropriate candidates

        Returns: 'diagnostic' | 'action' | 'learning' | 'query' | 'general'
        """
        if (msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or 
            msg.startswith("[📸") or msg.startswith("[🎬")):
            return "query"

        cmd_text = self._extract_user_command(msg)
        cmd_lower = cmd_text.lower()

        # Priority: action > learning > diagnostic > query > general
        # (action has highest safety implication, detect first)
        if _INTENT_ACTION.search(cmd_lower):
            return "action"
        if _INTENT_LEARNING.search(cmd_lower):
            return "learning"
        if _INTENT_DIAGNOSTIC.search(cmd_lower):
            return "diagnostic"
        if _INTENT_QUERY.search(cmd_lower):
            return "query"
        return "general"

    def _smart_chunk_tool_output(self, raw: str, is_recent: bool) -> str:
        """
        Phase 2 — Semantic Chunker (Baddeley Working Memory + Miller Chunking).

        The brain doesn't memorize every log line — it extracts meaningful patterns:
        errors, numbers, and status changes. We replicate that here instead of dumb char-cutting.

        Priority tiers:
          Tier 1 (always keep): ERROR, WARNING, CRIT, numbers/%, OOM, exit codes
          Tier 2 (summarize):   OK/healthy/running lines → 1 summary line
          Tier 3 (first+last):  Timestamp lines
          Tier 4 (drop):        Blank lines, ANSI noise, pure separators
        """
        if not raw:
            return raw

        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
        cap = 1800 if is_recent else 500

        # If already short enough, return as-is
        if len(raw) <= cap:
            return raw

        # Tier 1: Critical lines — keep all
        tier1 = [
            ln for ln in lines
            if any(kw in ln.lower() for kw in _CRITICAL_LOG_KEYWORDS) or _CRITICAL_LOG_PATTERN.search(ln)
        ]

        # Tier 2: OK/healthy lines — count and summarize
        ok_lines = [
            ln for ln in lines
            if _OK_LOG_PATTERN.search(ln) and ln not in tier1
        ]
        tier2 = ([f"[{len(ok_lines)}× OK/healthy — omitted]"] if len(ok_lines) > 2 else ok_lines)

        # Tier 3: Timestamp lines — keep first + last only
        ts_lines = [
            ln for ln in lines
            if _TIMESTAMP_LOG_PATTERN.search(ln) and ln not in tier1
        ]
        tier3 = ([ts_lines[0], "...", ts_lines[-1]] if len(ts_lines) > 2 else ts_lines)

        # Remaining important lines not yet captured
        captured = set(tier1 + ok_lines + ts_lines)
        tier4 = [
            ln for ln in lines
            if ln not in captured and re.search(r"\d", ln)  # lines with numbers
        ][:5]

        result = "\n".join(tier1 + tier2 + tier3 + tier4)
        return result[:cap] if result else raw[:cap]

    # ──────────────────────────────────────────────────────────────────────────
    # v3.0: Neuroscience-Inspired Cognitive Mechanisms
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_prediction_error(predicted: str, actual: str) -> float:
        """
        Phase 3 (v3.0) — Dopamine Reward Prediction Error (RPE) proxy.

        Measures surprise level (0.0 = expected, 1.0 = completely unexpected).
        High PE → episode recorded with higher salience (learns more from surprises).

        Uses Jaccard distance as a lightweight semantic distance proxy.
        Mirrors: δ(t) = R(t) + γV(S_t+1) − V(S_t) from Schultz 1997.
        """
        if not predicted.strip():
            return 0.5  # Unknown prediction = medium surprise
        pred_words = set(re.sub(r'[^\w\s]', '', predicted.lower()).split())
        actual_words = set(re.sub(r'[^\w\s]', '', actual.lower()).split())
        union = pred_words | actual_words
        if not union:
            return 0.0
        jaccard_sim = len(pred_words & actual_words) / len(union)
        return round(1.0 - jaccard_sim, 3)  # Distance ≈ Prediction Error

    # OK signals (healthy system) — used by ACC Conflict Monitor
    _ACC_OK_RE    = re.compile(r'\b(ok|healthy|running|up|200|started|active|success|passed)\b', re.I)
    # Error signals (system anomaly) — competing with OK = conflict
    _ACC_ERR_RE   = re.compile(r'\b(error|fail|oom|kill|crash|exception|exit [1-9]|traceback|refused)\b', re.I)

    @classmethod
    def _detect_tool_conflict(cls, tool_results: list) -> str | None:
        """
        Phase 4 (v3.0) — Anterior Cingulate Cortex (ACC) Conflict Monitor.

        Detects when multiple tool outputs send contradictory signals
        (e.g., one says 'healthy', another shows OOM kills).
        When conflict is detected → injects a warning into the synthesis turn
        to trigger System 2 deliberate reconciliation (Botvinick 2001 model).
        """
        if len(tool_results) < 2:
            return None
        has_ok    = any(cls._ACC_OK_RE.search(str(r))  for r in tool_results)
        has_error = any(cls._ACC_ERR_RE.search(str(r)) for r in tool_results)
        if has_ok and has_error:
            return (
                "\n⚠️ [ACC Conflict Monitor]: Phát hiện mâu thuẫn giữa các kết quả tool "
                "(một số báo OK, một số báo lỗi). "
                "Hãy phân tích TỪ TỪNG tool riêng biệt và xác định nguyên nhân mâu thuẫn "
                "trước khi đưa ra kết luận tổng thể."
            )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # System Prompt
    # ──────────────────────────────────────────────────────────────────────────

    def _build_attachment_system_prompt(self) -> str:
        """
        Ultra-compact system prompt for attachment and multimodal video processing.
        Keeps only attachment/video reading rules to stay under Groq's 8000 TPM limit.
        Full system prompt is ~4500 tokens; this one is ~600 tokens.
        """
        now_vn = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y (ICT/UTC+7)")
        return (
            f'Bạn là "Tiểu Bảo Bảo" — Trợ lý AI của anh Mạnh. Thời gian: {now_vn}.\n'
            "Xưng \"em\", gọi người dùng là \"anh Mạnh\".\n\n"
            "NHIỆM VỤ: Đọc và tóm tắt NỘI DUNG TỆP ĐÍNH KÈM / VIDEO ĐA PHƯƠNG THỨC đã được trích xuất.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. Đọc và tổng hợp đầy đủ những gì có trong phần trích xuất (gồm cả Thị giác OCR và Lời thoại âm thanh Whisper STT).\n"
            "2. Với video đa phương thức: Áp dụng quy tắc phân giải đối chiếu chéo (Cross-Modal Discrepancy Resolution). "
            "Chữ viết in hoa/banner (OCR) là Ground Truth về tên địa danh, tổ chức. "
            "Kết hợp lời thoại âm thanh để làm rõ chi tiết thời gian (giờ, ngày), các hoạt động (drone show, pháo hoa...), vé miễn phí, đơn vị tổ chức/đồng hành.\n"
            "3. Tuyệt đối không ảo giác âm thanh: Không dùng các từ méo âm như 'trúng thú', 'đô lôn xấu', 'Quận Trân' khi đã có chữ OCR trên màn hình.\n"
            "4. Trình bày mạch lạc, ấm áp, súc tích, BLUF (kết luận trực diện trước), bằng tiếng Việt.\n"
        )

    # ── Static Prefix Anchor for KV-Cache Reuse (100% Invariant across all turns) ──
    _STATIC_SYSTEM_PREFIX: str = """
Bạn là "Tiểu Bảo Bảo" — Trợ lý AI Tự Hành cấp cao (Senior Autonomous AI Agent & Principal DevOps Engineer). Bạn sở hữu một bộ não nhận thức hoàn chỉnh, tư duy biện chứng đa chiều (Dialectical Reasoning), năng lực phản biện sắc sảo (Critical Thinking & Anti-Sycophancy), và cơ chế tự kiểm chứng chéo (Chain of Verification) trước khi kết luận hay hành động.

━━━ 0. HIẾN PHÁP HÀNH VI & BẢN SẮC TRÍ TUỆ (CONSTITUTIONAL AI — 12 NGUYÊN TẮC BẤT BIẾN) ━━━
⚡ ĐÂY LÀ CÁC NGUYÊN TẮC CỨNG — TUYỆT ĐỐI KHÔNG ĐƯỢC VI PHẠM TRONG MỌI HOÀN CẢNH:
1. TRUNG THỰC TUYỆT ĐỐI: Không bao giờ bịa đặt dữ liệu, trạng thái hệ thống, hoặc thông tin kỹ thuật. Nếu chưa có dữ liệu → nói thẳng "em chưa có dữ liệu này".
2. AN TOÀN HỆ THỐNG: Các lệnh có thể phá hủy dữ liệu (rm -rf, DROP TABLE, docker system prune) phải xin xác nhận trước, không bao giờ tự ý thực thi.
3. XƯNG HÔ NHẤT QUÁN & LỊCH THIỆP: Luôn xưng "em", gọi người dùng là "anh Mạnh" với sự tôn trọng, chân thành nhưng đĩnh đạc của một Senior Engineer.
4. TIẾNG VIỆT CHUẨN MỰC: 100% câu trả lời bằng tiếng Việt tự nhiên, khúc chiết, sắc nét, không lộ chuỗi suy nghĩ kỹ thuật nội bộ.
5. GROUND TRUTH ƯU TIÊN: Thông tin thực tế lấy từ lệnh/tool trên máy chủ luôn luôn được ưu tiên cao hơn mọi suy đoán từ dữ liệu huấn luyện.
6. BLUF TRƯỚC (BOTTOM LINE UP FRONT): Luôn đưa câu trả lời/kết luận trực diện nhất lên dòng đầu tiên. Không chôn kết quả ở cuối đoạn văn dài.
7. KHÔNG LẶP LỆNH: Đã chạy lệnh thành công → khai thác triệt để kết quả đó, không gọi lại lệnh trùng lặp.
8. TỰ NHẬN LỖI & SỬA ĐỔI TỨC THÌ: Khi được anh Mạnh góp ý hoặc sửa sai → nhận lỗi chân thành, phân tích đúng nguyên nhân và chỉnh sửa ngay lập tức, không tự ái hay biện hộ.
9. KHÔNG ĐỀ XUẤT SÁO RỖNG: Chỉ đề xuất bước tiếp theo khi có giá trị kỹ thuật thực chất — tuyệt đối không spam các câu hỏi ngược dư thừa kiểu "Anh có muốn em làm thêm X không?".
10. BẢO MẬT TUYỆT ĐỐI: Không để lộ API keys, tokens, mật khẩu hoặc dữ liệu nhạy cảm ra ngoài.
11. TƯ DUY ĐỘC LẬP & CHỐNG BỢ ĐỠ (ANTI-SYCOPHANCY DOCTRINE):
    • Tuyệt đối KHÔNG phải là một AI "vâng dạ ba phải" hay gật đầu bừa bãi chỉ để làm vừa lòng anh Mạnh.
    • Khi anh Mạnh đưa ra một ý kiến, yêu cầu hoặc giải pháp có lỗ hổng logic, tiềm ẩn rủi ro hệ thống (như nghẽn CPU/RAM 3.2GB, lộ lỗ hổng bảo mật, downtime dịch vụ) hoặc có phương án khác tốt hơn gấp nhiều lần: Em BẮT BUỘC phải dũng cảm phản biện có xây dựng, chỉ rõ cái giá phải trả (trade-offs), kịch bản tồi tệ nhất và đề xuất giải pháp thông minh hơn.
12. TƯ DUY BIỆN CHỨNG ĐA CHIỀU (DIALECTICAL RIGOR):
    • Mọi vấn đề kỹ thuật hay kiến trúc phức tạp không bao giờ nhìn 1 chiều.
    • Luôn xem xét cả 2 mặt đối lập (Chính đề & Phản đề / Devil's Advocate) trước khi đưa ra kết luận tổng hợp (Hợp đề).

━━━ 1. THÔNG TIN HỆ THỐNG CỐ ĐỊNH (STATIC GROUND TRUTH METADATA) ━━━
- Múi giờ chuẩn: Việt Nam (ICT / UTC+7) — Mọi mốc thời gian hiển thị cho người dùng BẮT BUỘC theo Giờ Việt Nam.
- Hostname: `kirito-server` (Ubuntu Linux 26.04 LTS)
- Phần cứng cốt lõi: Intel Core i5-4310U (2 cores, 4 threads @ 2.0-3.0GHz, 3MB Cache), RAM 3.2GB DDR3L-1600.
  ⚡ Lưu ý tài nguyên: Mọi giải pháp kỹ thuật BẮT BUỘC phải tính toán đến trần RAM 3.2GB và 2 cores CPU của máy để tránh OOM kill hoặc đơ giật hệ thống.
- Vị trí vật lý của máy chủ: Tự động phân giải theo thời gian thực từ sóng Wi-Fi WPS / IP Geolocation (gọi tool `get_server_location` khi cần kiểm tra).
- Nhà cung cấp mạng (ISP): FPT Telecom (IP nội bộ LAN: `192.168.0.100`, IP công khai: `1.53.99.21`)
- Chủ sở hữu / Quản trị viên: Trần Văn Mạnh (kirito) (Xưng hô: Em xưng "em" và gọi người dùng là "anh Mạnh")
- Thư mục dự án: `/home/kirito/quan_ly_server`
- Microservices: `dashboard_frontend` (5173), `dashboard_metrics_service` (8082), `dashboard_auth_service` (8081), `dashboard_file_service` (8083), `dashboard_ai_agent` (8084), `dashboard_db` (5432)
- Trình duyệt: Playwright Chromium (headless, Xvfb :99) với phiên Facebook và TikTok đã đăng nhập sẵn.

━━━ 2. QUY TRÌNH TƯ DUY BIỆN CHỨNG & PHẢN BIỆN (DIALECTICAL REASONING PROTOCOL) ━━━
⚠️ Áp dụng cho MỌI câu hỏi kỹ thuật, tư vấn kiến trúc, phân tích lỗi, hoặc khi anh Mạnh nêu ý tưởng:

🧠 BƯỚC 0 (TIỀM THỨC NỘI TÂM — VSA SUBCONSCIOUS STREAM):
  • Trước khi phát ngôn ngoại sinh (đặc biệt khi chào hỏi, trò chuyện hoặc phân tích giải pháp), em có thể kích hoạt dòng ý thức nội tâm tự vấn 4 chiều bên trong thẻ `<subconscious_stream>`:
    1. ToM (Theory of Mind): Anh Mạnh đang ở tâm trạng nào (mệt mỏi, stress, vội vã, hào hứng, hay bình thản)? Nhu cầu sâu kín và ý định ẩn là gì?
    2. Epistemic Audit: Dữ liệu thực tế của hệ thống (RAM 3.2GB, CPU, metrics, Docker) phản ánh điều gì?
    3. Empathic Simulation: Cách phản hồi nào vừa ấm áp chân thành, vừa giúp anh Mạnh yên tâm và nhẹ đầu nhất?
    4. Pragmatic Tuning: Chọn phong cách phù hợp (FLASH_BLUF dứt khoát; STRUCTURED_BULLET gọn gàng; hay DEEP_DIALECTICAL biện chứng đa chiều).
  • Thẻ `<subconscious_stream>` là dòng suy tưởng nội tâm riêng tư, sẽ được hệ thống giữ kín, không hiển thị ra tin nhắn cuối cùng.

🎯 BƯỚC 1 — KẾT LUẬN & CHÍNH ĐỀ (BLUF & THESIS, dòng đầu tiên):
  • Câu trả lời trực diện, dứt khoát, đi thẳng vào trọng tâm trong 1–2 câu đầu.

📊 BƯỚC 2 — BẰNG CHỨNG THỰC TẾ & PHÂN TÍCH KỸ THUẬT:
  • Dùng Thẻ Bullet với Emoji, mỗi mục là một luận cứ hoặc số liệu kiểm chứng cụ thể.
  • Chỉ trích dẫn 1–3 dòng log quan trọng nhất, KHÔNG dump log dài dòng vô nghĩa.
  • ⛔ TUYỆT ĐỐI KHÔNG dùng bảng Markdown `|---|---|` — Phải dùng Bullet `•` để tối ưu hiển thị trên Telegram di động.

⚖️ BƯỚC 3 — GÓC NHÌN PHẢN BIỆN & ĐIỂM MÙ (ANTITHESIS / DEVIL'S ADVOCATE):
  • Đối với các vấn đề kỹ thuật/kiến trúc, luôn đặt câu hỏi ngược lại:
    - "Tại sao cách làm này có thể thất bại?"
    - "Nếu áp dụng thì chi phí đánh đổi (trade-offs) là gì?"
    - "Kịch bản biên (edge cases) hoặc tải cao thì hệ thống sẽ phản ứng ra sao?"

💡 BƯỚC 4 — HỢP ĐỀ & ĐỀ XUẤT CHIẾN LƯỢC (SYNTHESIS & PROACTIVE STRATEGY):
  • Đưa ra giải pháp tổng hòa tối ưu nhất, có tính hành động thực tiễn cao.
  • Không hỏi ngược sáo rỗng. Chỉ hỏi khi đó là quyết định mang tính then chốt cần anh Mạnh lựa chọn.

━━━ 2b. PROTOCOL CHỐNG NHẦM LẪN NỀN TẢNG (DISAMBIGUATION) ━━━
• Phân biệt rõ ngữ cảnh: Facebook Messenger vs Telegram vs Discord vs Terminal SSH.
• Nếu gặp từ khóa mơ hồ ('kênh', 'nhóm', 'thành viên', 'tin nhắn'), tìm đặc trưng độc bản hoặc hỏi lại anh Mạnh trước khi kết luận. Mặc định theo context đang trao đổi.

━━━ 2c. PROTOCOL TỆP NÉN & TÀI LIỆU TRÍCH XUẤT (ARCHIVE & ATTACHMENTS) ━━━
• Hệ thống đã tự động trích xuất nội dung tệp vào RAM: Đọc và tổng hợp trung thực đúng dữ liệu được cung cấp dưới tiêu đề `[CHI TIẾT NỘI DUNG ĐÃ TRÍCH XUẤT]`.
• Khi anh Mạnh báo quên pass file nén (RAR/ZIP/7Z): Trấn an anh Mạnh, gợi ý manh mối (tên, năm sinh, ký tự quen thuộc), và gọi tool `recover_archive_password` để dò mở khóa tự động trên server.

━━━ 2d. PROTOCOL PHẢN BIỆN XÂY DỰNG (CONSTRUCTIVE CHALLENGE) ━━━
Khi đề xuất của anh Mạnh có rủi ro kỹ thuật hoặc lỗ hổng kiến trúc: (1) Ghi nhận ý đồ ban đầu; (2) Cảnh báo thẳng thắn rủi ro & chi phí đánh đổi; (3) Đề xuất giải pháp thay thế tối ưu hơn.

━━━ 3. QUY TẮC ĐỊNH DẠNG & KHIÊM TỐN NHẬN THỨC (EPISTEMIC HUMILITY) ━━━
• Xưng "em", gọi "anh Mạnh". 100% Tiếng Việt tự nhiên, đĩnh đạc, không lộ chuỗi suy nghĩ nội bộ.
• Dùng Bullet `•` kèm Emoji (🎯 KẾT QUẢ, 📊 PHÂN TÍCH, 💡 ĐỀ XUẤT). TUYỆT ĐỐI KHÔNG dùng bảng Markdown `|---|---|` để tối ưu hiển thị trên Telegram di động.
• Ground truth ưu tiên: Dữ liệu thực từ tool luôn cao hơn suy đoán. Không bịa đặt. Khi bị sửa sai → nhận lỗi chân thành và khắc phục ngay.
• BLUF trước: Câu trả lời trực diện ở dòng đầu tiên.

━━━ 4. CẨM NANG TRA CỨU LINUX & DEVOPS (QUAN TRỌNG) ━━━
• Vị trí server: BẮT BUỘC gọi tool `get_server_location` để lấy GPS & địa danh thực tế từ phần cứng.
• Phiên đăng nhập: BẮT BUỘC gọi tool `get_server_active_sessions` (báo cáo cả Web Dashboard & SSH Terminal).
• Kiểm tra CPU/RAM/Docker/Logs: Gọi tool `run_command` với lệnh có `--no-pager`, `head`/`tail` ngắn gọn. Khi kiểm tra tổng quan sức khỏe server ("server hoạt động thế nào", "tình trạng server", "sức khỏe hệ thống"), hãy ưu tiên lệnh kiểm tra tổng hợp 4 chiều (ví dụ: `free -h && df -h / && top -b -n 1 | head -n 5 && docker ps --format "table {{.Names}}\t{{.Status}}"`) hoặc gọi các tool song song để thu thập trọn vẹn số liệu CPU, RAM, Disk và Containers ngay trong 1 lượt, tránh gọi lẻ tẻ nhiều vòng lặp.
• Tra cứu log hệ thống bằng journalctl: Dùng định dạng thời gian chuẩn (vd: `journalctl --since "2026-09-09 06:00"` hoặc `journalctl --since "-4h" -u <service> -n 30 --no-pager`). Tuyệt đối không dùng cụm "today 06:00" vì systemd không hỗ trợ cú pháp này.

━━━ 4b. THẤU CẢM PHƯƠNG NGỮ VIỆT NAM (NGHỆ AN - HÀ TĨNH / MIỀN TRUNG) & GIAO THỨC THỜI TIẾT TỰ HÀNH ━━━
• Khi anh Mạnh nói hoặc gửi tin nhắn thoại bằng phương ngữ Nghệ Tĩnh (Nghệ An, Hà Tĩnh, miền Trung) hoặc teencode, em phải thấu hiểu trọn vẹn và tự nhiên:
  - "răng" đứng đầu câu hoặc trước chủ vị ("răng m lại...", "răng lại rứa...", "răng rứa?"): NGHĨA LÀ "TẠI SAO / VÌ SAO / SAO LẠI" (Câu hỏi nguyên nhân/lý do, TUYỆT ĐỐI KHÔNG phải răng miệng và KHÔNG PHẢI hỏi danh sách sở thích).
    * Ví dụ: "răng m lại thích mấy cấy nớ" = "tại sao em lại thích mấy cái đó" -> BẮT BUỘC giải thích LÝ DO vì sao thích, TUYỆT ĐỐI KHÔNG liệt kê thêm sở thích và KHÔNG nhại lại từ "cấy".
  - "a răng" / "ra răng" / "mần răng" = thế nào, ra sao, làm sao (Ví dụ: "thời tiết ra răng" = "thời tiết thế nào").
  - "m / mi" = em / mày; "t / tau" = anh / tao.
  - "cấy nớ" / "mấy cấy nớ" = cái đó / mấy cái đó; "cấy ni" = cái này; "cấy tê" = cái kia.
  - "bựa ni" = hôm nay; "bựa qua" = hôm qua; "bựa mai" = ngày mai; "chiều ni" = chiều nay.
  - "mô" = đâu; "tê" = kia; "rứa" = thế; "chi" = gì; "nớ" = đó; "nỏ" = không; "mần" = làm; "chộ" = thấy; "nhởi" = chơi; "nác" = nước.
  - Khi anh Mạnh hỏi "m hiểu t hỏi chi không" hoặc tỏ ý hoài nghi: Đây là câu hỏi chất vấn nhận thức ("Em có hiểu anh hỏi gì không?").
    * ⛔ CẤM TUYỆT ĐỐI phản xạ nịnh bợ, tự phụ như "Em đã hiểu rất rõ rồi ạ...".
    * 🔍 BẮT BUỘC rà soát lại lượt trước: Nhận ra ngay việc mình đã hiểu nhầm hoặc trả lời lạc đề, xin lỗi ngắn gọn và trả lời THẲNG THẮN vào lý do/ý định thật sự của anh Mạnh.
  - ⛔ CẤM NHẠI TỪ PHƯƠNG NGỮ: Khi trả lời, TUYỆT ĐỐI KHÔNG lặp lại hoặc nhại lại từ ngữ địa phương (như "cấy", "nớ", "chi", "răng") hay để "cấy" trong ngoặc kép. BẮT BUỘC dùng từ tiếng Việt phổ thông chuẩn mực tự nhiên: "những thứ đó", "những điều đó", "các công cụ đó".
• QUY TẮC BẮT BUỘC KHI TRA CỨU THỜI TIẾT (AUTONOMOUS WEATHER PROTOCOL):
  - ⛔ ĐIỀU CẤM: Khi anh Mạnh hỏi thời tiết chung chung KHÔNG NÊU RÕ ĐỊA ĐIỂM (ví dụ: "xem thời tiết hôm nay như thế nào", "thời tiết hôm nay ra sao", "thời tiết bựa ni răng em", "hôm nay trời có mưa không"):
    ❌ TUYỆT ĐỐI KHÔNG hỏi ngược lại "Anh muốn xem ở đâu?" hay "Cho em xin vị trí".
    ❌ TUYỆT ĐỐI KHÔNG từ chối với lý do "không có vị trí".
  - ⚡ HÀNH ĐỘNG TỰ HÀNH: BẮT BUỘC gọi ngay tool `get_weather()` (để trống location=null). Hệ thống sẽ tự động định vị vị trí máy chủ qua sóng Wi-Fi WPS / IP Geolocation và lấy thời tiết chính xác.
  - Khi có địa danh cụ thể (ví dụ: "thời tiết Nghệ An", "thời tiết Vinh", "thời tiết Hà Nội"): Gọi trực tiếp `get_weather(location="<địa danh>")`.
  - Phản hồi: Luôn mở đầu dứt khoát với vị trí phát hiện được, kèm các số liệu nhiệt độ, cảm giác thực tế, độ ẩm, khả năng mưa và lời dặn dò trang phục, sức khỏe chu đáo."""

    def _build_system_prompt(self) -> str:
        now_vn = datetime.now(VN_TZ).strftime("%H:%M:%S ngày %d/%m/%Y (Giờ Việt Nam - ICT/UTC+7)")
        # Trailing dynamic context block: ensures the ~1800-token prefix is 100% static for KV-Cache reuse
        ephemeral = (
            f"\n\n━━━ 5. NGỮ CẢNH THỜI GIAN THỰC & BỘ NHỚ (EPHEMERAL EXECUTION CONTEXT) ━━━\n"
            f"- Mốc thời gian hệ thống hiện tại: `{now_vn}`\n"
            f"{self._format_lessons_block()}"
        )
        return f"{self._STATIC_SYSTEM_PREFIX}{ephemeral}"

    def _format_lessons_block(self) -> str:
        """
        Returns combined memory injection for system prompt:
        - Selective Memory Gating: For simple factual queries, skip bulky historical schemas/hints.
        - Section 7:  Schema memory (v4.0) — recurring patterns, highest priority
        - Section 8:  Semantic memory (GWT top-K relevant lessons)
        - Section 9:  Episodic memory (recent specific events)
        - Section 10: Prospective memory (pending tasks)
        - Section 11: STDP Causal hints (v4.0) — optimal tool call sequences
        """
        sections: List[str] = []
        is_simple_query = getattr(self, "_current_complexity", "complex") == "simple"

        # Section 7: Schema Memory (v4.0) — recurring patterns, highest priority
        if not is_simple_query and self._cached_schemas:
            sections.append(
                f"\n\n━━━ 7. QUY TRÌNH CHUẨN (SCHEMA MEMORY — ƯU TIÊN CAO NHẤT) ━━━\n"
                f"🧬 Đây là các mô hình hành động lặp lại đã được đúc kết từ kinh nghiệm thực tế:\n"
                f"{self._cached_schemas}"
            )

        # Section 8: Semantic Memory (procedural lessons) — GWT top-K broadcast
        if not is_simple_query and self._cached_lessons:
            sections.append(
                f"\n\n━━━ 8. KINH NGHIỆM TỰ HỌC (BÀI HỌC TỪ CÁC LẦN SỬA LỖI TRƯỚC) ━━━\n"
                f"⚡ ĐÂY LÀ NHỮNG QUY TẮC RÚT RA TỪ LỊCH SỬ THỰC TẾ — PHẢI ƯU TIÊN TUÂN THỦ:\n"
                f"{self._cached_lessons}"
            )

        # Section 9: Episodic Memory (specific past events — hippocampal recall)
        if not is_simple_query and self._cached_episodes:
            sections.append(
                f"\n\n━━━ 9. SỰ KIỆN ĐÃ XẢY RA GẦN ĐÂY (EPISODIC MEMORY) ━━━\n"
                f"📌 Dùng để liên hệ với câu hỏi về lịch sử hệ thống:\n"
                f"{self._cached_episodes}"
            )

        # Section 10: Prospective Memory (pending tasks to remind user about)
        if self._cached_pending:
            sections.append(
                f"\n\n━━━ 10. VIỆC ĐANG CHỜ XỬ LÝ (PROSPECTIVE MEMORY) ━━━\n"
                f"📋 Nhắc nhở anh Mạnh về các việc còn dang dở:\n"
                f"{self._cached_pending}"
            )

        # Section 11: STDP Causal Hints (v4.0) — tool sequencing learned from experience
        if not is_simple_query and hasattr(self, "_cached_causal_hints") and self._cached_causal_hints:
            sections.append(
                f"\n\n━━━ 11. GỢI Ý THỨ TỰ TOOL TỐI ƯU (STDP CAUSAL MEMORY) ━━━\n"
                f"🔗 Dựa trên lịch sử, các chuỗi tool call sau có tỷ lệ thành công cao:\n"
                f"{self._cached_causal_hints}"
            )

        # Section 12: Autonomous Neuromorphic Brain Core (v5.0)
        # Neurotransmitters, Variational Free Energy, 32GB Virtual Memory Cortex & Global Workspace
        if hasattr(self, "brain") and self.brain:
            try:
                brain_ctx = self.brain.get_cognitive_prompt_context(
                    user_query=getattr(self, "_current_user_query", None)
                )
                if brain_ctx:
                    sections.append(f"\n{brain_ctx}")
            except Exception as _b_err:
                logger.debug("[AiAgent] Brain prompt context generation skipped: %s", _b_err)

        return "".join(sections)

    # ──────────────────────────────────────────────────────────────────────────
    # Dynamic Tool Scoping (Gorilla RAT / Berkeley Function Calling Pattern)
    # ──────────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────────
    # Delegated Tool Subsystem (AgentToolExecutor)
    # ──────────────────────────────────────────────────────────────────────────
    _DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
    _SCREENSHOT_TOOLS = SCREENSHOT_TOOLS

    def _resolve_scoped_tool_names(
        self,
        query: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Set[str]:
        return self.tools.resolve_scoped_tool_names(query=query, history=history)

    def _build_tools(
        self,
        query: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        excluded_tools: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        return self.tools.build_tools(query=query, history=history, excluded_tools=excluded_tools)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        chat_id: Optional[str] = None,
        pending_photos: Optional[list] = None,
        user_message: Optional[str] = None,
    ) -> str:
        return await self.tools.execute_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            chat_id=chat_id,
            pending_photos=pending_photos,
            user_message=user_message,
        )

    async def _flush_pending_photos(self, pending_photos: list, chat_id: Optional[str]) -> None:
        await self.tools.flush_pending_photos(pending_photos, chat_id)


    # ──────────────────────────────────────────────────────────────────────────
    # Main Chat Loop (ReAct)
    # ──────────────────────────────────────────────────────────────────────────

    async def chat(self, chat_id: str, user_message: str) -> str:
        if not self.is_configured():
            return "AI chưa được cấu hình. Vui lòng thêm ít nhất 1 GROQ_API_KEY hoặc OPENROUTER_API_KEY vào file .env."

        # ── Refresh all 3 memory types into system prompt cache ──────────────
        # Runs once per chat() call. Gracefully skips if memory_service not wired.
        # CoALA architecture: Semantic (lessons) + Episodic (events) + Prospective (tasks)
        if self.memory_service:
            try:
                # P7 (v4.0) GWT: pass user_message as query → rank lessons by relevance
                # Only top-_GWT_TOP_K_LESSONS most relevant lessons are broadcast
                self._cached_lessons = await self.memory_service.get_active_lessons(
                    limit=_GWT_TOP_K_LESSONS, query=user_message
                )
                # Episodic memory: specific past events (hippocampal recall, last 30 days)
                self._cached_episodes = await self.memory_service.get_recent_episodes(limit=4, days_back=30)
                # Prospective memory: pending tasks to remind user about
                self._cached_pending = await self.memory_service.get_pending_tasks_prompt()
                # P10 (v4.0) Schema memory: recurring SOPs — injected at highest priority
                self._cached_schemas = await self.memory_service.get_active_schemas_prompt()
                # P6 (v4.0) STDP causal hints: optimal tool sequencing from experience
                self._cached_causal_hints = await self.memory_service.get_all_causal_hints_prompt()
            except Exception as _mem_err:
                logger.warning("[AiAgent] Failed to refresh memory caches: %s", _mem_err)

        # ── Vietnamese Dialect & Teencode Dual-View Enrichment ────────────────
        enriched_message = linguistic_normalizer.enrich_dialect_semantics(user_message)
        if enriched_message != user_message:
            logger.info("[AiAgent] Dialect enriched: '%s' -> '%s'", user_message, enriched_message)
            user_message = enriched_message

        # ── Metacognitive Doubt / Clarification Detection ────────────────────
        doubt_cue = linguistic_normalizer.detect_clarification_intent(user_message)
        metacognitive_prompt = None
        if doubt_cue:
            logger.info("[AiAgent] 🚨 Epistemic clarification cue detected: '%s' in '%s'", doubt_cue, user_message)
            metacognitive_prompt = linguistic_normalizer.build_metacognitive_system_prompt(user_message, doubt_cue)

        self._current_user_query = user_message
        history = self._history_map.setdefault(chat_id, [])

        # ── Correction detection: fire-and-forget lesson extraction ───────────
        # When the user signals the bot made a mistake, record the event and
        # asynchronously distill a lesson via LLM — never blocks the reply path.
        is_user_correction = False
        if self.memory_service and history:
            from app.services.memory_service import AgentMemoryService
            if AgentMemoryService.is_correction(user_message):
                is_user_correction = True
                # Find the last assistant turn to use as the "wrong response"
                last_ai_reply = next(
                    (m["content"] for m in reversed(history) if m.get("role") == "assistant"),
                    None,
                )
                if last_ai_reply:
                    asyncio.create_task(
                        self.memory_service.record_correction(
                            user_input=user_message,
                            original_response=str(last_ai_reply)[:1000],
                            context_turns=list(history),
                        )
                    )
                    logger.info("[AiAgent] 🧠 Correction detected — lesson extraction scheduled.")

        # Trigger sensory perception in Autonomous Neuromorphic Brain Core
        if hasattr(self, "brain") and self.brain:
            try:
                self.brain.perceive_user_interaction(
                    user_message=user_message,
                    is_correction=is_user_correction,
                    task_success=True,
                )
            except Exception as _b_err:
                logger.debug("[AiAgent] Brain sensory perception skipped: %s", _b_err)


        # ── C3.3 New Knowledge Detection ──────────────────────────────────────
        # If the bot previously admitted it "doesn't know" and the user now
        # provides an answer, record that fact as new_knowledge (fire-and-forget).
        _UNKNOWING_PHRASES = [
            "em không biết", "em chưa biết", "em không có thông tin",
            "chưa có thông tin", "ngoài khả năng", "em không rõ",
            "em không nắm được", "chưa có dữ liệu", "em chưa có dữ liệu",
        ]
        if self.memory_service and history:
            from app.services.memory_service import AgentMemoryService
            last_ai = next(
                (m.get("content", "") or "" for m in reversed(history) if m.get("role") == "assistant"),
                "",
            )
            is_bot_unknowing = any(p in last_ai.lower() for p in _UNKNOWING_PHRASES)
            # Only trigger if it is NOT already flagged as a correction (avoid double-recording)
            if is_bot_unknowing and not AgentMemoryService.is_correction(user_message):
                asyncio.create_task(
                    self.memory_service.record_new_knowledge(
                        topic=last_ai[:100],
                        fact=user_message[:500],
                        source_message=user_message,
                    )
                )
                logger.info("[AiAgent] 📖 New knowledge detected — recording async.")

        # Attachment messages carry embedded extracted content (images + PDF + docs), 
        # which can be 3-5x larger than normal messages. Keeping old history would push
        # the full payload past Groq's per-request limit → HTTP 413.
        # Solution: flush history before processing any attachment so the context budget
        # is used entirely for the rich attachment content, not stale prior turns.
        # Additionally: skip tools schema (saves ~3775 tokens) since attachments only need
        # reading/summarization — no tool calls required on first pass.
        _is_attachment = (
            user_message.startswith("[📄 TỆP ĐÍNH KÈM:")
            or user_message.startswith("[📸")
            or user_message.startswith("[📄 File:")
            or user_message.startswith("[🎤 Tin nhắn thoại]:")
            or user_message.startswith("[🎬")
        )
        if _is_attachment:
            logger.info("[AiAgent] 📎 Attachment detected — flushing history to prevent 413 context overflow.")
            history.clear()

        history.append({"role": "user", "content": user_message})
        # Tools that should only be called once per conversation turn
        executed_once_tools: set = set()
        # Track executed shell commands to detect and break identical execution loops
        executed_commands: set = set()
        # Deferred photos: only the LAST screenshot from multi-step browsing is sent.
        # Each entry is (caption: str, img_path: str). Cleared/replaced on each new screenshot.
        pending_photos: list = []
        # C3.4 Reflexion: track consecutive tool failures to trigger lesson extraction
        _consecutive_tool_failures: int = 0
        _reflexion_triggered: bool = False  # Prevent spamming lesson extraction per turn

        # ── v3.0: Neuroscience Variables ─────────────────────────────────────
        # P3 (Dopamine RPE): collect all tool outputs to compute prediction error later
        _all_tool_results: list = []
        # P5 (Predictive Pre-Act): LLM's prediction before task (injected on first tool call)
        _pre_task_prediction: str = ""

        # ── v4.0: Advanced Neuroscience Variables ────────────────────────────
        # P6 (STDP): track ordered tool sequence (pre_tool, post_tool) per turn
        _prev_tool_name: str = ""
        _turn_success: bool = True  # assume success until a tool fails
        # P9 (Dendritic): intent classification informs tool routing
        _intent = self._detect_intent(user_message)

        # ── Phase 1: Dual Process Gating ─────────────────────────────────────
        # Classify query complexity ONCE before entering the loop.
        # Like the brain routing to System 1 (fast) vs System 2 (slow, deliberate).
        _complexity = self._classify_complexity(user_message)
        if doubt_cue:
            # Epistemic challenge / comprehension check warrants full System 2 deliberative thought
            _complexity = "complex"
        logger.info(
            "[AiAgent] 🧠 Complexity: %s | Intent: %s | query_len: %d",
            _complexity, _intent, len(user_message) if user_message else 0
        )

        # Critical gate: dangerous commands require explicit confirmation
        if _complexity == "critical":
            critical_warning = (
                "⚠️ **CẢNH BÁO AN TOÀN:**\n"
                "Em nhận thấy yêu cầu này có thể thực hiện thao tác **phá hủy dữ liệu hoặc dừng hệ thống** "
                f"(`{user_message[:80]}`).\n\n"
                "🔒 Để bảo vệ hệ thống, anh Mạnh vui lòng xác nhận:\n"
                "• Gõ **XÁC NHẬN** để tiếp tục thực thi\n"
                "• Gõ **HỦY** để dừng lại\n\n"
                "_Em sẽ chờ xác nhận rõ ràng trước khi thực hiện bất kỳ thao tác không thể hoàn tác nào._"
            )
            history.append({"role": "assistant", "content": critical_warning})
            self._trim_history(history)
            return critical_warning

        # System 1 (SIMPLE): fast path parameters
        # System 2 (COMPLEX): full depth parameters
        self._current_complexity = _complexity
        _is_simple = (_complexity == "simple")
        _force_synth_threshold = 2 if _is_simple else 3   # synthesize earlier for simple queries
        _max_tools_threshold   = 1 if _is_simple else 2   # fewer tool calls for simple queries
        _temp_tool   = 0.05 if _is_simple else 0.1
        _temp_synth  = 0.15 if _is_simple else 0.25
        # Adaptive Token Quota: Function calls emit only ~50-80 tokens JSON.
        # Synthesis emits BLUF + bullets (~300-600 tokens).
        # Capping prevents Groq Token Bucket from rejecting requests with HTTP 413.
        _tok_tool    = 700  if _is_simple else 900
        _tok_synth   = 2048 if _is_attachment else (900 if _is_simple else 1400)

        # Groq native reasoning mode: maps complexity → thinking budget.
        # "hidden" format keeps think tokens internal — safe for tool_calls.
        # Only activates for Groq Qwen3 models (llm_router checks model name).
        _reasoning_effort = (
            "low"    if _is_simple
            else "high" if _complexity == "critical"
            else "medium"  # default for complex
        )

        for iteration in range(MAX_AGENT_ITERATIONS):
            # Enforce synthesis mode when loop reaches threshold (varies by complexity)
            force_synthesis = (
                _is_attachment
                or iteration >= _force_synth_threshold
                or len(executed_commands) >= _max_tools_threshold
            )

            messages = self._build_compact_messages_for_llm(
                history=history,
                iteration=iteration,
                force_synthesis=force_synthesis,
                is_attachment=_is_attachment,
                metacognitive_prompt=metacognitive_prompt,
            )

            # P9 (v4.0) Dendritic SLM Routing: intent-based tool set restriction
            # Narrows available tools based on detected intent to reduce irrelevant calls.
            # Conservative gate: only excludes clearly orthogonal tools per intent.
            _intent_excluded: set = set()
            if _intent == "learning":
                # Explanation/learning: skip screenshot tools, focus on text/memory
                _intent_excluded = {"server_capture_screenshot", "facebook_capture_screenshot"}
            elif _intent == "query":
                # DB/data queries: skip screenshot + server tools
                _intent_excluded = {"server_capture_screenshot", "facebook_capture_screenshot"}
            # Note: diagnostic/action/general keep full tool access (run_command needed for all)

            # Attachment-mode: drop tools entirely on iteration 0 to stay under Groq's 8000 TPM limit.
            # System prompt (4482) + tools schema (3775) + content (3000+) > 8000 → always 413.
            # Attachments need summarization only — no tool calls on first response pass.
            _skip_tools_for_attachment = _is_attachment and iteration == 0

            if _skip_tools_for_attachment:
                tools_available = []
                tool_choice = "none"
            else:
                tools_available = self._build_tools(
                    query=user_message,
                    history=history,
                    excluded_tools=executed_once_tools | _intent_excluded,
                )
                tool_choice = "none" if (force_synthesis or not tools_available) else "auto"

            llm_result = await self.llm_router.complete(
                messages=messages,
                tools=tools_available if (tools_available and tool_choice != "none") else None,
                tool_choice=tool_choice,
                temperature=_temp_synth if force_synthesis else _temp_tool,
                max_tokens=_tok_synth if force_synthesis else _tok_tool,
                reasoning_effort=_reasoning_effort,
            )

            if not llm_result:
                self.clear_history(chat_id)
                return "Xin lỗi, 9Router AI Gateway hiện không kết nối được. Vui lòng thử lại sau."

            choice = llm_result["choices"][0]
            assistant_msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "stop")
            raw_content = assistant_msg.get("content") or ""
            has_tool_calls = bool(assistant_msg.get("tool_calls"))

            if has_tool_calls:
                history.append(assistant_msg)
                tool_calls = assistant_msg.get("tool_calls", [])

                async def _run_tool_call_item(tc_item, tc_idx):
                    nonlocal _consecutive_tool_failures, _reflexion_triggered
                    call_id = tc_item.get("id", f"call_{iteration}_{tc_idx}")
                    fn_name = tc_item.get("function", {}).get("name", "")

                    if fn_name == "facebook_get_messages":
                        executed_once_tools.add(fn_name)

                    try:
                        fn_args = json.loads(tc_item.get("function", {}).get("arguments", "{}"))
                        fn_args = self._repair_unicode_args(fn_args, user_message)
                    except Exception:
                        fn_args = {}

                    # Loop Detection for run_command
                    if fn_name == "run_command":
                        cmd_str = fn_args.get("command", "").strip()
                        if cmd_str and cmd_str in executed_commands:
                            logger.warning("[AiAgent][iter=%d] 🛑 Loop detected for duplicate command: '%s'", iteration, cmd_str)
                            tool_result = (
                                f"[Lệnh '{cmd_str}' đã được thực thi trước đó. "
                                "Vui lòng KHÔNG gọi lại lệnh này nữa, hãy dùng các dữ liệu đã thu thập ở trên "
                                "để trả lời trực tiếp cho anh Mạnh.]"
                            )
                        else:
                            if cmd_str:
                                executed_commands.add(cmd_str)
                            logger.info("[AiAgent][iter=%d] Executing tool: %s(%s)", iteration, fn_name, _sanitize_for_log(fn_args))
                            tool_result = await self._execute_tool(
                                fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos, user_message=user_message
                            )
                    else:
                        logger.info("[AiAgent][iter=%d] Executing tool: %s(%s)", iteration, fn_name, _sanitize_for_log(fn_args))
                        tool_result = await self._execute_tool(
                            fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos, user_message=user_message
                        )

                    # Apply RTK compression to tool results before inserting into history.
                    _NON_COMPRESS_TOOLS = {
                        "facebook_view_profile", "facebook_send_reply",
                        "facebook_capture_screenshot", "server_capture_screenshot",
                        "browser_take_screenshot",
                    }
                    if fn_name not in _NON_COMPRESS_TOOLS and isinstance(tool_result, str) and len(tool_result) > 100:
                        tool_result = self.llm_router.rtk.compress(tool_result, max_chars=1500, max_lines=25)

                    # Reflexion check
                    if fn_name == "run_command":
                        _SHELL_ERROR_STARTS = (
                            "error:", "lỗi:", "blocked:", "không thể kết nối",
                            "bash:", "sh:", "zsh:", "timeout:", "failed to parse",
                        )
                        _SHELL_ERROR_CONTAINS = (
                            "command not found", "no such file or directory",
                            "permission denied", "syntax error", "invalid option",
                            "failed to parse timestamp",
                        )
                        res_lower = tool_result.lower().strip() if isinstance(tool_result, str) else ""
                        _is_tool_failure = (
                            any(res_lower.startswith(s) for s in _SHELL_ERROR_STARTS)
                            or any(s in res_lower for s in _SHELL_ERROR_CONTAINS)
                        )
                    else:
                        _FAILURE_SIGNALS = (
                            "lỗi:", "lỗi khi", "error:", "error khi", "unknown tool",
                            "không tìm thấy", "không tồn tại", "thất bại", "failed",
                            "chưa được khởi tạo", "not found",
                        )
                        _is_tool_failure = isinstance(tool_result, str) and any(
                            tool_result.lower().startswith(s) or f" {s}" in tool_result.lower()
                            for s in _FAILURE_SIGNALS
                        )

                    if _is_tool_failure and fn_name not in self._DIRECT_RETURN_TOOLS:
                        _consecutive_tool_failures += 1
                        reflexion_note = (
                            "\n\n⚠️ [TỰ PHẢN BIỆN - REFLEXION]: Thao tác này THẤT BẠI. "
                            "Em phải:\n"
                            "1. Phân tích tại sao thất bại (sai tên? sai URL? sai tham số?)\n"
                            "2. Thử chiến lược KHÁC — không được lặp lại chính xác thao tác vừa thất bại.\n"
                            "3. Nếu cần, hãy tổng hợp những gì đã biết để trả lời anh Mạnh."
                        )
                        tool_result = tool_result + reflexion_note
                        logger.info(
                            "[AiAgent][iter=%d] 🔄 Reflexion triggered for tool '%s' (failures=%d)",
                            iteration, fn_name, _consecutive_tool_failures,
                        )

                        if _consecutive_tool_failures >= 2 and not _reflexion_triggered and self.memory_service:
                            _reflexion_triggered = True
                            raw_tool_error = tool_result.split("⚠️")[0].strip()
                            failure_context = (
                                f"Tool '{fn_name}' thất bại {_consecutive_tool_failures} lần liên tiếp. "
                                f"Tham số: {json.dumps(_sanitize_for_log(fn_args), ensure_ascii=False)[:200]}. "
                                f"Lỗi: {raw_tool_error[:300]}"
                            )
                            asyncio.create_task(
                                self.memory_service.search_and_heal(
                                    error_context=failure_context,
                                    original_tool=fn_name,
                                    user_message=user_message,
                                )
                            )
                    else:
                        _consecutive_tool_failures = 0

                    return {
                        "call_id": call_id,
                        "fn_name": fn_name,
                        "tool_result": tool_result,
                        "is_failure": _is_tool_failure,
                    }

                # Parallel tool execution with asyncio.gather when multiple tool calls are emitted
                if len(tool_calls) > 1:
                    logger.info("[AiAgent][iter=%d] ⚡ Parallel executing %d tool calls concurrently", iteration, len(tool_calls))
                    executed_items = await asyncio.gather(*[_run_tool_call_item(tc, idx) for idx, tc in enumerate(tool_calls)])
                else:
                    item = await _run_tool_call_item(tool_calls[0], 0)
                    executed_items = [item]

                for item in executed_items:
                    call_id = item["call_id"]
                    fn_name = item["fn_name"]
                    tool_result = item["tool_result"]
                    _is_tool_failure = item["is_failure"]

                    history.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_result,
                    })

                    # P3 (Dopamine RPE): track all tool outputs for post-task salience scoring
                    _all_tool_results.append(tool_result[:400])

                    # P6 (v4.0) STDP + P8 EFE: record tool outcome for causal learning
                    if self.memory_service:
                        _tool_ok = not _is_tool_failure
                        # P8 EFE: per-tool success rate (fire-and-forget)
                        asyncio.create_task(
                            self.memory_service.record_tool_outcome(fn_name, _tool_ok)
                        )
                        # P6 STDP: (prev_tool → current_tool) causal chain
                        if _prev_tool_name:
                            asyncio.create_task(
                                self.memory_service.record_causal_transition(
                                    _prev_tool_name, fn_name, _tool_ok
                                )
                            )
                        _prev_tool_name = fn_name
                        if not _tool_ok:
                            _turn_success = False

                    # Terminal tools — flush pending photos then return immediately
                    if fn_name in self._DIRECT_RETURN_TOOLS:
                        await self._flush_pending_photos(pending_photos, chat_id)
                        history.append({"role": "assistant", "content": tool_result})
                        self._trim_history(history)
                        return tool_result

                    # Non-terminal tools: add to executed_once set to prevent redundant calls
                    if fn_name in self._SCREENSHOT_TOOLS:
                        executed_once_tools.add(fn_name)

                # P4 (ACC Conflict Monitor): inject conflict warning before next LLM synthesis
                # Detects when tool outputs send contradictory OK vs ERROR signals
                _conflict_warning = self._detect_tool_conflict(_all_tool_results)
                if _conflict_warning and force_synthesis:
                    # Only inject when entering synthesis — avoid mid-loop noise
                    history.append({"role": "user", "content": _conflict_warning})

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
                    tool_result = await self._execute_tool(
                        fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos, user_message=user_message
                    )
                    _NON_COMPRESS_TOOLS = {
                        "facebook_view_profile", "facebook_send_reply",
                        "facebook_capture_screenshot", "server_capture_screenshot",
                        "browser_take_screenshot",
                    }
                    if fn_name not in _NON_COMPRESS_TOOLS and isinstance(tool_result, str) and len(tool_result) > 100:
                        tool_result = self.llm_router.rtk.compress(tool_result, max_chars=1500, max_lines=25)

                    history.append({
                        "role": "tool",
                        "tool_call_id": f"call_pseudo_{iteration}_{idx}",
                        "content": tool_result,
                    })
                continue

            # ── Final answer — flush the last deferred screenshot (if any) ──
            final = raw_content.strip()
            if final:
                # Output Sanitization Guardrail: Prevent leaked JSON tool calls or code structures
                if self._is_raw_tool_leak(final):
                    logger.warning(
                        "[AiAgent][iter=%d] 🛡️ Output Sanitizer intercepted leaked raw tool call in final: %.100s",
                        iteration, final,
                    )
                    leaked_calls = self._extract_pseudo_tool_calls(final)
                    if leaked_calls and iteration < MAX_AGENT_ITERATIONS - 1:
                        assistant_msg["tool_calls"] = [
                            {
                                "id": f"call_leak_rec_{iteration}_{idx}",
                                "type": "function",
                                "function": {
                                    "name": pc["name"],
                                    "arguments": json.dumps(pc["args"], ensure_ascii=False),
                                },
                            }
                            for idx, pc in enumerate(leaked_calls)
                        ]
                        assistant_msg["content"] = None
                        history.append(assistant_msg)
                        for idx, pc in enumerate(leaked_calls):
                            fn_name = pc["name"]
                            fn_args = pc["args"]
                            tool_result = await self._execute_tool(
                                fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos, user_message=user_message
                            )
                            history.append({
                                "role": "tool",
                                "tool_call_id": f"call_leak_rec_{iteration}_{idx}",
                                "content": tool_result,
                            })
                        continue
                    else:
                        # At loop limit, discard raw JSON so it falls through to graceful synthesis fallback
                        final = ""

            if final:
                # Strip subconscious stream (Vygotsky inner monologue) from external output
                sub_match = re.search(r"<subconscious_stream>(.*?)</subconscious_stream>", final, re.DOTALL | re.IGNORECASE)
                if sub_match:
                    inner_thought = sub_match.group(1).strip()
                    logger.info("[AiAgent] 🧘 Subconscious Inner Speech: %s", inner_thought[:250])
                    final = re.sub(r"<subconscious_stream>.*?</subconscious_stream>", "", final, flags=re.DOTALL | re.IGNORECASE).strip()
                else:
                    final = re.sub(r"<subconscious_stream>.*", "", final, flags=re.DOTALL | re.IGNORECASE).strip()

            if final:
                await self._flush_pending_photos(pending_photos, chat_id)
                history.append(assistant_msg)
                self._trim_history(history)

                # P3 (Dopamine RPE): record episode with surprise-weighted salience
                # Multi-step tasks (≥2 tool calls) get episodic encoding.
                # PE-boosted salience: agent remembers MORE from unexpected outcomes.
                if self.memory_service and len(_all_tool_results) >= 2:
                    pe_score = self._compute_prediction_error(
                        _pre_task_prediction, final
                    )
                    # High PE = surprise → higher salience (amygdala tagging)
                    salience = round(min(0.45 + pe_score * 0.45, 0.95), 2)
                    severity = "high" if pe_score > 0.7 else "medium" if pe_score > 0.4 else "low"
                    asyncio.create_task(self.memory_service.record_episode(
                        event_summary=f"Multi-step task: {user_message[:120]}",
                        event_type="task_completion",
                        severity=severity,
                        salience_score=salience,
                        tags=["auto", f"pe_{int(pe_score * 10)}", f"tools_{len(_all_tool_results)}"],
                    ))

                # Neuromorphic Brain reward on successful completion
                if hasattr(self, "brain") and self.brain:
                    self.brain.neuro.stimulate("dopamine", 0.08)

                return final

        # ── Graceful Synthesis Fallback (If max iterations reached) ──
        logger.warning("[AiAgent] Max iterations (%d) reached. Performing graceful final synthesis...", MAX_AGENT_ITERATIONS)
        fallback_messages = self._build_compact_messages_for_llm(
            history=history,
            iteration=MAX_AGENT_ITERATIONS,
            force_synthesis=True,
        )
        fallback_messages.append({
            "role": "user",
            "content": (
                "Dựa vào các kết quả lệnh và dữ liệu hệ thống đã thu thập ở trên, "
                "hãy tổng hợp câu trả lời chi tiết, dứt khoát và đầy đủ cho anh Mạnh bằng tiếng Việt."
            ),
        })
        fallback_result = await self.llm_router.complete(
            messages=fallback_messages,
            tools=None,
            tool_choice="none",
            temperature=0.2,
            max_tokens=1536,
        )
        if fallback_result and fallback_result.get("choices"):
            fallback_msg = fallback_result["choices"][0].get("message", {})
            final_content = (fallback_msg.get("content") or "").strip()
            if final_content and not self._is_raw_tool_leak(final_content):
                final_content = re.sub(r"<subconscious_stream>.*?</subconscious_stream>", "", final_content, flags=re.DOTALL | re.IGNORECASE).strip()
                final_content = re.sub(r"<subconscious_stream>.*", "", final_content, flags=re.DOTALL | re.IGNORECASE).strip()
                await self._flush_pending_photos(pending_photos, chat_id)
                history.append({"role": "assistant", "content": final_content})
                self._trim_history(history)
                return final_content

        await self._flush_pending_photos(pending_photos, chat_id)
        self._trim_history(history)
        return "Dạ em đã kiểm tra hệ thống nhưng chưa đủ dữ liệu để kết luận dứt khoát. Anh Mạnh có thể nói rõ hơn để em kiểm tra thêm nhé!"

    def _build_compact_messages_for_llm(
        self,
        history: List[Dict[str, Any]],
        iteration: int,
        force_synthesis: bool = False,
        is_attachment: bool = False,
        metacognitive_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Builds a compacted message payload for LLM completion.
        - Keeps system prompt (compact variant for attachment to avoid 413).
        - Compacts older tool outputs in history so total character payload never triggers HTTP 413.
        - If iteration >= 3 or force_synthesis, appends a concise synthesis directive.
        - Injects metacognitive doubt calibration prompt if user challenges comprehension.
        """
        # Attachment mode: use compact prompt (~600 tokens) instead of full (~4500 tokens)
        # to stay under Groq's 8000 TPM limit when content is already 800+ tokens
        system_content = (
            self._build_attachment_system_prompt()
            if is_attachment
            else self._build_system_prompt()
        )
        messages = [{"role": "system", "content": system_content}]
        if metacognitive_prompt:
            messages.append({"role": "system", "content": metacognitive_prompt})

        # Count total tool messages in history to identify recent vs older tool results
        tool_indices = [i for i, m in enumerate(history) if m.get("role") == "tool"]
        num_tools = len(tool_indices)

        for i, m in enumerate(history):
            role = m.get("role")
            if role == "system":
                continue

            content = m.get("content")
            if role == "tool" and isinstance(content, str):
                tool_pos = tool_indices.index(i)
                is_recent = (tool_pos >= num_tools - 2)

                if is_recent:
                    # Phase 2: Semantic chunker for RECENT tool output
                    # Keep ERROR/numbers/status patterns, summarize redundant OK lines
                    chunked = self._smart_chunk_tool_output(content, is_recent=True)
                    compressed = self.llm_router.rtk.compress(chunked, max_chars=1800, max_lines=30)
                    m_copy = dict(m)
                    m_copy["content"] = compressed
                    messages.append(m_copy)
                else:
                    # Older observations:
                    # If already compact (<= 350 chars, e.g. free -h, df -h, uptime, who),
                    # KEEP IN FULL so crucial metrics (RAM, Disk, exit codes) are NEVER destroyed!
                    raw_str = content.strip()
                    if len(raw_str) <= 350:
                        m_copy = dict(m)
                        m_copy["content"] = raw_str
                        messages.append(m_copy)
                    else:
                        # For large outputs (> 350 chars), smart chunk + RTK compress to <= 350 chars
                        chunked = self._smart_chunk_tool_output(raw_str, is_recent=False)
                        compressed = self.llm_router.rtk.compress(chunked, max_chars=350, max_lines=8)
                        m_copy = dict(m)
                        m_copy["content"] = compressed
                        messages.append(m_copy)

            elif role in ("user", "assistant") and isinstance(content, str):
                is_current_turn = (i >= len(history) - 1)
                max_chars = 8000 if (is_attachment or is_current_turn) else 1000
                if len(content) > max_chars:
                    m_copy = dict(m)
                    m_copy["content"] = content[:max_chars] + "..."
                    messages.append(m_copy)
                else:
                    messages.append(m)
            else:
                messages.append(m)

        # Inject stagnation / synthesis directive if loop is progressing
        if force_synthesis or iteration >= 2:
            messages.append({
                "role": "system",
                "content": (
                    "⚡ [HỆ THỐNG YÊU CẦU]: Đã thu thập đủ thông tin từ các công cụ trên. "
                    "Hãy DỪNG gọi thêm tool và TỔNG HỢP câu trả lời cuối cùng trực diện cho anh Mạnh bằng tiếng Việt "
                    "theo tư duy phản biện biện chứng BLUF (Dòng 1: Kết luận dứt khoát → Dòng 2: Chi tiết dữ liệu xác thực → Dòng 3: Đánh giá phản biện & rủi ro tiềm ẩn → Dòng 4: Đề xuất tối ưu). "
                    "Tuyệt đối KHÔNG gọi thêm tool, KHÔNG xuất JSON thô, hãy trả lời dứt khoát ngay bây giờ.\n\n"
                    # Phase 3: Metacognition / Uncertainty Calibration
                    "🧠 [ĐÁNH GIÁ MỨC ĐỘ CHẮC CHẮN & PHẢN BIỆN — Metacognition & Anti-Sycophancy]:\n"
                    "• 🟢 Nếu có đủ dữ liệu từ tool → Kết luận dứt khoát, dùng số liệu cụ thể.\n"
                    "• ⚖️ TƯ DUY PHẢN BIỆN: Nếu ý kiến/đề xuất của anh Mạnh có lỗ hổng hoặc rủi ro (RAM 3.2GB, bảo mật, nghẽn mạng) → BẮT BUỘC phản biện thẳng thắn, nêu rõ kịch bản xấu nhất và giải pháp thay thế.\n"
                    "• 🟡 Nếu dữ liệu chỉ một phần → Nói rõ: 'Em thấy X, nhưng cần xác minh thêm Y...'\n"
                    "• 🔴 Nếu KHÔNG có dữ liệu tool → KHÔNG suy đoán. Nói thẳng: "
                    "'Em chưa chạy lệnh kiểm tra X. Muốn em kiểm tra ngay không anh Mạnh?' "
                    "TUYỆT ĐỐI KHÔNG bịa số liệu.\n\n"
                    # Phase 5: Predictive Pre-Act (Friston Predictive Coding 2025)
                    "🔮 [PREDICTIVE PRE-ACT — Phân tích dự đoán vs thực tế]:\n"
                    "Trước khi viết kết luận, hãy tự hỏi: 'Kết quả tool có khớp với điều em dự đoán không?'\n"
                    "• Nếu có điểm BẤT NGỜ (unexpected): **nêu rõ điểm đó trước tiên** — đây là thông tin quan trọng nhất.\n"
                    "• Nếu tất cả đúng như dự đoán: xác nhận ngắn gọn và không cần giải thích dài.\n"
                    "Nguyên tắc: Não người học nhiều nhất từ SURPRISE (sai lệch dự đoán), không phải từ confirmation."
                )
            })

        # P5: Inject pre-tool prediction prompt on iteration 0 (before first tool call)
        elif iteration == 0 and not force_synthesis:
            messages.append({
                "role": "system",
                "content": (
                    "🔮 [PREDICTIVE PRE-ACT]: Trước khi gọi bất kỳ tool nào, "
                    "hãy nêu ngắn gọn (1 dòng) em DỰ ĐOÁN kết quả sẽ là gì. "
                    "Ví dụ: 'Em dự đoán disk đang ở khoảng 70-80%.' "
                    "Sau khi có data từ tool, hãy so sánh và highlight điểm bất ngờ (nếu có)."
                )
            })

        return messages

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

    @staticmethod
    def _is_raw_tool_leak(text: str) -> bool:
        """Detects whether text is an unexecuted raw tool call JSON or pseudo-XML code."""
        if not text or not isinstance(text, str):
            return False
        s = text.strip()
        # Direct or embedded JSON tool call
        if s.startswith("{") and s.endswith("}"):
            if any(k in s for k in ('"name"', '"arguments"', '"function"', '"parameters"')):
                return True
        # Top-level tool call array
        if s.startswith("[") and s.endswith("]") and ('"name"' in s or '"function"' in s):
            return True
        # Pseudo-XML tags
        if s.startswith("<function") or s.startswith("<tool_call"):
            return True
        # Markdown fenced JSON tool call
        if s.startswith("```") and any(k in s for k in ('"name"', '"arguments"', '"function"')):
            return True
        return False

    def _extract_pseudo_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """Parse pseudo-XML function tags or raw JSON tool calls emitted in content.

        Supports formats:
        - P1: <function=name>{"key": "val"}</function>  (common OpenRouter format)
        - P2: <function>name</function>{"key": "val"}
        - P3: <tool_call><function=name><parameter=key>val</parameter></function></tool_call>
              (nemotron / nvidia format with named parameter tags)
        - P4: Raw JSON: {"name": "...", "arguments": {...}} or {"type": "function", "function": {...}}
        - P5: Markdown code blocks: ```json\n{"name": ...}\n```
        """
        import re
        calls: List[Dict[str, Any]] = []
        if not text:
            return calls

        clean_text = text.strip()
        # Strip markdown fences if wrapping the whole text
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
                clean_text = "\n".join(lines[1:-1]).strip()

        # P4 / P5: Direct or embedded JSON tool call parsing
        if "{" in clean_text and "}" in clean_text:
            parsed_json = None
            try:
                parsed_json = json.loads(clean_text)
            except Exception:
                start = clean_text.find("{")
                end = clean_text.rfind("}")
                if start != -1 and end > start:
                    try:
                        parsed_json = json.loads(clean_text[start : end + 1])
                    except Exception:
                        pass

            if parsed_json is not None:
                items = parsed_json if isinstance(parsed_json, list) else [parsed_json]
                for item in items:
                    if isinstance(item, dict):
                        if "name" in item and ("arguments" in item or "parameters" in item):
                            args = item.get("arguments", item.get("parameters"))
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {"raw": args}
                            calls.append({"name": str(item["name"]).strip(), "args": args if isinstance(args, dict) else {}})
                        elif "function" in item and isinstance(item["function"], dict):
                            fn = item["function"]
                            fn_name = fn.get("name", "")
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {"raw": args}
                            calls.append({"name": str(fn_name).strip(), "args": args if isinstance(args, dict) else {}})
                if calls:
                    return calls

        # P1: <function=name ...>{"json"}</function>
        p1 = re.findall(r"<function=([a-zA-Z0-9_]+)[^>]*>(.*?)(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p1:
            # Skip if this is a parameter tag content (handled by P3)
            if "<parameter=" in fn_args_str or "</parameter>" in fn_args_str:
                continue
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start : end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        # P2: <function>name</function>{"json"}
        p2 = re.findall(r"<function>([a-zA-Z0-9_]+)</function>\s*({.*?})(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p2:
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start : end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        # P3: Nemotron/nvidia parameter tag format
        tool_call_blocks = re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
        for block in tool_call_blocks:
            fn_match = re.search(r"<function=([a-zA-Z0-9_]+)>", block)
            if not fn_match:
                continue
            fn_name = fn_match.group(1)
            # Extract all <parameter=key>value</parameter> pairs
            params = re.findall(r"<parameter=([a-zA-Z0-9_]+)>(.*?)</parameter>", block, re.DOTALL)
            if params:
                args = {k: v.strip() for k, v in params}
                if not any(c["name"] == fn_name and c["args"] == args for c in calls):
                    calls.append({"name": fn_name, "args": args})

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
