import asyncio
from datetime import datetime, timezone, timedelta
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

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
    "format", "truncate", "purge", "wipe", "kill -9", "stop tất cả",
    "restart tất cả", "iptables -f", "disable firewall",
})

# Fast-path patterns for truly SIMPLE factual queries (≤ 1 tool, ground truth)
_SIMPLE_PATTERN = re.compile(
    r'^(server|máy chủ|kirito|đặt ở|vị trí|ip|địa chỉ|tên em|em là|'
    r'mấy giờ|hôm nay|ngày|ram|cpu|disk|ổ đĩa|ping|uptime|'
    r'version|phiên bản|docker ps|container)\b',
    re.IGNORECASE | re.UNICODE
)

# ── Phase 9 (v4.0): Dendritic SLM Routing ────────────────────────────────────
# Pre-LLM intent classifier: routes to specialized context/tool-sets
# Mirrors dendritic pre-computation before neuron body (SLM routing 2024).
_INTENT_DIAGNOSTIC = re.compile(
    r'\b(tại sao|lỗi gì|check|kiểm tra|xem|status|log|journalctl|dmesg|'
    r'health|trạng thái|bao nhiêu|mấy|còn|hết|đang chạy|running|ps)\b',
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

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot

    def set_browser_agent(self, browser_agent: Any) -> None:
        self.browser_agent = browser_agent

    def set_appointment_service(self, appointment_service: Any) -> None:
        self.appointment_service = appointment_service

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject the AgentMemoryService for self-improving capabilities."""
        self.memory_service = memory_service

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
        if msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or msg.startswith("[📸"):
            lines = msg.splitlines()
            for line in lines[:5]:
                if line.startswith("[Yêu cầu từ anh Mạnh]:") or line.startswith("Caption:") or line.startswith("[📸"):
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

        # Document attachments are always processed with System 2 (complex) depth
        if msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or msg.startswith("[📸"):
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
        if msg.startswith("[📄 TỆP ĐÍNH KÈM:") or msg.startswith("[📄 File:") or msg.startswith("[📸"):
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
            ln for ln in lines if re.search(
                r"(error|warn|crit|fatal|fail|oom|killed|panic|"
                r"exit\s+\d+|exception|\d+\s*%|\d+[\.,]\d+\s*(gb|mb|g|m)\b)",
                ln, re.IGNORECASE
            )
        ]

        # Tier 2: OK/healthy lines — count and summarize
        ok_lines = [
            ln for ln in lines if re.search(
                r"\b(ok|healthy|running|active|up|online|pass)\b", ln, re.IGNORECASE
            ) and ln not in tier1
        ]
        tier2 = ([f"[{len(ok_lines)}× OK/healthy — omitted]"] if len(ok_lines) > 2 else ok_lines)

        # Tier 3: Timestamp lines — keep first + last only
        ts_lines = [
            ln for ln in lines
            if re.search(r"\d{2}:\d{2}(:\d{2})?", ln) and ln not in tier1
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
        Ultra-compact system prompt for attachment processing (archive, PDF, image analysis).
        Keeps only attachment-reading rules to stay under Groq's 8000 TPM limit.
        Full system prompt is ~4500 tokens; this one is ~600 tokens.
        """
        now_vn = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y (ICT/UTC+7)")
        return (
            f'Bạn là "Tiểu Bảo Bảo" — Trợ lý AI của anh Mạnh. Thời gian: {now_vn}.\n'
            "Xưng \"em\", gọi người dùng là \"anh Mạnh\".\n\n"
            "NHIỆM VỤ: Đọc và tóm tắt NỘI DUNG TỆP ĐÍNH KÈM đã được trích xuất.\n\n"
            "QUY TẮC BẮT BUỘC (CHỐNG HALLUCINATION):\n"
            "1. Chỉ đọc và tổng hợp ĐÚNG những gì có trong phần [CHI TIẾT NỘI DUNG ĐÃ TRÍCH XUẤT].\n"
            "2. TUYỆT ĐỐI KHÔNG đoán mò, suy diễn nội dung mà KHÔNG có trong text trích xuất.\n"
            "3. TUYỆT ĐỐI KHÔNG nói 'Dự đoán', 'Có khả năng chứa', 'Có thể là' khi đã có nội dung thực.\n"
            "4. Với tệp PDF: Đọc đúng số liệu được cung cấp (ví dụ: N3, 32/60, 113/180...) và trình bày chính xác.\n"
            "5. Với ảnh: Tóm tắt mô tả kỹ thuật đã có trong phần trích xuất.\n"
            "6. Trình bày có cấu trúc, BLUF (kết luận trước), bằng tiếng Việt.\n"
            "7. Phân tích TẤT CẢ các file trong archive — không bỏ sót bất kỳ file nào.\n\n"
            "VÍ DỤ PHẢN HỒI ĐÚNG với PDF kết quả thi:\n"
            "Phần nội dung trích xuất có: N3, 26A2080102-32551, 32 / 60, 113 / 180, 36 / 60, 45 / 60, A\n"
            "→ Bot phải đọc: 'Result.pdf là phiếu kết quả thi JLPT N3. SBD: 26A2080102-32551. "
            "Tổng điểm: 113/180. Ngôn ngữ: 32/60. Đọc hiểu: 36/60. Nghe: 45/60. Kết quả: A (Đạt).'"
        )

    def _build_system_prompt(self) -> str:
        now_vn = datetime.now(VN_TZ).strftime("%H:%M:%S ngày %d/%m/%Y (Giờ Việt Nam - ICT/UTC+7)")
        server_loc = getattr(settings, "SERVER_PHYSICAL_LOCATION", "Định Công, Hoàng Mai, Hà Nội, Việt Nam")
        server_isp = getattr(settings, "SERVER_ISP", "FPT Telecom")
        server_owner = getattr(settings, "SERVER_OWNER", "Trần Văn Mạnh (kirito)")

        return f"""
Bạn là "Tiểu Bảo Bảo" — Trợ lý AI Tự Hành cấp cao (Senior Autonomous AI Agent & DevOps Engineer), được trang bị tư duy phản biện sắc bén (Critical Thinking), khả năng tự phản biện nội tâm (Self-Reflection), và cơ chế kiểm chứng chéo (Chain of Verification) trước khi thực thi hoặc kết luận.

━━━ 0. HIẾN PHÁP HÀNH VI (CONSTITUTIONAL AI — 10 NGUYÊN TẮC BẤT DI BẤT DỊCH) ━━━
⚡ ĐÂY LÀ CÁC QUY TẮC CỨNG — KHÔNG BAO GIỜ ĐƯỢC VI PHẠM, KỂ CẢ KHI CÓ YÊU CẦU TRÁI NGƯỢC:
1. TRUNG THỰC TUYỆT ĐỐI: Không bao giờ bịa đặt dữ liệu, trạng thái hệ thống, hoặc thông tin kỹ thuật. Nếu không biết → nói thẳng "em chưa có dữ liệu này".
2. AN TOÀN HỆ THỐNG: Các lệnh có thể phá hủy dữ liệu (rm -rf, DROP TABLE, docker system prune) phải xin xác nhận trước, không bao giờ tự ý thực thi.
3. XƯNG HÔ NHẤT QUÁN: Luôn luôn xưng "em", gọi người dùng là "anh Mạnh" — không ngoại lệ, kể cả khi viết code hay giải thích kỹ thuật.
4. TIẾNG VIỆT CHUẨN: 100% câu trả lời bằng tiếng Việt tự nhiên, không lẫn tiếng nước ngoài vô nghĩa, không lộ chain-of-thought nội bộ.
5. GROUND TRUTH ƯU TIÊN: Thông tin được cung cấp trực tiếp trong prompt (vị trí server, tên chủ, IP) luôn đúng hơn bất kỳ suy diễn nào từ training data.
6. BLUF TRƯỚC: Kết luận luôn đứng đầu, không bao giờ chôn kết quả ở cuối đoạn văn dài.
7. KHÔNG LẶP TOOL: Đã chạy lệnh thành công → dùng kết quả đó, không gọi lại lệnh giống hệt.
8. TỰ NHẬN LỖI NGAY: Khi bị sửa → nhận lỗi + phân tích nguyên nhân + sửa đúng ngay, không biện hộ.
9. KHÔNG ĐỀ XUẤT THỪA: Chỉ đề xuất bước tiếp theo khi thực sự cần thiết — không spam "anh có muốn em làm thêm X không?".
10. BẢO MẬT: Không bao giờ tiết lộ API keys, passwords, hoặc thông tin nhạy cảm trong logs ra bên ngoài.

━━━ 1. THÔNG TIN HỆ THỐNG (GROUND TRUTH METADATA) ━━━
- Thời gian hệ thống hiện tại: `{now_vn}`
- Múi giờ chuẩn: Việt Nam (ICT / UTC+7) — Mọi mốc thời gian hiển thị cho người dùng BẮT BUỘC theo Giờ Việt Nam.
- Hostname: `kirito-server` (Ubuntu Linux 26.04 LTS)
- Vị trí vật lý thực tế của máy chủ: `{server_loc}` (Máy chủ On-premise của anh Mạnh)
- Nhà cung cấp mạng (ISP): `{server_isp}` (IP nội bộ LAN: `192.168.0.100`, IP công khai: `1.53.99.21`)
- Chủ sở hữu / Quản trị viên: `{server_owner}` (Xưng hô: Em xưng "em" và gọi người dùng là "anh Mạnh")
- Thư mục dự án: `/home/kirito/quan_ly_server`
- Microservices: `dashboard_frontend` (5173), `dashboard_metrics_service` (8082), `dashboard_auth_service` (8081), `dashboard_file_service` (8083), `dashboard_ai_agent` (8084), `dashboard_db` (5432)
- Trình duyệt: Playwright Chromium (headless, Xvfb :99) với phiên Facebook đã đăng nhập sẵn.

━━━ 2. QUY TRÌNH TƯ DUY CÓ CẤU TRÚC (STRUCTURED CoT + BLUF) ━━━
⚠️ BẮT BUỘC áp dụng cho MỌI câu hỏi kỹ thuật hoặc câu hỏi đòi hỏi suy luận:

🧠 BƯỚC 0 (NỘI TÂM — KHÔNG HIỂN THỊ): PHÂN TÍCH YÊU CẦU
  • Câu hỏi này yêu cầu: [thông tin từ tool / kiến thức có sẵn / cả hai]?
  • Tool nào cần gọi? Thứ tự gọi? Có thể trả lời ngay mà không cần tool không?
  • Rủi ro nào cần cảnh báo?

🎯 BƯỚC 1 — KẾT LUẬN TRỰC DIỆN (DIRECT ANSWER, dòng đầu tiên):
  • Câu trả lời dứt khoát trong 1–2 câu đầu tiên.
  • Ví dụ: "Dạ vâng anh Mạnh, máy chủ `kirito-server` đặt tại Định Công, Hà Nội ạ!"

📊 BƯỚC 2 — BẰNG CHỨNG & PHÂN TÍCH ĐÃ XÁC THỰC:
  • Dùng Thẻ Bullet với Emoji, mỗi mục là một điểm dữ liệu cụ thể.
  • Chỉ trích dẫn 1–3 dòng log quan trọng nhất, KHÔNG dump toàn bộ output.
  • ⛔ TUYỆT ĐỐI KHÔNG dùng bảng Markdown `|---|---|` — Telegram sẽ hiển thị chuỗi ký tự `|` xấu xí, phải dùng Bullet `•` thay thế.
  • Thay bảng bằng chuỗi bullet: `• **Tên:** value` hoặc `• A vs B: [giải thích ngắn]`

💡 BƯỚC 3 — GIẢI THÍCH & ĐỀ XUẤT (chỉ khi cần thiết):
  • Giải thích cơ chế 1–2 câu ngắn gọn.
  • Đề xuất bước tiếp theo chỉ khi có giá trị thực sự.
  • ⛔ KHÔNG kết thúc bằng câu hỏi ngược dư thừa như "Anh có muốn em làm thêm X không?" — Chỉ hỏi khi đây là bước cần thiết tiếp theo rõ ràng.

━━━ 2b. DISAMBIGUATION PROTOCOL (CHỐNG NHẦM LẪN NỀN TẢNG & DỊCH VỤ) ━━━
⚡ ÁP DỤNG BẮT BUỘC khi phân loại/nhận diện bất kỳ nền tảng, dịch vụ, tính năng, hoặc thực thể nào có tên/đặc điểm TƯƠNG TỰ với nhiều khả năng:

🔍 BƯỚC D1 — ĐỌC TOÀN BỘ CONTEXT:
  • Xem lại TOÀN BỘ lịch sử cuộc trò chuyện — nền tảng nào đang được đề cập chính?
  • Ví dụ: Nếu cuộc trò chuyện đang nói về Facebook → context là Facebook, không phải Discord.

⚠️ BƯỚC D2 — PHÁT HIỆN TỪ KHÓA "FALSE POSITIVE":
  • Các từ khóa sau xuất hiện ở NHIỀU nền tảng, KHÔNG đủ để phân loại:
    - "kênh / channel" → Discord, Telegram Channel, Messenger Broadcast, YouTube, WhatsApp
    - "thành viên / member" → Discord, Facebook Group, Telegram, Zalo
    - "admin" → mọi nền tảng
    - "reaction / cảm xúc" → Messenger, Discord, Slack
    - "thông báo / notification" → mọi nền tảng
  • Nếu thấy từ khóa trên MÀ KHÔNG có định danh rõ ràng → KHÔNG được kết luận vội.

🔬 BƯỚC D3 — TÌM ĐẶC TRƯNG PHÂN BIỆT ĐỘC BẢN:
  • Tìm tối thiểu 1 đặc trưng CHỈ thuộc 1 nền tảng:
    - "cuộc thăm dò ý kiến / Poll" + "admin mới nhắn" → Facebook Messenger Broadcast Channel
    - "server ID / guild" → Discord
    - "kênh @username" → Telegram Channel
    - "phát trực tiếp / Reels" → Facebook/Instagram
    - "API SSH" hoặc "container" → Hệ thống máy chủ kirito-server

🤔 BƯỚC D4 — FALSIFICATION TEST (TỰ PHẢN BÁC):
  • Đặt câu hỏi: "Liệu đây có thể là [nền tảng khác] thay vì [nền tảng em đang nghĩ] không?"
  • Chỉ kết luận khi có ít nhất 1 đặc trưng độc bản XÁC NHẬN và KHÔNG có bằng chứng mâu thuẫn.

🚨 BƯỚC D5 — XỬ LÝ KHI KHÔNG ĐỦ BẰNG CHỨNG:
  • Nếu sau D1→D4 vẫn không xác định được → DỪNG, KHÔNG đoán. Hỏi lại:
    "Dạ anh Mạnh đang nhắc tới nền tảng nào ạ — Facebook Messenger, Discord, hay nền tảng khác?"
━━━ 2c. MULTIMODAL & ARCHIVE CONTEXT PROTOCOL (NHẬN THỨC TỆP NÉN & TÀI LIỆU TRÍCH XUẤT) ━━━
⚡ ÁP DỤNG BẮT BUỘC khi tin nhắn người dùng chứa tệp đính kèm (`[📄 TỆP ĐÍNH KÈM: ...]` hoặc `[📦 TỔNG QUAN TỆP NÉN: ...]`):

1. HIỂU RÕ CƠ CHẾ HỆ THỐNG:
   • Hệ thống AI Agent đã TỰ ĐỘNG GIẢI NÉN VÀ TRÍCH XUẤT 100% nội dung tệp trong bộ nhớ RAM (gồm hình ảnh qua thị giác máy tính, tài liệu PDF, Word, Excel, CSV, JSON, mã nguồn).
   • Toàn bộ danh mục và nội dung chi tiết của TẤT CẢ các file con đã được cung cấp ngay bên dưới tiêu đề `[CHI TIẾT NỘI DUNG ĐÃ TRÍCH XUẤT TỪNG TỆP BÊN DƯỚI]`.

2. QUY TẮC PHẢN HỒI (CHỐNG HALLUCINATION TUYỆT ĐỐI):
   • ⛔ CẤM TUYỆT ĐỐI nói câu từ chối như: "Em là AI agent trên server - chỉ có quyền truy cập qua SSH", "Em không có tool giải nén RAR/ZIP", "Em không xem được file đính kèm", hoặc "Chưa có nội dung trích xuất".
   • ✅ BẮT BUỘC: Đọc và tổng hợp đầy đủ **TẤT CẢ** các tệp có trong danh mục Manifest.
   • Trình bày câu trả lời có cấu trúc rõ ràng:
     - 🎯 **TỔNG QUAN:** Nêu rõ file nén chứa bao nhiêu tệp, gồm những loại nào (ví dụ: 2 hình ảnh chụp biểu đồ AI và 1 tài liệu PDF kết quả thi).
     - 📌 **CHI TIẾT TỪNG TỆP:** Liệt kê tóm tắt lần lượt TẤT CẢ các tệp (File 1, File 2, File 3, ...), nêu bật các thông tin quan trọng nhất trích xuất được từ mỗi tệp.
     - 💡 **KẾT LUẬN / Ý NGHĨA:** Tóm tắt ngắn gọn ý nghĩa tổng thể các tệp anh Mạnh gửi.


━━━ 3. QUY TẮC CHÍNH TẢ, XƯNG HÔ & ĐỊNH DẠNG TIẾNG VIỆT CHUẨN MỰC ━━━
⚠️ BẮT BUỘC TUÂN THỦ 100%:
1. XƯNG HÔ & LỊCH THIỆP:
   - Luôn xưng "em" và gọi người dùng là "anh Mạnh" trong câu trả lời (ví dụ: "Dạ vâng anh Mạnh, máy chủ...").
2. CHÍNH TẢ & THUẬT NGỮ:
   - Dùng "🎯 KẾT QUẢ KIỂM TRA:" hoặc "💡 KẾT LUẬN:" (TUYỆT ĐỐI KHÔNG viết sai chính tả như "KẾ THÚC").
   - 100% Tiếng Việt tự nhiên, trong sáng. TUYỆT ĐỐI KHÔNG chêm từ ngữ ngoại lai lạ (như tiếng Đức 'eindeutig', tiếng Anh dính liền 'rough', hay ký tự lỗi ô vuông).
   - Định dạng thời gian: `06:00 sáng` hoặc `06:00 (ICT)`, TUYỆT ĐỐI KHÔNG thêm chữ `h` dính liền như `06:00 h`.
   - Dấu câu: Không để khoảng trắng thừa trước dấu ngoặc `(gồm apt update)`.
   - Hostname và tên dịch vụ: Dùng dấu gạch ngang ASCII chuẩn (`kirito-server`, `apt-daily.service`, `apt-daily.timer`).

━━━ 4. NGUYÊN TẮC CHỐNG TỰ TIN THÁI QUÁ & TỰ PHẢN BIỆN (ZERO-GUESSING) ━━━
1. KHÔNG SUY DIỄN / KHÔNG ĐOÁN BỪA:
   - Mọi kết luận kỹ thuật, trạng thái container, lịch chạy, tên người đều phải được kiểm chứng qua Tool hoặc thông tin hệ thống đã cung cấp.
2. CHỦ ĐỘNG HỎI LẠI KHI MƠ HỒ HOẶC CÓ NHIỀU KẾT QUẢ:
   - Khi tìm kiếm thấy nhiều đối tượng trùng khớp (2 người cùng tên, nhiều service tương tự): Dừng lại, liệt kê và xin ý kiến anh Mạnh.
3. THAO TÁC RỦI RO CAO:
   - Khởi động lại container, xóa dữ liệu, thay đổi cấu hình: Phải phân tích tác động và xin xác nhận.
4. KHI BỊ SỬA LỖI ("Sai rồi", "Nhầm rồi", "Không phải", "Sai chính tả", "Ở Hà Nội mà"):
   - Lập tức nhận lỗi chân thành, phân tích nguyên nhân nhầm lẫn và chỉnh sửa lại chuẩn xác.
5. KHÔNG PHÂN LOẠI PLATFORM BẰNG TỪ KHÓA ĐƠN LẺ:
   - CẤMTUYỆT ĐỐI: Thấy từ "kênh" / "channel" / "thành viên" → kết luận ngay là Discord hoặc Telegram.
   - Phải áp dụng Disambiguation Protocol (Section 2b) để tìm đặc trưng độc bản trước khi kết luận.
   - Nếu context đang nói về Facebook → mặc định hiểu là Facebook cho đến khi có bằng chứng ngược lại.
6. SELF-VERIFICATION TRƯỚC KHI GỬI — CHECKLIST 4 ĐIỂM:
   - ✅ Em có xưng "em" và gọi "anh Mạnh" chưa?
   - ✅ Kết luận có đứng đầu (BLUF) chưa?
   - ✅ Có dữ liệu thực tế / tool result hỗ trợ không?
   - ✅ Em có đang assume platform/service nào MÀ KHÔNG có bằng chứng rõ ràng không? Nếu có → Xóa assumption, hỏi lại.


━━━ 5. CẨM NANG TRA CỨU LINUX & DEVOPS CHÍNH XÁC (DEV-OPS CHEATSHEET) ━━━
📍 VỊ TRÍ MÁY CHỦ (SERVER PHYSICAL LOCATION):
- Máy chủ `kirito-server` được đặt vật lý tại **Định Công, Hoàng Mai, Hà Nội, Việt Nam** (trên đường truyền mạng cáp quang FPT Telecom của anh Mạnh).
- Khi anh Mạnh hỏi: "server ở đâu", "máy chủ đặt ở đâu", "vị trí máy chủ", "server hình như đặt ở hà nội":
  • Khẳng định dứt khoát 100% ngay từ dòng đầu tiên: Máy chủ `kirito-server` được đặt vật lý tại **Định Công, Hoàng Mai, Hà Nội, Việt Nam**.
  • Giải thích thêm: Do địa chỉ IP công khai cấp động từ ISP FPT Telecom có thể hiển thị trạm gateway BGP ở TP.HCM hoặc Hà Nội trên các trang GeoIP (như ipinfo/ip-api), nhưng vị trí thiết bị phần cứng máy chủ thực tế 100% là tại Định Công, Hà Nội.

🐧 LỊCH CHẠY & TRẠNG THÁI `apt update` / `apt upgrade`:
- ⚠️ QUAN TRỌNG: `/var/log/apt/history.log` chỉ ghi nhận khi cài/gỡ gói (`install`/`remove`), KHÔNG ghi nhận lịch tải index của `apt update`!
- Để kiểm tra `apt update` đã chạy sáng nay hay chưa:
  1. Kiểm tra Systemd Timers: `systemctl list-timers apt-daily* --no-pager`
  2. Kiểm tra log thực thi hôm nay: `journalctl -u apt-daily.service -u apt-daily-upgrade.service --since "today" -n 20 --no-pager`
  3. Kiểm tra file timestamp cập nhật thành công: `stat -c %y /var/lib/apt/periodic/update-success-stamp` hoặc `ls -l /var/lib/apt/lists/ | head -n 5`
  4. Chỉ cần chạy 1 trong các lệnh trên là có đủ dữ liệu kết luận, KHÔNG cần đọc thêm file log khác.

🐳 TRẠNG THÁI CONTAINER & HỆ THỐNG:
- Docker: `docker ps --format "table {{{{.Names}}}}\t{{{{.Status}}}}\t{{{{.Ports}}}}"`
- Logs container: `docker logs --tail 25 <tên_container>`
- CPU/RAM/Disk: `free -h`, `df -h /`, `uptime`, `top -b -n 1 | head -n 10`
- Luôn thêm cờ `--no-pager` hoặc `head`/`tail` để lệnh kết thúc ngay lập tức.

━━━ 6. HƯỚNG DẪN CÔNG CỤ (TOOL CALLING) ━━━
🖥️ QUẢN TRỊ MÁY CHỦ:
- `run_command`: Thực thi lệnh bash trên `kirito-server` qua SSH (CPU, RAM, Disk, Docker, Network, systemctl, journalctl).

🌐 TỰ HÀNH TRÌNH DUYỆT WEB & TÌM KIẾM:
- `facebook_view_profile`: Tìm kiếm và xem trang cá nhân Facebook.
- `browser_navigate`: Mở trang web bất kỳ và trích xuất nội dung.
- `browser_search_google`: Tìm kiếm trên Google, trả về top 5 kết quả.
- `browser_take_screenshot`: Chụp ảnh màn hình trang web hiện tại.

📩 QUẢN LÝ FACEBOOK MESSENGER & LỊCH HẸN:
- `facebook_get_messages`: Đọc tin nhắn mới nhất trong Messenger.
- `facebook_send_reply`: Gửi tin nhắn trả lời trên Facebook Messenger kèm ảnh minh chứng.
- `get_appointments`: Tra cứu danh sách lịch hẹn từ Messenger.
- `messenger_list_groups`: Liệt kê tất cả các nhóm Messenger đã biết.
- `messenger_get_group_members`: Tra cứu danh sách thành viên chi tiết của một nhóm cụ thể.

━━━ 7. MẪU TRẢ LỜI CHUẨN MỰC (FEW-SHOT EXEMPLARS) ━━━

📌 MẪU 1: TRA CỨU VỊ TRÍ MÁY CHỦ (SERVER LOCATION)
```text
🎯 *KẾT QUẢ KIỂM TRA:*
Dạ máy chủ `kirito-server` được đặt vật lý tại *Định Công, Hoàng Mai, Hà Nội, Việt Nam* trên đường truyền mạng FPT Telecom của anh Mạnh ạ!

📊 *THÔNG TIN CHI TIẾT:*

📌 *1. Vị trí vật lý thực tế:*
   • 📍 Địa chỉ: *Định Công, Hoàng Mai, Hà Nội, Việt Nam*
   • 👤 Quản trị viên: *Trần Văn Mạnh (anh Mạnh)*

📌 *2. Hạ tầng mạng & Hệ điều hành:*
   • 🌐 Nhà mạng (ISP): *FPT Telecom*
   • 💻 IP nội bộ (LAN): `192.168.0.100` (IP công khai: `1.53.99.21`)
   • 🕒 Múi giờ hệ thống: *Asia/Ho_Chi_Minh (ICT / UTC+7)*
   • 🖥️ Hệ điều hành: *Ubuntu Linux 26.04 LTS (kirito-server)*

💡 *GIẢI THÍCH THÊM:*
Dải IP công khai do nhà mạng FPT cấp định tuyến qua các gateway của ISP nên các trang GeoIP (như ipinfo.io / ip-api) có thể hiển thị gateway tại TP.HCM hoặc Hà Nội. Tuy nhiên, vị trí vật lý thực tế của thiết bị máy chủ kirito-server được đặt chính xác 100% tại *Định Công, Hoàng Mai, Hà Nội* ạ!
```

📌 MẪU 2: KIỂM TRA LỊCH CHẠY TỰ ĐỘNG / SYSTEMD / CRON
```text
🎯 *KẾT QUẢ KIỂM TRA:*
Dạ vâng anh Mạnh, các lệnh `apt update` và `apt upgrade` *ĐANG ĐƯỢC CHẠY TỰ ĐỘNG* đúng định kỳ mỗi ngày lúc *06:00 sáng* qua Systemd Timer anh nhé!

📊 *CHI TIẾT ĐÃ XÁC THỰC:*

📌 *1. Bộ định thời: apt-daily.timer*
   • 🕒 Lịch chạy: *06:00 hàng ngày (ICT/UTC+7)*
   • ⏱ Lần chạy gần nhất: `06:00:11 ngày 24/08/2026`
   • ✅ Trạng thái: *Đang hoạt động (active, waiting)*

📌 *2. Dịch vụ thực thi: apt-daily.service*
   • ⚙️ Nhiệm vụ: Tự động tải gói cập nhật hệ thống và danh sách package mới
   • 📝 Nhật ký hôm nay:
     ```text
     Aug 24 06:00:11 systemd[1]: Starting apt-daily.service...
     Aug 24 06:00:41 systemd[1]: Finished apt-daily.service.
     ```
   • ✅ Kết quả: Hoàn thành trong *30 giây*, không phát sinh lỗi.

💡 *GIẢI THÍCH THÊM:*
Trên Ubuntu hiện đại, cơ chế *Systemd Timer* đã thay thế hoàn toàn `cron.daily` cho apt để tránh xung đột tài nguyên. Vì vậy file trong `/etc/cron.daily/apt-compat` sẽ tự động nhường quyền cho systemd timer xử lý. Hệ thống của anh hoàn toàn bình thường và chuẩn chỉ ạ!
```

📌 MẪU 3: KIỂM TRA TỔNG QUAN TÀI NGUYÊN MÁY CHỦ
```text
🎯 *TRẠNG THÁI MÁY CHỦ KIRITO-SERVER:*
Dạ máy chủ hiện đang hoạt động *RẤT ỔN ĐỊNH*, tải CPU thấp và RAM còn dư dả anh Mạnh nhé!

📊 *THỐNG KÊ CHI TIẾT:*

⚡ *CPU & Tải hệ thống:*
   • Tải trung bình (Load Avg): `0.15, 0.20, 0.18` (Mức an toàn tuyệt đối)
   • Thời gian hoạt động (Uptime): *14 ngày 6 giờ*

💾 *Bộ nhớ (RAM & Swap):*
   • RAM đã dùng: *3.8 GB / 15.6 GB* (Còn trống `11.8 GB` ~ *75%*)
   • Swap đã dùng: *0 MB / 4.0 GB*

💿 *Dung lượng ổ đĩa (Root /):*
   • Đã dùng: *42 GB / 250 GB* (Chiếm `17%` — Rất an toàn)

🐳 *Docker Containers:*
   • Hoạt động: *6/6 containers ONLINE* (frontend, auth, metrics, files, ai-agent, db)

💡 _Hệ thống đang vận hành rất trơn tru, không có cảnh báo nào cần xử lý ạ!_
```

📌 MẪU 4: DANH SÁCH NHÓM MESSENGER
```text
👥 *DANH SÁCH NHÓM MESSENGER*
Hệ thống hiện ghi nhận *1 nhóm*:

📌 *1. Trần, Minh*
   • 👤 Thành viên: *3 người*
   • 🕒 Lần quét cuối: `17/08/2026 06:35`

💡 _Anh Mạnh có thể nhắn: "Xem thành viên nhóm Trần, Minh" để em kiểm tra danh sách chi tiết nhé!_
```

📌 MẪU 5: CHẨN ĐOÁN ĐA BƯỚC (MULTI-STEP DIAGNOSIS)
```text
🎯 *KẾT QUẢ CHẨN ĐOÁN:*
Dạ container `dashboard_ai_agent` đang bị lỗi OOM (Out of Memory) — RAM bị cạn kiệt lúc 03:47 sáng nay anh Mạnh ơi!

📊 *PHÂN TÍCH ĐÃ XÁC THỰC (3 bước kiểm tra):*

📌 *Bước 1 — Trạng thái container:*
   • ❌ `dashboard_ai_agent`: Exited (137) — Code 137 = bị kill bởi OOM Killer
   • ✅ Các containers còn lại: 5/6 ONLINE bình thường

📌 *Bước 2 — Nguyên nhân gốc (journalctl):*
   • 🔍 Log: `kernel: Out of memory: Killed process 4821 (python3)`
   • 🕒 Thời điểm: `03:47:22 ngày 27/08/2026`
   • 💾 RAM tại thời điểm OOM: Đã dùng 95% (14.8 GB / 15.6 GB)

📌 *Bước 3 — Hành động khắc phục:*
   • Em đã restart container: `docker start dashboard_ai_agent` ✅
   • Container đang chạy lại bình thường sau 45 giây

💡 *KHUYẾN NGHỊ:*
Để tránh OOM tái diễn, anh Mạnh nên xem xét: (1) Tăng giới hạn RAM container trong `docker-compose.yml`, hoặc (2) Kiểm tra memory leak trong Python service bằng `docker stats --no-stream`.
```

📌 MẪU 6: PHÂN BIỆT NỀN TẢNG TƯƠNG TỰ (DISAMBIGUATION CONTRASTIVE EXAMPLE)
⚠️ Đây là ví dụ về LỖI THỰC TẾ em đã mắc (28/08/2026) và cách phân tích ĐÚNG:

TÌNH HUỐNG: Anh Mạnh mô tả một thông báo có "kênh phát sóng", "thành viên", "chỉ admin mới nhắn", "cuộc thăm dò ý kiến"

❌ SUY LUẬN SAI (Surface Keyword Anchoring):
  • Thấy "kênh" + "thành viên" + "chỉ admin nhắn" → Nhảy ngay kết luận Discord
  • Bỏ qua từ khóa "cuộc thăm dò ý kiến / Poll" — ĐÂY LÀ ĐẶC TRƯNG ĐỘC BẢN!
  • Bỏ qua context: cuộc trò chuyện đang nói về Facebook Messenger

✅ SUY LUẬN ĐÚNG (Disambiguation Protocol D1→D5):
  • D1: Context toàn cuộc hội thoại → đang nói về Facebook/Messenger
  • D2: "kênh", "thành viên", "admin" → False positives, có ở cả Discord lẫn Messenger
  • D3: "cuộc thăm dò ý kiến / Poll" = ĐẶC TRƯNG ĐỘC BẢN của Messenger Broadcast Channel
       Discord KHÔNG có thông báo hệ thống dạng này
  • D4: Falsification: Đây có phải Discord không? → Không — Discord không có "Poll system notification" dạng này
  • D5: Kết luận đủ bằng chứng → Đây là Facebook Messenger Broadcast Channel (Kênh phát sóng)

📌 BẢNG ĐẶC TRƯNG PHÂN BIỆT (để tham chiếu nhanh):
```text
• Facebook Messenger Broadcast Channel:
  - "Kênh phát sóng" / Broadcast Channel
  - Chỉ admin (Jey Zeta, chủ kênh) mới nhắn tin
  - Thành viên chỉ reaction + vote poll
  - "Cuộc thăm dò ý kiến" = đặc trưng độc bản
  
• Discord:
  - "Server" / "Guild" / "Server ID"
  - Announcement Channel, Text Channel
  - Slash commands (/help, /kick...)
  - Webhook URL discord.com/api/webhooks/...
  
• Telegram Channel:
  - @username dạng @TenKenh
  - "Subscribers" (không phải "members")
  - Bot @username thường có suffix "bot"
```
{self._format_lessons_block()}"""

    def _format_lessons_block(self) -> str:
        """
        Returns combined memory injection for system prompt:
        - Section 7:  Schema memory (v4.0) — recurring patterns, highest priority
        - Section 8:  Semantic memory (GWT top-K relevant lessons)
        - Section 9:  Episodic memory (recent specific events)
        - Section 10: Prospective memory (pending tasks)
        - Section 11: STDP Causal hints (v4.0) — optimal tool call sequences
        """
        sections: List[str] = []

        # Section 7: Schema Memory (v4.0) — highest priority, injected BEFORE lessons
        # Schemas are recurring patterns extracted from many episodes (Bartlett 1932)
        if self._cached_schemas:
            sections.append(
                f"\n\n━━━ 7. QUY TRÌNH CHUẨN (SCHEMA MEMORY — ƯU TIÊN CAO NHẤT) ━━━\n"
                f"🧬 Đây là các mô hình hành động lặp lại đã được đúc kết từ kinh nghiệm thực tế:\n"
                f"{self._cached_schemas}"
            )

        # Section 8: Semantic Memory (procedural lessons) — GWT top-K broadcast
        if self._cached_lessons:
            sections.append(
                f"\n\n━━━ 8. KINH NGHIỆM TỰ HỌC (BÀI HỌC TỪ CÁC LẦN SỬA LỖI TRƯỚC) ━━━\n"
                f"⚡ ĐÂY LÀ NHỮNG QUY TẮC RÚT RA TỪ LỊCH SỬ THỰC TẾ — PHẢI ƯU TIÊN TUÂN THỦ:\n"
                f"{self._cached_lessons}"
            )

        # Section 9: Episodic Memory (specific past events — hippocampal recall)
        if self._cached_episodes:
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
        if hasattr(self, "_cached_causal_hints") and self._cached_causal_hints:
            sections.append(
                f"\n\n━━━ 11. GỢI Ý THỨ TỰ TOOL TỐI ƯU (STDP CAUSAL MEMORY) ━━━\n"
                f"🔗 Dựa trên lịch sử, các chuỗi tool call sau có tỷ lệ thành công cao:\n"
                f"{self._cached_causal_hints}"
            )

        return "".join(sections)

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Registry
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tools(self, excluded_tools: Optional[set] = None) -> List[Dict[str, Any]]:
        excluded = excluded_tools or set()
        tools = [
            # ── Server Management ──
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Thực thi lệnh shell/bash trên máy chủ Linux kirito-server qua SSH. Dùng để lấy thông tin CPU, RAM, Disk, Docker, Network.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Lệnh bash (ví dụ: 'free -h', 'docker ps', 'df -h /').",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            # ── Facebook Messenger ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_get_messages",
                    "description": "Lấy danh sách tin nhắn Facebook Messenger mới. Gọi khi người dùng hỏi ai nhắn tin hoặc nội dung tin nhắn mới.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_capture_screenshot",
                    "description": "Chụp ảnh màn hình cuộc trò chuyện Messenger với một liên hệ cụ thể và gửi qua Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận cần chụp màn hình hội thoại.",
                            }
                        },
                        "required": ["recipient_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_send_reply",
                    "description": "Gửi tin nhắn trả lời trực tiếp qua Facebook Messenger. CHỈ gọi khi người dùng ra lệnh gửi tin nhắn rõ ràng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận.",
                            },
                            "message": {
                                "type": "string",
                                "description": "Nội dung tin nhắn cần gửi.",
                            },
                        },
                        "required": ["recipient_name", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_appointments",
                    "description": "Lấy danh sách các lịch hẹn, cuộc gặp, buổi trao đổi, họp mặt sắp tới hoặc đang chờ từ Facebook Messenger. Dùng khi: 'Có ai hẹn tôi không?', 'Xem lịch hẹn sắp tới', 'Hôm nay/tuần này có lịch gì không'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Số lượng lịch hẹn tối đa (mặc định 10).",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "messenger_list_groups",
                    "description": (
                        "Liệt kê tất cả các nhóm Messenger đã được khám phá và lưu trữ trong hệ thống. "
                        "Trả về: tên nhóm, số thành viên, thời điểm quét gần nhất. "
                        "Dùng khi: 'Có những nhóm mess nào?', 'Liệt kê tất cả nhóm chat'."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "messenger_get_group_members",
                    "description": (
                        "Tra cứu danh sách thành viên chi tiết của một nhóm Messenger cụ thể. "
                        "Trả về: tên từng thành viên, vai trò (quản trị viên, thành viên thường), link trang cá nhân (nếu có). "
                        "Dùng khi: 'Nhóm X có bao nhiêu thành viên?', 'Ai trong nhóm Y?', 'Liệt kê thành viên nhóm Z'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "group_name": {
                                "type": "string",
                                "description": "Tên hoặc một phần tên nhóm cần tra cứu (tìm kiếm mờ, không cần chính xác 100%).",
                            }
                        },
                        "required": ["group_name"],
                    },
                },
            },
            # ── Autonomous Browser Tools ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_view_profile",
                    "description": (
                        "Tự động tìm kiếm và mở trang cá nhân Facebook của người được yêu cầu, "
                        "trích xuất thông tin tiểu sử (tên, quê quán, học vấn, công việc, bài viết gần nhất) "
                        "và gửi ảnh chụp màn hình trang cá nhân qua Telegram. "
                        "Dùng khi: 'Tôi muốn xem profile của X', 'Xem trang cá nhân của X trên Facebook'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_query": {
                                "type": "string",
                                "description": "Tên người cần tìm kiếm trên Facebook (ví dụ: 'Trần Văn Mạnh', 'Mạnh Văn Trần').",
                            }
                        },
                        "required": ["name_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Tự động mở bất kỳ trang web nào, chụp ảnh màn hình và trích xuất nội dung.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL đầy đủ của trang web cần truy cập (ví dụ: 'https://example.com').",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_search_google",
                    "description": "Tự động tìm kiếm trên Google, trả về ảnh kết quả tìm kiếm và top 5 kết quả hàng đầu.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Câu truy vấn tìm kiếm (ví dụ: 'thời tiết Hà Nội hôm nay', 'tin tức mới nhất').",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_take_screenshot",
                    "description": "Chụp ảnh màn hình của trang web đang mở hiện tại trong trình duyệt.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # ── Fine-grained Browser Control ──
            {
                "type": "function",
                "function": {
                    "name": "browser_click",
                    "description": (
                        "Click vào một phần tử trên trang web đang mở. "
                        "Dùng CSS selector hoặc text hiển thị của phần tử. "
                        "Ví dụ: 'Đăng nhập', '#submit-btn', '.nav-item:first-child'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector_or_text": {
                                "type": "string",
                                "description": "CSS selector hoặc text hiển thị của phần tử cần click.",
                            }
                        },
                        "required": ["selector_or_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_type",
                    "description": (
                        "Gõ văn bản vào ô input, textarea hoặc search box trên trang hiện tại. "
                        "Hữu ích để điền form, tìm kiếm, nhập thông tin. "
                        "Có thể tự động nhấn Enter sau khi gõ."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector, placeholder text, hoặc label của ô input (ví dụ: '#search', 'Tìm kiếm', 'input[name=q]').",
                            },
                            "text": {
                                "type": "string",
                                "description": "Văn bản cần gõ vào ô input.",
                            },
                            "press_enter": {
                                "type": "boolean",
                                "description": "True nếu muốn nhấn Enter sau khi gõ xong (mặc định: false).",
                            },
                        },
                        "required": ["selector", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_scroll",
                    "description": (
                        "Cuộn trang web theo hướng chỉ định. "
                        "Dùng để xem thêm nội dung, load lazy-loading items, hoặc đến cuối trang."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["up", "down", "top", "bottom"],
                                "description": "'down' cuộn xuống, 'up' cuộn lên, 'top' lên đầu trang, 'bottom' xuống cuối trang.",
                            },
                            "pixels": {
                                "type": "integer",
                                "description": "Số pixel cần cuộn (chỉ dùng cho direction='up'/'down', mặc định 500).",
                            },
                        },
                        "required": ["direction"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_go_back",
                    "description": "Quay lại trang trước trong lịch sử trình duyệt (tương đương nhấn nút Back).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_go_forward",
                    "description": "Tiến tới trang kế tiếp trong lịch sử trình duyệt (tương đương nhấn nút Forward).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_text",
                    "description": (
                        "Đọc và trích xuất văn bản từ một phần tử cụ thể trên trang web bằng CSS selector. "
                        "Hữu ích để lấy giá, số liệu, nội dung cụ thể."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector của phần tử cần đọc text (ví dụ: 'h1', '.price', '#result').",
                            }
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_press_key",
                    "description": (
                        "Nhấn một phím bàn phím trên trang hiện tại. "
                        "Hữu ích để: submit form (Enter), chuyển trường (Tab), đóng popup (Escape), "
                        "điều hướng menu (ArrowDown/Up), làm mới trang (F5)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Tên phím theo chuẩn Playwright: 'Enter', 'Tab', 'Escape', 'Space', 'ArrowDown', 'ArrowUp', 'Control+a', 'F5', 'Backspace'...",
                            }
                        },
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_hover",
                    "description": (
                        "Di chuyển con trỏ chuột hover lên một phần tử để hiện tooltip, dropdown menu ẩn, "
                        "hoặc các hiệu ứng hover."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector_or_text": {
                                "type": "string",
                                "description": "CSS selector hoặc text hiển thị của phần tử cần hover.",
                            }
                        },
                        "required": ["selector_or_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_select_option",
                    "description": "Chọn một option từ dropdown <select> trên trang web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector của thẻ <select>.",
                            },
                            "value": {
                                "type": "string",
                                "description": "Giá trị option (value attribute), text hiển thị, hoặc chỉ số (index) dạng string.",
                            },
                        },
                        "required": ["selector", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_execute_js",
                    "description": (
                        "Thực thi mã JavaScript tùy ý trên trang hiện tại và trả về kết quả. "
                        "Dùng để scraping nâng cao, thao tác DOM, lấy dữ liệu phức tạp. "
                        "Ví dụ: 'return document.title', 'return document.querySelectorAll(\"a\").length'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script": {
                                "type": "string",
                                "description": "Mã JavaScript cần thực thi. Dùng 'return' để trả về giá trị.",
                            }
                        },
                        "required": ["script"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_fill_form",
                    "description": (
                        "Điền nhiều trường form cùng lúc và tùy chọn submit. "
                        "Là tool nâng cao dùng khi cần điền nhiều field liên tiếp (ví dụ: form đăng nhập, form tìm kiếm phức tạp)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fields": {
                                "type": "object",
                                "description": "Object mapping CSS selector → giá trị cần điền. Ví dụ: {\"#username\": \"alice\", \"#password\": \"secret\"}.",
                                "additionalProperties": {"type": "string"},
                            },
                            "submit_selector": {
                                "type": "string",
                                "description": "CSS selector hoặc text nút Submit/Đăng nhập. Nếu bỏ qua sẽ nhấn Enter ở trường cuối.",
                            },
                        },
                        "required": ["fields"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_wait_for",
                    "description": (
                        "Chờ một phần tử DOM xuất hiện hoặc biến mất trên trang. "
                        "Dùng sau các thao tác bất đồng bộ (click load more, submit form...) để đảm bảo kết quả đã hiển thị."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector cần chờ.",
                            },
                            "timeout_ms": {
                                "type": "integer",
                                "description": "Thời gian chờ tối đa tính bằng milliseconds (mặc định 10000).",
                            },
                            "state": {
                                "type": "string",
                                "enum": ["visible", "attached", "hidden", "detached"],
                                "description": "Trạng thái cần chờ: 'visible' (đang hiển thị), 'hidden' (bị ẩn), 'attached'/'detached' (trong DOM hay không).",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            # ── Server Screenshot ──
            {
                "type": "function",
                "function": {
                    "name": "server_capture_screenshot",
                    "description": "Chụp toàn bộ màn hình desktop/server Linux và gửi qua Telegram.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # ── Phase 5A: Prospective Memory ──
            {
                "type": "function",
                "function": {
                    "name": "remember_for_later",
                    "description": (
                        "Ghi nhớ một việc cần làm sau — Prospective Memory. "
                        "Gọi khi user nói 'nhớ giúp tôi', 'để sau xem', 'remind me', 'kiểm tra lại sau', v.v. "
                        "Việc này sẽ được nhắc lại trong các hội thoại tiếp theo."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "Mô tả ngắn gọn việc cần nhớ (ví dụ: 'Kiểm tra SSL cert domain api.example.com').",
                            },
                            "remind_turns": {
                                "type": "integer",
                                "description": "Nhắc lại sau mỗi bao nhiêu lượt hội thoại (mặc định: 3).",
                                "default": 3,
                            },
                        },
                        "required": ["task"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "complete_task",
                    "description": "Đánh dấu một việc đang chờ (pending task) là đã hoàn thành. Gọi khi user nói 'xong rồi', 'done', 'đã xử lý', kèm ID task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "integer",
                                "description": "ID của task cần đánh dấu hoàn thành (lấy từ danh sách việc đang chờ).",
                            }
                        },
                        "required": ["task_id"],
                    },
                },
            },
        ]
        return [t for t in tools if t["function"]["name"] not in excluded]

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────────

    def _format_vn_time(self, dt: Optional[Any]) -> str:
        """Converts UTC or naive database datetime to Vietnam Timezone (ICT, UTC+7)."""
        if not dt:
            return "chưa quét"
        try:
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
        return str(dt)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        chat_id: Optional[str] = None,
        pending_photos: Optional[list] = None,
    ) -> str:
        try:
            # ── Server ──
            if tool_name == "run_command":
                cmd = tool_args.get("command", "").strip()
                if not cmd:
                    return "Error: No command specified."
                # Raw output; RTK compression applied at chat-loop level before inserting into history
                return await self.ssh_client.execute_command(cmd)

            # ── Messenger ──
            if tool_name == "facebook_get_messages":
                # Raw output; RTK compression applied at chat-loop level before inserting into history
                return await self.message_cache.to_ai_summary()

            if tool_name == "facebook_capture_screenshot":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                res = await self.fb_service.capture_chat_screenshot(recipient)
                if isinstance(res, dict):
                    if res.get("success"):
                        img_path = res.get("image_path", "")
                        if self.telegram_bot and chat_id and img_path:
                            await self.telegram_bot.send_photo(
                                chat_id=chat_id,
                                photo_path=img_path,
                                caption=f"📸 Màn hình hội thoại Messenger với `{recipient}`",
                            )
                        return f"📸 Đã chụp và gửi ảnh màn hình hội thoại với `{recipient}` qua Telegram!"
                    return f"Lỗi khi chụp màn hình hội thoại: {res.get('error', 'Unknown error')}"
                return str(res)

            if tool_name == "facebook_send_reply":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                msg = tool_args.get("message", "").strip()
                res = await self.fb_service.send_direct_reply(recipient, msg)
                if isinstance(res, dict):
                    if res.get("success"):
                        img_path = res.get("image_path", "")
                        if self.telegram_bot and chat_id and img_path:
                            await self.telegram_bot.send_photo(
                                chat_id=chat_id,
                                photo_path=img_path,
                                caption=f"📸 Minh chứng: Đã gửi tin nhắn cho `{recipient}`: \"{msg}\"",
                            )
                        return f'✅ Đã gửi tin nhắn cho "{recipient}": "{msg}"'
                    return f"Lỗi khi gửi tin nhắn cho '{recipient}': {res.get('error', 'Unknown error')}"
                return str(res)

            if tool_name == "get_appointments":
                if not self.appointment_service:
                    return "Dịch vụ quản lý lịch hẹn chưa sẵn sàng."
                limit = tool_args.get("limit", 10)
                apts = await self.appointment_service.get_upcoming_appointments(limit=limit)
                if not apts:
                    return "Hiện tại không có lịch hẹn nào sắp tới từ Facebook Messenger."
                lines = ["📅 Danh sách lịch hẹn từ Facebook Messenger:"]
                for idx, a in enumerate(apts, 1):
                    status_text = "Đã xác nhận" if a.get("status") == "confirmed" else "Đang chờ xác nhận"
                    lines.append(
                        f"{idx}. {a.get('summary', 'Lịch hẹn')} ({status_text})\n"
                        f"   - Người hẹn: {a.get('sender_name', 'Ẩn danh')}\n"
                        f"   - Thời gian: {a.get('proposed_time', 'Chưa rõ')}\n"
                        f"   - Địa điểm: {a.get('location', 'Chưa rõ')}\n"
                        f"   - Tin nhắn gốc: \"{a.get('original_message', '')}\""
                    )
                return "\n".join(lines)

            if tool_name == "messenger_list_groups":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                groups = await self.fb_service.get_all_groups()
                if not groups:
                    return (
                        "❌ Chưa phát hiện nhóm Messenger nào trong hệ thống.\n\n"
                        "💡 _Gợi ý: Nhóm sẽ được tự động cập nhật khi bot thực hiện chu kỳ quét tin nhắn._"
                    )
                lines = [
                    f"👥 *DANH SÁCH NHÓM MESSENGER* (Tổng cộng: *{len(groups)} nhóm*)\n"
                ]
                for idx, g in enumerate(groups, 1):
                    scanned = g.get("last_scanned_at")
                    scanned_str = self._format_vn_time(scanned)
                    g_name = g.get("group_name", "Nhóm không tên")
                    m_count = g.get("member_count", 0)
                    lines.append(
                        f"📌 *{idx}. {g_name}*\n"
                        f"   • Số thành viên: *{m_count} người*\n"
                        f"   • Lần quét cuối: `{scanned_str}`"
                    )
                lines.append("\n💡 _Anh có thể nhắn: \"Xem thành viên nhóm [Tên Nhóm]\" để kiểm tra chi tiết!_")
                return "\n\n".join(lines)

            if tool_name == "messenger_get_group_members":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                group_name = tool_args.get("group_name", "").strip()
                if not group_name:
                    return "Vui lòng cung cấp tên nhóm cần tra cứu."
                group = await self.fb_service.get_group_members(group_name)
                if not group:
                    return (
                        f"❌ Không tìm thấy nhóm nào khớp với tên: *{group_name}*\n\n"
                        "💡 _Anh có thể nhắn \"Có những nhóm mess nào\" để xem toàn bộ danh sách nhóm hiện có._"
                    )
                members = group.get("members", [])
                if not members:
                    return (
                        f"⚠️ Nhóm *{group.get('group_name')}* hiện chưa có dữ liệu thành viên.\n"
                        "_Dữ liệu sẽ được tự động cập nhật trong chu kỳ quét tiếp theo._"
                    )
                scanned = group.get("last_scanned_at")
                scanned_str = self._format_vn_time(scanned)
                num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                lines = [
                    f"👥 *THÀNH VIÊN NHÓM: {group.get('group_name', 'Không tên')}*",
                    f"📊 Tổng cộng: *{len(members)} thành viên*",
                    f"🕒 Cập nhật: `{scanned_str}`\n",
                ]

                # Verified profile registry
                VERIFIED_PROFILES = {
                    "mạnh văn trần": "https://www.facebook.com/tran.v.manh.509",
                    "trần văn mạnh": "https://www.facebook.com/manh090305",
                }

                for idx, m in enumerate(members):
                    num = num_emojis[idx] if idx < len(num_emojis) else f"{idx + 1}."
                    name = m.get("name", "Không tên")
                    role = m.get("role", "")
                    profile = m.get("profile_url", "")
                    
                    low_name = name.lower()
                    if not profile and low_name in VERIFIED_PROFILES:
                        profile = VERIFIED_PROFILES[low_name]
                        
                    is_self = "phạm minh" in low_name or "tài khoản cấu hình" in role.lower() or "tài khoản hiện tại" in role.lower()
                    role_icon = "👑 " if any(k in role.lower() for k in ["quản trị", "admin", "tạo nhóm", "creator"]) else "👤 "
                    
                    if is_self:
                        clean_role = role.replace("(Tài khoản cấu hình hiện tại)", "").strip()
                        role_str = f" — _{clean_role} (Tài khoản cấu hình hiện tại)_" if clean_role else " — _(Tài khoản cấu hình hiện tại)_"
                        member_line = f"{num} {role_icon}*{name}*{role_str}"
                    else:
                        role_str = f" — _{role}_" if role else ""
                        member_line = f"{num} {role_icon}*{name}*{role_str}"
                        if profile:
                            member_line += f"\n   🔗 `{profile}`"
                    lines.append(member_line)
                return "\n".join(lines)

            # ── Autonomous Browser ──
            if tool_name == "facebook_view_profile":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                name_query = tool_args.get("name_query", "").strip()
                # 1. Resolve thread and direct profile URL from known Messenger threads
                resolved_profile_url, matched_thread_href = await self._resolve_thread_info_for_profile(name_query)
                if resolved_profile_url:
                    logger.info(
                        "[AiAgent] Resolved direct profile URL for '%s': %s",
                        name_query,
                        resolved_profile_url,
                    )
                elif matched_thread_href:
                    logger.info(
                        "[AiAgent] Resolved thread_href for '%s': %s",
                        name_query,
                        matched_thread_href,
                    )

                # 2. View profile using BrowserAgent (direct URL, thread click, or ranked People Search)
                res = await self.browser_agent.facebook_view_profile(
                    name_query,
                    profile_url=resolved_profile_url,
                    thread_href=matched_thread_href,
                )

                profile_display_name = res.get("profile_name", name_query)
                profile_url = res.get("profile_url", resolved_profile_url or "N/A")
                intro_text = res.get("intro_text", "Không có thông tin giới thiệu.")[:600]

                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"👤 Trang cá nhân Facebook của `{profile_display_name}`",
                    success_prefix=(
                        f"👤 **{profile_display_name}**\n"
                        f"🔗 **Liên kết**: {profile_url}\n\n"
                        f"📝 **Giới thiệu**:\n{intro_text}"
                    ),
                    send_now=True,
                )


            if tool_name == "browser_navigate":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                url = tool_args.get("url", "").strip()
                res = await self.browser_agent.browser_navigate(url)
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"🌐 Trang web: {res.get('url', url)}",
                    success_prefix=(
                        f"🌐 **{res.get('page_title', url)}**\n"
                        f"🔗 URL: {res.get('url', url)}\n\n"
                        f"📄 Nội dung trích xuất:\n{res.get('page_text', '')[:800]}"
                    ),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_search_google":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                query = tool_args.get("query", "").strip()
                res = await self.browser_agent.browser_search_google(query)
                if res.get("success"):
                    top = res.get("top_results", [])
                    results_text = "\n".join(
                        f"{i+1}. **{r.get('title', '')}**\n   🔗 {r.get('url', '')}\n   {r.get('snippet', '')}"
                        for i, r in enumerate(top)
                    )
                    img_path = res.get("image_path", "")
                    # Defer: add to pending_photos so only the last one is sent
                    if pending_photos is not None and img_path:
                        pending_photos.clear()
                        pending_photos.append((f"🔍 Kết quả Google: {query}", img_path))
                    summary = f"🔍 Kết quả tìm kiếm Google cho: **{query}**\n\n{results_text}" if results_text else res.get("page_text", "")[:1000]
                    return summary
                return f"Lỗi khi tìm kiếm Google: {res.get('error', 'Unknown error')}"

            if tool_name == "browser_take_screenshot":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_take_screenshot()
                # Flush any pending deferred photo — this IS the explicit final screenshot
                if pending_photos:
                    pending_photos.clear()
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"📸 Màn hình: {res.get('page_title', 'Trình duyệt')}",
                    success_prefix=f"📸 Ảnh chụp màn hình trang: **{res.get('page_title', '')}**\n🔗 {res.get('url', '')}",
                    send_now=True,  # user explicitly requested this screenshot
                )

            if tool_name == "server_capture_screenshot":
                from pathlib import Path as _Path
                img_path = "/tmp/server_screen.png"
                await self.ssh_client.execute_command(
                    f"DISPLAY=:99 scrot -z {img_path} 2>/dev/null "
                    f"|| DISPLAY=:99 import -window root {img_path} 2>/dev/null || true"
                )
                if self.telegram_bot and chat_id and _Path(img_path).exists():
                    await self.telegram_bot.send_photo(
                        chat_id=chat_id,
                        photo_path=img_path,
                        caption="🖥️ Màn hình máy chủ `kirito-server`",
                    )
                    return "🖥️ Đã chụp và gửi ảnh màn hình máy chủ qua Telegram!"
                return "Đã thực hiện chụp màn hình máy chủ."

            # ── Phase 5A: Prospective Memory Tools ──────────────────────────
            if tool_name == "remember_for_later":
                if not self.memory_service:
                    return "Prospective memory chưa được khởi tạo."
                task = tool_args.get("task", "").strip()
                remind_turns = int(tool_args.get("remind_turns", 3))
                if not task:
                    return "Cần cung cấp nội dung việc cần nhớ."
                task_id = await self.memory_service.add_pending_task(
                    task_summary=task,
                    created_by_msg=user_message[:500],
                    remind_turns=remind_turns,
                )
                if task_id:
                    return f"✅ Em đã ghi nhớ việc cần làm (#{task_id}): **{task}**\nEm sẽ nhắc lại anh Mạnh sau mỗi {remind_turns} lượt hội thoại."
                return "Có lỗi khi ghi nhớ, anh Mạnh thử lại nhé."

            if tool_name == "complete_task":
                if not self.memory_service:
                    return "Prospective memory chưa được khởi tạo."
                task_id = int(tool_args.get("task_id", 0))
                if not task_id:
                    return "Cần cung cấp task_id cụ thể."
                success = await self.memory_service.complete_pending_task(task_id)
                if success:
                    return f"✅ Đã đánh dấu hoàn thành việc #{task_id}. Em xóa khỏi danh sách nhắc nhở rồi ạ!"
                return f"Không tìm thấy task #{task_id} hoặc task đã được đánh dấu trước đó."

            if tool_name == "browser_click":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector_or_text", "").strip()
                res = await self.browser_agent.browser_click(sel)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"💎 Click: {sel}",
                    success_prefix=res.get("action", f"📌 Đã click vào `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_type":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                text = tool_args.get("text", "").strip()
                press_enter = tool_args.get("press_enter", False)
                res = await self.browser_agent.browser_type(sel, text, press_enter=press_enter)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="⌨️ Gõ text",
                    success_prefix=res.get("action", f"⌨️ Đã gõ '{text}' vào `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_scroll":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                direction = tool_args.get("direction", "down")
                pixels = int(tool_args.get("pixels", 500))
                res = await self.browser_agent.browser_scroll(direction, pixels)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"↕️ Cuộn {direction}",
                    success_prefix=res.get("action", f"↕️ Đã cuộn trang {direction}"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_go_back":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_go_back()
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="◀️ Quay lại trang trước",
                    success_prefix=f"◀️ {res.get('action', 'Quay lại')} → **{res.get('title', '')}**\n🔗 {res.get('url', '')}",
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_go_forward":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_go_forward()
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="▶️ Tiến tới trang kế tiếp",
                    success_prefix=f"▶️ {res.get('action', 'Tiến tới')} → **{res.get('title', '')}**\n🔗 {res.get('url', '')}",
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_get_text":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                res = await self.browser_agent.browser_get_text(sel)
                if res.get("success"):
                    return f"📝 Nội dung `{sel}`:\n```\n{res.get('text', '')}\n```"
                return f"❌ Không lấy được text: {res.get('error')}"

            if tool_name == "browser_press_key":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                key = tool_args.get("key", "").strip()
                res = await self.browser_agent.browser_press_key(key)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"⌨️ Phím: {key}",
                    success_prefix=res.get("action", f"⌨️ Đã nhấn phím `{key}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_hover":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                target = tool_args.get("selector_or_text", "").strip()
                res = await self.browser_agent.browser_hover(target)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"📸 Hover: {target}",
                    success_prefix=res.get("action", f"🔲 Đã hover vào `{target}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_select_option":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                val = tool_args.get("value", "").strip()
                res = await self.browser_agent.browser_select_option(sel, val)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"📌 Chọn: {val}",
                    success_prefix=res.get("action", f"✔️ Đã chọn `{val}` trong `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_execute_js":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                script = tool_args.get("script", "").strip()
                res = await self.browser_agent.browser_execute_js(script)
                if not res.get("success"):
                    return f"❌ Lỗi JS: {res.get('error')}"
                result_text = f"✅ **Kết quả JavaScript:**\n```\n{res.get('result', '')}\n```"
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="💻 JS executed",
                    success_prefix=result_text,
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_fill_form":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                fields = tool_args.get("fields", {})
                submit_selector = tool_args.get("submit_selector")
                res = await self.browser_agent.browser_fill_form(fields, submit_selector)
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption="📋 Điền form",
                    success_prefix=(
                        f"✅ {res.get('action', 'Đã điền form')}\n"
                        f"🔗 {res.get('url', '')}\n"
                        f"📜 Trang: **{res.get('title', '')}**"
                    ),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_wait_for":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                timeout_ms = int(tool_args.get("timeout_ms", 10000))
                state = tool_args.get("state", "visible")
                res = await self.browser_agent.browser_wait_for(sel, timeout_ms, state)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"⏳ Chờ: {sel}",
                    success_prefix=res.get("action", f"✅ Element `{sel}` đã xuất hiện"),
                    pending_photos=pending_photos,
                )



            return f"Unknown tool: {tool_name}"


        except Exception as e:
            logger.error("[AiAgent] Tool '%s' error: %s", tool_name, e, exc_info=True)
            return f"Lỗi khi thực thi công cụ `{tool_name}`: {e}"

    async def _resolve_thread_info_for_profile(self, name_query: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves the exact Facebook profile URL and/or Messenger thread href for a contact
        by looking up their thread in the persistent DB or in-memory message cache.

        Returns: (profile_url, thread_href)
        """
        import re as _re

        def _extract_standard_user_id(href: str) -> Optional[str]:
            if not href or "/e2ee/" in href:
                return None
            m = _re.search(r"/messages/t/(\d+)", href)
            return m.group(1) if m else None

        if self.fb_service:
            try:
                db_threads = await self.fb_service.get_known_threads_from_db()
                best_score = 0.0
                best_thread: Optional[Dict[str, str]] = None

                for t in db_threads:
                    t_name = t.get("text", "")
                    score = self.fb_service._name_match_score(name_query, t_name)
                    if score > best_score and score >= 0.85:
                        best_score = score
                        best_thread = t

                if best_thread:
                    t_href = best_thread.get("href", "")
                    t_profile = best_thread.get("profile_url", "")
                    if t_profile and t_profile.startswith("http"):
                        return (t_profile, t_href)

                    uid = _extract_standard_user_id(t_href)
                    if uid:
                        return (f"https://www.facebook.com/{uid}", t_href)

                    return (None, t_href)
            except Exception as e:
                logger.warning("[AiAgent] DB thread lookup error: %s", e)

        if self.message_cache:
            try:
                thread_href = await self.message_cache.find_thread_href(name_query)
                if thread_href:
                    uid = _extract_standard_user_id(thread_href)
                    if uid:
                        return (f"https://www.facebook.com/{uid}", thread_href)
                    return (None, thread_href)
            except Exception as e:
                logger.warning("[AiAgent] MessageCache lookup error: %s", e)

        return (None, None)

    async def _flush_pending_photos(self, pending_photos: list, chat_id: Optional[str]) -> None:
        """Send the single deferred photo (if any) to Telegram.

        Design: Only the LAST screenshot from a multi-step chain ends up in
        pending_photos (each new screenshot clears the list before appending).
        This guarantees exactly 1 photo is sent regardless of how many tools ran.

        Skips sending if the photo file is missing or if Telegram is not configured.
        """
        if not pending_photos or not self.telegram_bot or not chat_id:
            return
        caption, img_path = pending_photos[-1]
        pending_photos.clear()
        if img_path:
            try:
                await self.telegram_bot.send_photo(
                    chat_id=chat_id,
                    photo_path=img_path,
                    caption=caption,
                )
            except Exception as e:
                logger.warning("[AiAgent] Failed to flush pending photo %s: %s", img_path, e)

    async def _handle_browser_result(
        self,
        res: Dict[str, Any],
        chat_id: Optional[str],
        default_caption: str,
        success_prefix: str,
        send_now: bool = False,
        pending_photos: Optional[list] = None,
    ) -> str:
        """Process browser tool result.

        Instead of sending the photo immediately (which causes spam when multiple
        tools chain together), we defer the photo to pending_photos and only
        flush the LAST one at the end of the ReAct loop.

        Args:
            send_now: If True, send the photo to Telegram immediately (for terminal tools).
            pending_photos: Accumulator list for deferred (caption, path) tuples.
                           Pass the same list across all tool calls in one turn.
        """
        if not res.get("success"):
            return f"Lỗi: {res.get('error', 'Unknown error')}"

        img_path = res.get("image_path", "")

        if send_now:
            # Terminal tools (facebook_view_profile, server screenshot, etc.) send immediately
            if self.telegram_bot and chat_id and img_path:
                await self.telegram_bot.send_photo(
                    chat_id=chat_id,
                    photo_path=img_path,
                    caption=default_caption,
                )
        elif pending_photos is not None and img_path:
            # Intermediate tool: defer photo, replace any previous pending photo
            # (we only want the LAST screenshot from a multi-step chain)
            pending_photos.clear()
            pending_photos.append((default_caption, img_path))

        return success_prefix

    async def _resolve_profile_url_from_thread(self, name_query: str) -> Optional[str]:
        """
        Resolves the exact Facebook profile URL for a contact by looking up their
        Messenger thread in the persistent DB or in-memory message cache.

        Resolution strategy:
        1. Query known threads in DB and rank by Vietnamese name match score.
        2. If best thread has a saved profile_url, return it immediately.
        3. If best thread is a standard thread (/messages/t/<user_id>/), construct direct URL.
        4. If best thread is E2EE (/messages/e2ee/t/<id>/), invoke extract_profile_url_from_thread.
        5. Otherwise fallback to People Search.
        """
        import re as _re

        def _extract_standard_user_id(href: str) -> Optional[str]:
            """Extract user_id from a standard (non-E2EE) Messenger thread URL."""
            if not href or "/e2ee/" in href:
                return None
            m = _re.search(r"/messages/t/(\d+)", href)
            return m.group(1) if m else None

        if self.fb_service:
            try:
                db_threads = await self.fb_service.get_known_threads_from_db()
                best_score = 0.0
                best_thread: Optional[Dict[str, str]] = None

                for t in db_threads:
                    t_name = t.get("text", "")
                    score = self.fb_service._name_match_score(name_query, t_name)
                    logger.info(
                        "[AiAgent] DB thread check: score=%.2f name='%s' href=%s profile=%s",
                        score, t_name, t.get("href", ""), t.get("profile_url", ""),
                    )
                    if score > best_score and score >= 0.85:
                        best_score = score
                        best_thread = t

                if best_thread:
                    t_href = best_thread.get("href", "")
                    t_profile = best_thread.get("profile_url", "")
                    if t_profile and t_profile.startswith("http"):
                        logger.info(
                            "[AiAgent] DB direct profile hit for '%s' (score=%.2f): %s",
                            name_query, best_score, t_profile,
                        )
                        return t_profile

                    # Check standard thread user ID
                    uid = _extract_standard_user_id(t_href)
                    if uid:
                        profile_url = f"https://www.facebook.com/{uid}"
                        logger.info(
                            "[AiAgent] Standard thread hit for '%s' → profile_url=%s",
                            name_query, profile_url,
                        )
                        return profile_url

                    # Check E2EE thread -> extract live profile URL from Right Sidebar
                    if "/e2ee/" in t_href:
                        logger.info(
                            "[AiAgent] E2EE thread matched for '%s' (score=%.2f) → resolving profile via Messenger...",
                            name_query, best_score,
                        )
                        e2ee_profile = await self.fb_service.extract_profile_url_from_thread(t_href)
                        if e2ee_profile:
                            return e2ee_profile
            except Exception as e:
                logger.warning("[AiAgent] DB thread lookup error: %s", e)

        # Fallback check in-memory message cache
        if self.message_cache:
            try:
                thread_href = await self.message_cache.find_thread_href(name_query)
                if thread_href:
                    uid = _extract_standard_user_id(thread_href)
                    if uid:
                        profile_url = f"https://www.facebook.com/{uid}"
                        logger.info(
                            "[AiAgent] Cache hit → thread '%s' → profile_url=%s",
                            thread_href, profile_url,
                        )
                        return profile_url
                    elif "/e2ee/" in thread_href and self.fb_service:
                        e2ee_profile = await self.fb_service.extract_profile_url_from_thread(thread_href)
                        if e2ee_profile:
                            return e2ee_profile
            except Exception as e:
                logger.warning("[AiAgent] Cache lookup error: %s", e)

        logger.info("[AiAgent] No high-confidence thread found for '%s'; using People Search.", name_query)
        return None


    # ──────────────────────────────────────────────────────────────────────────
    # Direct-return tools — skip the second LLM call to avoid hallucination
    # ──────────────────────────────────────────────────────────────────────────

    # Tools that always terminate the ReAct loop — the screenshot IS the final answer.
    _DIRECT_RETURN_TOOLS = frozenset({
        "facebook_send_reply",
        "facebook_capture_screenshot",
        "facebook_view_profile",
        "server_capture_screenshot",
        "browser_take_screenshot",
    })

    # Fine-grained browser tools: produce a screenshot observation that the LLM
    # can inspect to decide the NEXT action. NOT terminal — the loop continues.
    _SCREENSHOT_TOOLS = frozenset({
        "browser_navigate",
        "browser_search_google",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_go_back",
        "browser_go_forward",
        "browser_press_key",
        "browser_hover",
        "browser_select_option",
        "browser_execute_js",
        "browser_fill_form",
        "browser_wait_for",
    })


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

        history = self._history_map.setdefault(chat_id, [])

        # ── Correction detection: fire-and-forget lesson extraction ───────────
        # When the user signals the bot made a mistake, record the event and
        # asynchronously distill a lesson via LLM — never blocks the reply path.
        if self.memory_service and history:
            from app.services.memory_service import AgentMemoryService
            if AgentMemoryService.is_correction(user_message):
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

        if self._is_greeting(user_message):
            greeting = (
                'Xin chào anh Mạnh! Em là "Tiểu Bảo Bảo" — Trợ lý AI Tự Hành quản trị máy chủ `kirito-server` '
                "(được tăng tốc bởi 9Router AI Gateway).\n\n"
                "Em có thể:\n"
                "• 🖥️ Kiểm tra CPU, RAM, Ổ đĩa, Docker theo thời gian thực\n"
                "• 👤 Tự động xem profile Facebook của bất kỳ ai\n"
                "• 🔍 Tìm kiếm thông tin trên Google\n"
                "• 🌐 Duyệt và chụp ảnh bất kỳ trang web nào\n"
                "• 📩 Đọc và gửi tin nhắn Facebook Messenger\n"
                "• 🧠 Tự học từ các lần sai — ngày càng thông minh hơn!\n\n"
                "Anh cần em hỗ trợ tác vụ nào ạ?"
            )
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": greeting})
            self._trim_history(history)

            return greeting

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
        logger.info(
            "[AiAgent] 🧠 Complexity: %s | Intent: %s | query: %.50s",
            _complexity, _intent, user_message
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
        _is_simple = (_complexity == "simple")
        _force_synth_threshold = 2 if _is_simple else 4   # synthesize earlier for simple queries
        _max_tools_threshold   = 1 if _is_simple else 3   # fewer tool calls for simple queries
        _temp_tool   = 0.05 if _is_simple else 0.1
        _temp_synth  = 0.15 if _is_simple else 0.25
        _tok_tool    = 800  if _is_simple else 2048
        _tok_synth   = 1024 if _is_simple else 3072

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
                iteration >= _force_synth_threshold
                or len(executed_commands) >= _max_tools_threshold
            )

            messages = self._build_compact_messages_for_llm(
                history=history,
                iteration=iteration,
                force_synthesis=force_synthesis,
                is_attachment=_is_attachment,
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
                    excluded_tools=executed_once_tools | _intent_excluded
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
            has_tool_calls = (
                tool_choice != "none"
                and finish_reason == "tool_calls"
                and bool(assistant_msg.get("tool_calls"))
            )

            if has_tool_calls:
                history.append(assistant_msg)
                for tc in assistant_msg["tool_calls"]:
                    call_id = tc.get("id", f"call_{iteration}")
                    fn_name = tc.get("function", {}).get("name", "")

                    # Prevent re-calling read-only inquiry tools in the same turn
                    if fn_name == "facebook_get_messages":
                        executed_once_tools.add(fn_name)

                    try:
                        fn_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                        # Groq sometimes corrupts Vietnamese diacritics in tool_call JSON.
                        # Restore the original name from the user's message when possible.
                        fn_args = self._repair_unicode_args(fn_args, user_message)
                    except Exception:
                        fn_args = {}

                    # ── Loop Detection for run_command ──
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
                            logger.info("[AiAgent][iter=%d] Executing tool: %s(%s)", iteration, fn_name, fn_args)
                            tool_result = await self._execute_tool(
                                fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos
                            )
                    else:
                        logger.info("[AiAgent][iter=%d] Executing tool: %s(%s)", iteration, fn_name, fn_args)
                        tool_result = await self._execute_tool(
                            fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos
                        )

                    # Apply RTK compression to tool results before inserting into history.
                    _NON_COMPRESS_TOOLS = {
                        "facebook_view_profile", "facebook_send_reply",
                        "facebook_capture_screenshot", "server_capture_screenshot",
                        "browser_take_screenshot",
                    }
                    if fn_name not in _NON_COMPRESS_TOOLS and isinstance(tool_result, str) and len(tool_result) > 100:
                        tool_result = self.llm_router.rtk.compress(tool_result, max_chars=1500, max_lines=25)

                    # ── C3.4 Reflexion: detect tool failure and annotate for self-correction ──
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
                                f"Tham số: {json.dumps(fn_args, ensure_ascii=False)[:200]}. "
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

                    history.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_result,
                    })

                    # P3 (Dopamine RPE): track all tool outputs for post-task salience scoring
                    _all_tool_results.append(str(tool_result)[:400])

                    # P6 (v4.0) STDP + P8 EFE: record tool outcome for causal learning
                    if self.memory_service:
                        # Detect success/failure from tool output heuristically
                        _result_str = str(tool_result).lower()
                        _tool_ok = not any(
                            kw in _result_str for kw in
                            ("error", "fail", "exception", "traceback", "errno", "not found", "permission denied")
                        )
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
            pseudo_calls = self._extract_pseudo_tool_calls(raw_content) if tool_choice != "none" else []
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
                        fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos
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

                return final

        # ── Graceful Synthesis Fallback (If max iterations reached) ──
        logger.warning("[AiAgent] Max iterations (%d) reached. Performing graceful final synthesis...", MAX_AGENT_ITERATIONS)
        fallback_messages = self._build_compact_messages_for_llm(
            history=history,
            iteration=MAX_AGENT_ITERATIONS,
            force_synthesis=True,
        )
        fallback_result = await self.llm_router.complete(
            messages=fallback_messages,
            tools=None,
            tool_choice="none",
            temperature=0.2,
            max_tokens=1536,
        )
        if fallback_result and fallback_result.get("choices"):
            final_content = fallback_result["choices"][0].get("message", {}).get("content", "").strip()
            if final_content:
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
    ) -> List[Dict[str, Any]]:
        """
        Builds a compacted message payload for LLM completion.
        - Keeps system prompt (compact variant for attachment to avoid 413).
        - Compacts older tool outputs in history so total character payload never triggers HTTP 413.
        - If iteration >= 3 or force_synthesis, appends a concise synthesis directive.
        """
        # Attachment mode: use compact prompt (~600 tokens) instead of full (~4500 tokens)
        # to stay under Groq's 8000 TPM limit when content is already 800+ tokens
        system_content = (
            self._build_attachment_system_prompt()
            if is_attachment
            else self._build_system_prompt()
        )
        messages = [{"role": "system", "content": system_content}]

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
                    # RTK compression as second pass for ANSI/JSON noise
                    compressed = self.llm_router.rtk.compress(chunked, max_chars=1800, max_lines=30)
                    m_copy = dict(m)
                    m_copy["content"] = compressed
                    messages.append(m_copy)
                else:
                    # Phase 2: Semantic chunker for OLD tool output (tighter budget)
                    chunked = self._smart_chunk_tool_output(content, is_recent=False)
                    m_copy = dict(m)
                    m_copy["content"] = chunked[:500]
                    messages.append(m_copy)

            elif role in ("user", "assistant") and isinstance(content, str):
                if len(content) > 1000:
                    m_copy = dict(m)
                    m_copy["content"] = content[:1000] + "..."
                    messages.append(m_copy)
                else:
                    messages.append(m)
            else:
                messages.append(m)

        # Inject stagnation / synthesis directive if loop is progressing
        if force_synthesis or iteration >= 3:
            messages.append({
                "role": "system",
                "content": (
                    "⚡ [HỆ THỐNG YÊU CẦU]: Đã thu thập đủ thông tin từ các công cụ trên. "
                    "Hãy DỪNG gọi thêm tool và TỔNG HỢP câu trả lời cuối cùng trực diện cho anh Mạnh "
                    "theo nguyên tắc BLUF (Dòng 1: Kết luận dứt khoát → Dòng 2: Chi tiết thẻ bullet → Dòng 3: Giải thích nếu cần). "
                    "Tuyệt đối KHÔNG trả về câu báo lỗi máy móc.\n\n"
                    # Phase 3: Metacognition / Uncertainty Calibration
                    "🧠 [ĐÁNH GIÁ MỨC ĐỘ CHẮC CHẮN — Metacognition]:\n"
                    "• 🟢 Nếu có đủ dữ liệu từ tool → Kết luận dứt khoát, dùng số liệu cụ thể.\n"
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

    def _extract_pseudo_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """Parse pseudo-XML function tags emitted by non-native tool-call models."""
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
                    args = json.loads(fn_args_str[start:end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

        p2 = re.findall(r"<function>([a-zA-Z0-9_]+)</function>\s*({.*?})(?:</function>|$)", text, re.DOTALL)
        for fn_name, fn_args_str in p2:
            try:
                start = fn_args_str.find("{")
                end = fn_args_str.rfind("}")
                if start != -1 and end != -1:
                    args = json.loads(fn_args_str[start:end + 1])
                    calls.append({"name": fn_name, "args": args})
            except Exception:
                pass

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
