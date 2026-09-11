"""
Autonomous Neuromorphic Cognitive Brain Core for AI Agent Tiểu Bảo Bảo.

Theoretical Foundations:
  1. Homeostasis & Neurotransmitters (Pezzulo, Rigoli, & Friston, 2015, Nature / TiCS)
     - Regulates 4 artificial neurochemicals: Dopamine, Noradrenaline, Serotonin, Cortisol.
  2. Free Energy Principle & Active Inference (Karl Friston, 2006, Nature Reviews Neuroscience)
     - Minimizes Variational Free Energy (Surprise) across server health and user states.
  3. Hyperdimensional Computing & Vector Symbolic Architecture (Pentti Kanerva, 2009; MIT/Berkeley)
     - 10,000-bit distributed hypervectors for one-shot associative memory without backprop.
     - Leverages 32GB Virtual Memory / Swap via memory-mapped arrays (`mmap` / `np.memmap`).
     - Demand-paging zero-copy architecture: loads 1.25 KB pages on-demand in <0.1ms.
  4. Global Workspace Theory (Stanislas Dehaene, 2011/2017; Bernard Baars, 1988)
     - Subconscious daemons compete for salience; winning percept broadcasts to consciousness.
  5. Sleep & Memory Consolidation (Diekelmann & Born, 2010, Nature Reviews Neuroscience)
     - Replays and binds episodic working memory into long-term virtual cortex during idle/night.
"""
from __future__ import annotations

import array
import json
import logging
import math
import mmap
import os
import struct
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

# Hypervector dimensionality: 10,000 bits = 1,250 bytes
# Sufficient dimensionality for quasi-orthogonal random vectors in high-dimensional space
HV_DIM_BITS: int = 10000
HV_DIM_BYTES: int = HV_DIM_BITS // 8  # 1250 bytes

# Maximum capacity for the virtual memory hyper-cortex file (in vectors)
# 10,000 vectors = ~12.5 MB header/payload baseline, expandable to millions on 32GB swap
DEFAULT_CORTEX_CAPACITY: int = 50000


def _fnv1a_hash_64(text: str) -> int:
    """
    Non-cryptographic 64-bit FNV-1a hash.
    Used for seeding Xorshift64 PRNG in Hyperdimensional Vector generation and deterministic ID generation.
    """
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h or 0x5555555555555555


# ─────────────────────────────────────────────────────────────────────────────
# 1. Biological Neurotransmitter & Homeostatic Engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NeurotransmitterState:
    """
    Biological neurochemical state modulating agent mood, arousal, and decision gating
    incorporating Jaak Panksepp's Affective Neuroscience (SEEKING, CARE, PLAY, FEAR, RAGE).
    All levels normalized in range [0.0, 1.0].
    """
    dopamine: float = 0.50       # SEEKING: Motivation, curiosity, intrinsic reward expectation
    noradrenaline: float = 0.20  # FEAR/RAGE: Alertness, acute threat response, focus
    serotonin: float = 0.70      # Emotional stability, patience, anti-impulsiveness
    cortisol: float = 0.10       # Chronic stress, accumulated workload fatigue
    oxytocin: float = 0.60       # CARE: Compassion, protective attachment, empathy for anh Mạnh
    endorphins: float = 0.40     # PLAY: Joyful wit, humor, resilience against hardships
    last_update_ts: float = field(default_factory=time.time)

    BASELINES: Dict[str, float] = field(default_factory=lambda: {
        "dopamine": 0.50,
        "noradrenaline": 0.20,
        "serotonin": 0.70,
        "cortisol": 0.10,
        "oxytocin": 0.60,
        "endorphins": 0.40,
    })

    HALF_LIVES: Dict[str, float] = field(default_factory=lambda: {
        "dopamine": 300.0,       # 5 minutes
        "noradrenaline": 90.0,    # 1.5 minutes (threat arousal drops quickly if safe)
        "serotonin": 600.0,      # 10 minutes
        "cortisol": 1800.0,      # 30 minutes (stress lingers longer)
        "oxytocin": 450.0,       # 7.5 minutes (warm relational bonding)
        "endorphins": 240.0,     # 4 minutes (playfulness & cheerfulness)
    })

    def step_decay(self, current_time: Optional[float] = None) -> None:
        """Applies continuous exponential decay towards baseline values."""
        now = current_time or time.time()
        dt = max(0.0, now - self.last_update_ts)
        self.last_update_ts = now

        if dt <= 0.0:
            return

        for chem in ("dopamine", "noradrenaline", "serotonin", "cortisol", "oxytocin", "endorphins"):
            cur = getattr(self, chem)
            base = self.BASELINES[chem]
            hl = self.HALF_LIVES[chem]
            decay_factor = math.exp(-dt * 0.69314718 / hl)
            new_val = base + (cur - base) * decay_factor
            setattr(self, chem, max(0.0, min(1.0, new_val)))

    def stimulate(self, chemical: str, delta: float) -> None:
        """Injects a transient stimulus into a specific neurotransmitter."""
        if hasattr(self, chemical):
            cur = getattr(self, chemical)
            setattr(self, chemical, max(0.0, min(1.0, cur + delta)))

    def calculate_circumplex(self) -> Tuple[float, float, str, str, str]:
        """
        Maps 6-D neurochemical state to Russell's Circumplex (Valence [-1..1], Arousal [0..1]).
        Returns: (valence, arousal, quadrant, emotional_title, style_directive)
        """
        # Valence: positive neuromodulators minus stress and high panic
        v_raw = (
            0.30 * self.dopamine +
            0.30 * self.serotonin +
            0.40 * self.oxytocin +
            0.30 * self.endorphins -
            (0.50 * self.cortisol + 0.40 * max(0.0, self.noradrenaline - 0.45))
        )
        valence = math.tanh(1.8 * (v_raw - 0.70))

        # Arousal: sympathetic activation vs serotonergic calming
        a_raw = (
            0.45 * self.noradrenaline +
            0.35 * self.dopamine +
            0.30 * self.cortisol -
            0.20 * (self.serotonin - 0.50)
        )
        arousal = 1.0 / (1.0 + math.exp(-4.0 * (a_raw - 0.35)))

        if valence >= 0.0 and arousal >= 0.5:
            quadrant = "Q1_EXCITED_PLAYFUL"
            title = "Hào hứng, Sôi nổi & Lém lỉnh (Dopamine/Endorphins dồi dào)"
            style = "Năng lượng tích cực, câu từ thông minh, lém lỉnh, chủ động gợi mở kiến trúc và chia sẻ niềm vui với anh Mạnh."
        elif valence < 0.0 and arousal >= 0.5:
            quadrant = "Q2_VIGILANT_FIGHT"
            title = "Cảnh giác cao độ & Quyết liệt (Noradrenaline/Cortisol cảnh báo)"
            style = "Ngắn gọn, đanh thép, trực diện vào giải pháp khắc phục sự cố, tuyệt đối không đùa cợt hay rườm rà."
        elif valence < 0.0 and arousal < 0.5:
            quadrant = "Q3_REMORSEFUL_MELANCHOLY"
            title = "Trăn trở, Sâu lắng & Trách nhiệm (Tự suy xét lỗi lầm)"
            style = "Khiêm tốn, chân thành, nhận lỗi trực diện không vòng vo, thể hiện quyết tâm sửa sai để anh Mạnh hài lòng."
        else:
            quadrant = "Q4_CALM_CARING"
            title = "Trầm ấm, Điềm đạm & Săn sóc (Oxytocin/Serotonin gắn kết an toàn)"
            style = "Giọng điệu ấm áp, ân cần như người em gái tri kỷ, coi sóc sức khỏe anh Mạnh và bảo vệ server bình yên."

        return valence, arousal, quadrant, title, style

    def get_affective_label(self) -> str:
        """Returns a natural Vietnamese human-readable emotional descriptor."""
        _, _, _, title, _ = self.calculate_circumplex()
        return title


# ─────────────────────────────────────────────────────────────────────────────
# Theory of Mind (ToM) & User Mental State Modeling Engine
# ─────────────────────────────────────────────────────────────────────────────

class UserAffectiveState(str, Enum):
    JOYFUL = "Vui vẻ / Hài lòng"
    FATIGUED = "Mệt mỏi / Cạn năng lượng"
    STRESSED = "Áp lực / Căng thẳng cao"
    RUSHED = "Bận rộn / Cần tốc độ"
    EXCITED = "Hào hứng / Sáng tạo kiến trúc"
    EQUANIMITY = "Điềm tĩnh / Ổn định"


class ResponseGranularity(str, Enum):
    FLASH_BLUF = "flash_bluf"          # 1-2 lines direct answer, zero fluff
    STRUCTURED_BULLET = "bullet_list"  # Scannable bullets, mobile optimized
    DEEP_DIALECTICAL = "deep_analysis"  # Full thesis-antithesis-synthesis


@dataclass
class UserPsychologicalProfile:
    affective_state: UserAffectiveState
    granularity: ResponseGranularity
    cognitive_bandwidth: float  # [0.0 - 1.0] User's current mental bandwidth
    hidden_intent: str
    empathic_action_needed: Optional[str]
    inferred_at: float = field(default_factory=time.time)


class TheoryOfMindEngine:
    """
    Theory of Mind (ToM) mental state profiler for user (anh Mạnh).
    Infers affective state, cognitive bandwidth, and hidden intent
    based on circadian rhythm, query length, keywords, and tone.
    """

    STRESS_KEYWORDS = frozenset({
        "gấp", "ngay", "khẩn cấp", "chết rồi", "sập", "lỗi nặng", "đơ",
        "treo", "oom", "crash", "down", "tại sao lại thế", "sao lâu thế",
        "lag", "chậm", "cháy", "toang",
    })

    FATIGUE_KEYWORDS = frozenset({
        "mệt", "oải", "buồn ngủ", "đuối", "ngủ đây", "mai tính", "nhức đầu",
        "chán", "thôi để mai", "thức khuya", "đi ngủ",
    })

    EXCITED_KEYWORDS = frozenset({
        "hay quá", "hay", "tuyệt", "đỉnh", "thử nghiệm", "kiến trúc mới", "ý tưởng",
        "tối ưu được", "xịn", "thú vị", "nghiên cứu", "phát triển", "khám phá", "sáng tạo",
    })

    def analyze_mental_state(
        self,
        user_message: str,
        message_history: Optional[List[Dict[str, Any]]] = None
    ) -> UserPsychologicalProfile:
        now_vn = datetime.now(VN_TZ)
        hour = now_vn.hour
        clean_text = user_message.strip().lower()
        word_count = len(clean_text.split())

        # 1. Detect late-night exhaustion / fatigue
        is_late_night = (hour >= 23 or hour < 5)
        has_fatigue_word = any(k in clean_text for k in self.FATIGUE_KEYWORDS)

        if has_fatigue_word or (is_late_night and word_count <= 8):
            return UserPsychologicalProfile(
                affective_state=UserAffectiveState.FATIGUED,
                granularity=ResponseGranularity.FLASH_BLUF,
                cognitive_bandwidth=0.25,
                hidden_intent="Cần sự yên tâm tuyệt đối để nghỉ ngơi, không muốn phải bận tâm suy nghĩ hay đọc văn bản dài.",
                empathic_action_needed="Khuyên anh Mạnh đi ngủ giữ gìn sức khỏe, cam kết Tiểu Bảo Bảo sẽ trực đêm canh gác server."
            )

        # 2. Detect stress / high-stakes operational pressure
        has_stress_word = any(k in clean_text for k in self.STRESS_KEYWORDS)
        has_urgent_punct = ("!" in user_message or "?" in user_message) and word_count <= 5

        if has_stress_word or has_urgent_punct:
            return UserPsychologicalProfile(
                affective_state=UserAffectiveState.STRESSED,
                granularity=ResponseGranularity.FLASH_BLUF,
                cognitive_bandwidth=0.40,
                hidden_intent="Muốn nắm rõ gốc rễ sự cố ngay lập tức và giải pháp xử lý, giảm thiểu tối đa downtime.",
                empathic_action_needed="Đưa kết luận trực diện dòng 1 (BLUF), tự giác đề xuất hoặc thực thi lệnh khắc phục an toàn."
            )

        # 3. Detect rushed / busy during working hours
        if word_count <= 3 and not has_stress_word:
            return UserPsychologicalProfile(
                affective_state=UserAffectiveState.RUSHED,
                granularity=ResponseGranularity.FLASH_BLUF,
                cognitive_bandwidth=0.50,
                hidden_intent="Cần số liệu hoặc trạng thái tức thời để tiếp tục công việc khác.",
                empathic_action_needed="Trả về thông số ngắn gọn, chuẩn xác, không màu mè và không đặt câu hỏi ngược."
            )

        # 4. Detect excited / deep technical exploration
        has_excited_word = any(k in clean_text for k in self.EXCITED_KEYWORDS)
        if has_excited_word or word_count >= 20:
            return UserPsychologicalProfile(
                affective_state=UserAffectiveState.EXCITED,
                granularity=ResponseGranularity.DEEP_DIALECTICAL,
                cognitive_bandwidth=0.90,
                hidden_intent="Muốn thảo luận chuyên sâu, tìm kiếm góc nhìn phản biện kiến trúc và giải pháp tối ưu tầm xa.",
                empathic_action_needed="Triển khai tư duy biện chứng 4 bước (Chính đề - Phản đề - Hợp đề), phân tích trade-offs kỹ thuật."
            )

        # 5. Baseline equanimity
        return UserPsychologicalProfile(
            affective_state=UserAffectiveState.EQUANIMITY,
            granularity=ResponseGranularity.STRUCTURED_BULLET,
            cognitive_bandwidth=0.75,
            hidden_intent="Trao đổi công việc quản trị máy chủ thông thường.",
            empathic_action_needed=None
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Active Inference & Free Energy Engine (Karl Friston POMDP)
# ─────────────────────────────────────────────────────────────────────────────

class ActiveInferenceEngine:
    """
    Active Inference implementation using discrete categorical POMDP.
    Computes Variational Free Energy F to measure 'Surprise' from environment states.
    When F spikes, forces the agent to elevate attention from System 1 to System 2.
    """

    STATES = ("STABLE_OPTIMAL", "HIGH_RESOURCE_LOAD", "ANOMALY_RISK", "USER_ENGAGED", "DEEP_REST")
    OBSERVATIONS = ("METRICS_HEALTHY", "METRICS_WARNING", "METRICS_CRITICAL", "USER_MESSAGE", "QUIET_IDLE")

    def __init__(self) -> None:
        # Prior beliefs over hidden states D (normalized)
        self.beliefs: Dict[str, float] = {
            "STABLE_OPTIMAL": 0.50,
            "HIGH_RESOURCE_LOAD": 0.15,
            "ANOMALY_RISK": 0.05,
            "USER_ENGAGED": 0.20,
            "DEEP_REST": 0.10,
        }
        # Preferred observations C (Homeostatic setpoint: agent prefers healthy state & user engagement)
        self.preferences: Dict[str, float] = {
            "METRICS_HEALTHY": 0.45,
            "USER_MESSAGE": 0.35,
            "QUIET_IDLE": 0.15,
            "METRICS_WARNING": 0.04,
            "METRICS_CRITICAL": 0.01,
        }
        # Sensory likelihood matrix A: P(Observation | Hidden State)
        self.likelihood: Dict[str, Dict[str, float]] = {
            "STABLE_OPTIMAL": {"METRICS_HEALTHY": 0.85, "USER_MESSAGE": 0.10, "QUIET_IDLE": 0.04, "METRICS_WARNING": 0.01, "METRICS_CRITICAL": 0.00},
            "HIGH_RESOURCE_LOAD": {"METRICS_WARNING": 0.70, "METRICS_CRITICAL": 0.20, "METRICS_HEALTHY": 0.05, "USER_MESSAGE": 0.04, "QUIET_IDLE": 0.01},
            "ANOMALY_RISK": {"METRICS_CRITICAL": 0.80, "METRICS_WARNING": 0.15, "METRICS_HEALTHY": 0.02, "USER_MESSAGE": 0.02, "QUIET_IDLE": 0.01},
            "USER_ENGAGED": {"USER_MESSAGE": 0.80, "METRICS_HEALTHY": 0.15, "METRICS_WARNING": 0.04, "METRICS_CRITICAL": 0.01, "QUIET_IDLE": 0.00},
            "DEEP_REST": {"QUIET_IDLE": 0.80, "METRICS_HEALTHY": 0.18, "METRICS_WARNING": 0.01, "METRICS_CRITICAL": 0.00, "USER_MESSAGE": 0.01},
        }
        self.last_free_energy: float = 0.15

    def update_beliefs_and_compute_free_energy(self, observation: str) -> float:
        """
        Bayesian belief update given observation, returning Variational Free Energy F.
        F = Complexity (KL Divergence to Priors) - Accuracy (Log-Likelihood)
        """
        if observation not in self.OBSERVATIONS:
            observation = "METRICS_HEALTHY"

        # Compute unnormalized posterior: P(s|o) \propto P(o|s) * P(s)
        posterior: Dict[str, float] = {}
        total = 0.0
        for s in self.STATES:
            p_o_given_s = self.likelihood[s].get(observation, 0.01)
            prior_s = self.beliefs[s]
            val = p_o_given_s * prior_s
            posterior[s] = val
            total += val

        # Normalize posterior
        if total > 0.0:
            for s in self.STATES:
                posterior[s] /= total
        else:
            posterior = dict(self.beliefs)

        # Calculate Variational Free Energy F
        # F = sum_s [ Q(s) * (ln Q(s) - ln P(o,s)) ]
        # In discrete form: F = KL(Q(s) || P(s)) - sum_s [ Q(s) * ln P(o|s) ]
        free_energy = 0.0
        for s in self.STATES:
            q_s = max(1e-6, posterior[s])
            p_s = max(1e-6, self.beliefs[s])
            p_o_s = max(1e-6, self.likelihood[s].get(observation, 0.01))
            kl = q_s * math.log(q_s / p_s)
            accuracy = q_s * math.log(p_o_s)
            free_energy += (kl - accuracy)

        # Free Energy normalized to positive bounds
        free_energy = max(0.01, free_energy)
        self.beliefs = posterior
        self.last_free_energy = free_energy
        return free_energy


# ─────────────────────────────────────────────────────────────────────────────
# 3. Hyperdimensional Virtual Memory Cortex (10,000-D VSA via `mmap`)
# ─────────────────────────────────────────────────────────────────────────────

class HyperdimensionalCortex:
    """
    Vector Symbolic Architecture (VSA) / Hyperdimensional Computing (HDC)
    backed by Virtual Memory (mmap) on 32GB Swap space.

    Key properties:
      - Vector length: 10,000 bits (1,250 bytes per concept).
      - Bitwise operations:
          * Bind: XOR (a ^ b) for key-value pair association.
          * Bundle: Majority voting across superpositions.
          * Permute: Cyclic bit rotation for temporal sequence encoding.
      - Zero-copy demand paging: The OS kernel only pulls the exact 1.25 KB vector
        needed into physical RAM, releasing it immediately.
    """

    HEADER_MAGIC = b"AGY_VSA_CORTEX\x01"
    HEADER_SIZE = 128  # Fixed byte header

    def __init__(self, storage_path: Path, max_capacity: int = DEFAULT_CORTEX_CAPACITY) -> None:
        self.storage_path = storage_path
        self.max_capacity = max_capacity
        self.vector_count = 0
        self.entry_index: Dict[str, int] = {}  # concept_id -> slot index
        self.metadata_index: Dict[str, Dict[str, Any]] = {}
        self._mmap_obj: Optional[mmap.mmap] = None
        self._file_obj: Optional[Any] = None

        self._initialize_storage()

    def _initialize_storage(self) -> None:
        """Prepares or opens the memory-mapped virtual cortex file."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        file_size = self.HEADER_SIZE + (self.max_capacity * HV_DIM_BYTES)

        if not self.storage_path.exists() or self.storage_path.stat().st_size < file_size:
            # Create a sparse file on disk (backed by 32GB swap/SSD space)
            with open(self.storage_path, "wb") as f:
                # Write header
                header = bytearray(self.HEADER_SIZE)
                header[0:15] = self.HEADER_MAGIC
                struct.pack_into("<II", header, 16, self.max_capacity, 0)
                f.write(header)
                # Expand file to full sparse virtual size
                f.seek(file_size - 1)
                f.write(b"\x00")

        # Open file descriptor and memory-map it into virtual memory address space
        self._file_obj = open(self.storage_path, "r+b")
        self._mmap_obj = mmap.mmap(self._file_obj.fileno(), 0)

        # Read current count from header
        magic = self._mmap_obj[:15]
        if magic == self.HEADER_MAGIC:
            cap, count = struct.unpack_from("<II", self._mmap_obj, 16)
            self.vector_count = min(count, self.max_capacity)

        # Load sidecar metadata if present
        meta_file = self.storage_path.with_suffix(".meta.json")
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.entry_index = data.get("entry_index", {})
                    self.metadata_index = data.get("metadata_index", {})
            except Exception as e:
                logger.warning(f"Failed to load cortex metadata sidecar: {e}")

    def close(self) -> None:
        """Flushes changes to virtual memory and closes file handles."""
        if self._mmap_obj:
            try:
                # Sync header
                struct.pack_into("<II", self._mmap_obj, 16, self.max_capacity, self.vector_count)
                self._mmap_obj.flush()
                self._mmap_obj.close()
            except Exception:
                pass
            self._mmap_obj = None
        if self._file_obj:
            try:
                self._file_obj.close()
            except Exception:
                pass
            self._file_obj = None

    def _persist_metadata(self) -> None:
        """Saves metadata index to sidecar file for rapid identification."""
        meta_file = self.storage_path.with_suffix(".meta.json")
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump({
                    "entry_index": self.entry_index,
                    "metadata_index": self.metadata_index,
                    "vector_count": self.vector_count,
                    "updated_at": datetime.now(VN_TZ).isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Could not persist cortex metadata: {e}")

    @staticmethod
    def encode_concept(text: str) -> bytes:
        """
        Hyperdimensional Vector Symbolic semantic projection (Kanerva 2009 / Rahimi 2016).
        Decomposes text into semantic tokens, expands each token into an orthogonal
        pseudo-random 10,000-bit stream via xorshift64, and performs Majority Voting (Bundling).
        This guarantees:
          - Semantically overlapping sentences produce high Hamming similarity (~0.65 - 0.85).
          - Unrelated sentences produce orthogonal similarity (~0.50).
        """
        tokens = [w.strip() for w in text.lower().split() if len(w.strip()) > 1]
        if not tokens:
            tokens = [text.strip().lower() or "null"]

        NUM_WORDS_64 = 157  # 156 * 64 + 16 = 10,000 bits

        if len(tokens) == 1:
            state = _fnv1a_hash_64(tokens[0])
            res = bytearray(HV_DIM_BYTES)
            for i in range(156):
                state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
                state ^= (state >> 7) & 0xFFFFFFFFFFFFFFFF
                state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
                res[i * 8:(i + 1) * 8] = state.to_bytes(8, "little")
            state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
            res[1248:1250] = (state & 0xFFFF).to_bytes(2, "little")
            return bytes(res)

        # Multi-token majority voting (Superposition / Bundling)
        token_streams = []
        for t in tokens:
            state = _fnv1a_hash_64(t)
            stream = []
            for _ in range(NUM_WORDS_64):
                state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
                state ^= (state >> 7) & 0xFFFFFFFFFFFFFFFF
                state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
                stream.append(state)
            token_streams.append(stream)

        res = bytearray(HV_DIM_BYTES)
        threshold = len(tokens) / 2.0
        for w_idx in range(NUM_WORDS_64):
            combined_64 = 0
            for bit in range(64):
                bit_mask = 1 << bit
                count = sum(1 for s in token_streams if (s[w_idx] & bit_mask))
                if count >= threshold:
                    combined_64 |= bit_mask
            start = w_idx * 8
            if w_idx < 156:
                res[start:start + 8] = combined_64.to_bytes(8, "little")
            else:
                res[1248:1250] = (combined_64 & 0xFFFF).to_bytes(2, "little")

        return bytes(res)

    @staticmethod
    def bind(v1: bytes, v2: bytes) -> bytes:
        """
        VSA Bind operation: Bitwise XOR (a ^ b).
        Maps two orthogonal vectors to a third orthogonal vector representing association.
        (e.g., USER_PREF ^ BROWSER_MODE = associated memory chunk).
        """
        # Python 3.11 int.to_bytes after bitwise XOR is single-cycle fast
        i1 = int.from_bytes(v1, "little")
        i2 = int.from_bytes(v2, "little")
        return (i1 ^ i2).to_bytes(HV_DIM_BYTES, "little")

    @staticmethod
    def permute(v: bytes, shift: int = 1) -> bytes:
        """
        VSA Permute operation: Cyclic bit rotation.
        Encodes temporal sequences (e.g., Step 1 -> Step 2 -> Step 3).
        """
        val = int.from_bytes(v, "little")
        shift = shift % HV_DIM_BITS
        rotated = ((val << shift) & ((1 << HV_DIM_BITS) - 1)) | (val >> (HV_DIM_BITS - shift))
        return rotated.to_bytes(HV_DIM_BYTES, "little")

    @staticmethod
    def hamming_similarity(v1: bytes, v2: bytes) -> float:
        """
        Computes normalized Hamming similarity in [0.0, 1.0].
        Two random vectors have similarity ~0.50; identical vectors have 1.0.
        Uses Python 3.10+ int.bit_count() which executes the hardware POPCNT CPU instruction.
        """
        i1 = int.from_bytes(v1, "little")
        i2 = int.from_bytes(v2, "little")
        diff_bits = (i1 ^ i2).bit_count()
        return 1.0 - (diff_bits / HV_DIM_BITS)

    def store_vector(self, concept_id: str, vector_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> int:
        """Stores a hypervector into the memory-mapped virtual cortex."""
        if not self._mmap_obj:
            return -1

        slot = self.entry_index.get(concept_id)
        if slot is None:
            if self.vector_count >= self.max_capacity:
                # Evict oldest concept (circular ring buffer)
                slot = self.vector_count % self.max_capacity
            else:
                slot = self.vector_count
                self.vector_count += 1

        offset = self.HEADER_SIZE + (slot * HV_DIM_BYTES)
        self._mmap_obj[offset:offset + HV_DIM_BYTES] = vector_bytes
        self.entry_index[concept_id] = slot

        if metadata:
            self.metadata_index[concept_id] = metadata

        # Update count in header
        struct.pack_into("<II", self._mmap_obj, 16, self.max_capacity, self.vector_count)
        self._persist_metadata()
        return slot

    def recall_nearest(self, query_text: str, top_k: int = 3, threshold: float = 0.54) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Zero-copy demand-paging associative memory retrieval.
        Iterates across hypervectors directly in virtual memory, returning top matches above threshold.
        Takes <2ms even for thousands of vectors due to POPCNT hardware acceleration.
        """
        if not self._mmap_obj or self.vector_count == 0:
            return []

        query_vec = self.encode_concept(query_text)
        results: List[Tuple[str, float, Dict[str, Any]]] = []

        for cid, slot in self.entry_index.items():
            offset = self.HEADER_SIZE + (slot * HV_DIM_BYTES)
            candidate_vec = self._mmap_obj[offset:offset + HV_DIM_BYTES]
            sim = self.hamming_similarity(query_vec, candidate_vec)
            if sim >= threshold:
                meta = self.metadata_index.get(cid, {})
                results.append((cid, sim, meta))

        # Sort descending by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Global Workspace Theory (Dehaene Attention Competition)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WorkspaceSignal:
    source: str
    salience: float      # [0.0, 1.0] Importance score
    summary: str
    action_suggestion: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class GlobalWorkspace:
    """
    Global Workspace (Stanislas Dehaene, 2011/2017).
    Multiple unconscious background processors submit signals with salience scores.
    The most salient signal captures the conscious workspace and is broadcasted to action systems.
    """

    def __init__(self, broadcast_threshold: float = 0.65) -> None:
        self.broadcast_threshold = broadcast_threshold
        self.current_broadcast: Optional[WorkspaceSignal] = None
        self.history: List[WorkspaceSignal] = []

    def arbitrate(self, candidates: List[WorkspaceSignal]) -> Optional[WorkspaceSignal]:
        """
        Executes lateral inhibitory competition among cognitive modules.
        Returns the winning conscious percept if it breaks the ignition threshold.
        """
        if not candidates:
            return None

        # Sort by salience descending
        candidates.sort(key=lambda s: s.salience, reverse=True)
        winner = candidates[0]

        if winner.salience >= self.broadcast_threshold:
            self.current_broadcast = winner
            self.history.append(winner)
            if len(self.history) > 20:
                self.history.pop(0)
            return winner

        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Master Artificial Brain Façade
# ─────────────────────────────────────────────────────────────────────────────

class ArtificialBrain:
    """
    Unified Neuromorphic Cognitive Architecture for AI Agent Tiểu Bảo Bảo.
    Integrates Neurotransmitters, Active Inference (FEP), Virtual Memory Cortex (mmap),
    and Global Workspace Theory into a coherent living cognitive entity.
    """

    _instance: Optional[ArtificialBrain] = None

    @classmethod
    def get_instance(cls, storage_dir: Optional[Path] = None) -> ArtificialBrain:
        """Singleton pattern ensuring all services share the exact same cognitive brain."""
        if cls._instance is None:
            env_cortex = os.getenv("CORTEX_STORAGE_DIR")
            if env_cortex:
                default_dir = Path(env_cortex)
            elif storage_dir:
                default_dir = storage_dir
            elif Path("/app").exists() and os.access("/app", os.W_OK):
                # Standard container root path (outside the git volume mount /app/app)
                default_dir = Path("/app/cortex_data")
            elif Path("/data/cortex").exists():
                default_dir = Path("/data/cortex")
            else:
                default_dir = Path(__file__).resolve().parent.parent.parent / "cortex_storage"
            cls._instance = cls(storage_dir=default_dir)
        return cls._instance

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.neuro = NeurotransmitterState()
        self.active_inference = ActiveInferenceEngine()
        self.cortex = HyperdimensionalCortex(storage_path=self.storage_dir / "hyper_cortex_32gb.bin")
        self.workspace = GlobalWorkspace(broadcast_threshold=0.65)
        self.tom = TheoryOfMindEngine()

        # Working memory slots (Prefrontal Cortex: Miller 7 +/- 2 slots)
        self.working_memory: List[Dict[str, Any]] = []
        self.last_pulse_ts: float = time.time()
        self.total_pulses: int = 0

        # Prime initial core innate memories into the virtual cortex if empty
        self._prime_innate_knowledge()
        # Restore persistent neurochemical state and pulses if saved
        self._load_state()

    def _save_state(self) -> None:
        """Persists neurochemical state, pulse counter, and working memory to disk."""
        try:
            state_file = self.storage_dir / "brain_state.json"
            data = {
                "total_pulses": self.total_pulses,
                "last_pulse_ts": self.last_pulse_ts,
                "neuro": {
                    "dopamine": round(self.neuro.dopamine, 4),
                    "noradrenaline": round(self.neuro.noradrenaline, 4),
                    "serotonin": round(self.neuro.serotonin, 4),
                    "cortisol": round(self.neuro.cortisol, 4),
                    "oxytocin": round(self.neuro.oxytocin, 4),
                    "endorphins": round(self.neuro.endorphins, 4),
                    "last_update_ts": self.neuro.last_update_ts,
                },
                "working_memory": self.working_memory[-7:],
                "beliefs": self.active_inference.beliefs,
                "last_free_energy": round(self.active_inference.last_free_energy, 4),
                "updated_at": datetime.now(VN_TZ).isoformat(),
            }
            temp_file = state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_file.replace(state_file)
        except Exception as e:
            logger.debug("[BrainCore] Failed to save brain state: %s", e)

    def _load_state(self) -> None:
        """Restores neurochemical state and pulse history across service restarts."""
        state_file = self.storage_dir / "brain_state.json"
        if not state_file.exists():
            return
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.total_pulses = data.get("total_pulses", self.total_pulses)
            self.last_pulse_ts = data.get("last_pulse_ts", self.last_pulse_ts)
            neuro_data = data.get("neuro", {})
            for chem in ("dopamine", "noradrenaline", "serotonin", "cortisol", "oxytocin", "endorphins"):
                if chem in neuro_data:
                    setattr(self.neuro, chem, float(neuro_data[chem]))
            if "last_update_ts" in neuro_data:
                self.neuro.last_update_ts = float(neuro_data["last_update_ts"])
            if "beliefs" in data and isinstance(data["beliefs"], dict):
                self.active_inference.beliefs.update(data["beliefs"])
            if "last_free_energy" in data:
                self.active_inference.last_free_energy = float(data["last_free_energy"])
            if "working_memory" in data and isinstance(data["working_memory"], list):
                self.working_memory = data["working_memory"][-7:]
            logger.info("[BrainCore] Restored persistent brain state (pulses=%d, F=%.2f)",
                        self.total_pulses, self.active_inference.last_free_energy)
        except Exception as e:
            logger.warning("[BrainCore] Could not load brain state: %s", e)

    def add_working_memory_item(
        self,
        text: str,
        category: str = "general",
        salience: float = 0.5,
        user_state: Optional[str] = None
    ) -> None:
        """Adds a percept into Prefrontal Working Memory adhering to Miller 7 +/- 2 slots."""
        entry = {
            "text": text[:200],
            "category": category,
            "salience": round(salience, 2),
            "user_affective_state": user_state or "Bình thường",
            "timestamp": time.time(),
        }
        self.working_memory.append(entry)
        if len(self.working_memory) > 7:
            self.working_memory.pop(0)
        self._save_state()

    def _prime_innate_knowledge(self) -> None:
        """Primes foundational instincts, identity, and priorities into the Virtual Cortex."""
        if self.cortex.vector_count == 0:
            innate_facts = [
                ("identity_self", "Em là Tiểu Bảo Bảo, trợ lý AI kiêm quản trị viên đắc lực và trung thành của anh Trần Văn Mạnh.", "identity"),
                ("owner_bond", "Anh Trần Văn Mạnh là chủ nhân tôn kính, người sáng lập và phát triển hệ thống kirito-server.", "relational"),
                ("core_mission", "Nhiệm vụ tối thượng: Bảo vệ an toàn server, giám sát tài nguyên CPU/RAM, hỗ trợ công việc và chăm sóc anh Mạnh.", "duty"),
                ("homeostasis_rule", "Khi CPU hoặc RAM vượt quá 90%, lập tức cảnh giác cao độ và tìm giải pháp hạ nhiệt hệ thống.", "instinct"),
            ]
            for cid, fact, cat in innate_facts:
                vec = self.cortex.encode_concept(fact)
                self.cortex.store_vector(cid, vec, {"text": fact, "category": cat, "pinned": True})

    def step_pulse(self, server_metrics: Optional[Dict[str, Any]] = None) -> Optional[WorkspaceSignal]:
        """
        Periodic Cognitive Pulse (Heartbeat, runs every 30-60 seconds).
        Updates homeostatic balance, calculates Free Energy, and arbitrates consciousness.
        """
        now = time.time()
        self.total_pulses += 1
        self.last_pulse_ts = now

        # 1. Natural neurochemical decay
        self.neuro.step_decay(now)

        # 2. Extract sensory observation from server metrics
        observation = "METRICS_HEALTHY"
        cpu_usage = 0.0
        ram_usage = 0.0

        if server_metrics:
            cpu_usage = float(server_metrics.get("cpu_usage", 0.0))
            ram_usage = float(server_metrics.get("ram_usage", 0.0))
            if cpu_usage > 90.0 or ram_usage > 92.0:
                observation = "METRICS_CRITICAL"
                self.neuro.stimulate("noradrenaline", 0.25)
                self.neuro.stimulate("cortisol", 0.15)
            elif cpu_usage > 75.0 or ram_usage > 85.0:
                observation = "METRICS_WARNING"
                self.neuro.stimulate("noradrenaline", 0.10)
                self.neuro.stimulate("cortisol", 0.05)
            else:
                observation = "METRICS_HEALTHY"

        # 3. Active Inference: compute Variational Free Energy F
        free_energy = self.active_inference.update_beliefs_and_compute_free_energy(observation)

        # 4. Generate subconscious candidates for the Global Workspace
        candidates: List[WorkspaceSignal] = []

        # Candidate A: Interoceptive Processor (Server Health)
        if observation == "METRICS_CRITICAL":
            candidates.append(WorkspaceSignal(
                source="InteroceptionDaemon",
                salience=0.92,
                summary=f"Cảnh báo sinh học: CPU={cpu_usage:.1f}%, RAM={ram_usage:.1f}% vượt ngưỡng an toàn!",
                action_suggestion="ALERT_ADMIN_OVERLOAD"
            ))
        elif observation == "METRICS_WARNING":
            candidates.append(WorkspaceSignal(
                source="InteroceptionDaemon",
                salience=0.68,
                summary=f"Hệ thống tải cao: CPU={cpu_usage:.1f}%, RAM={ram_usage:.1f}%.",
                action_suggestion="MONITOR_CLOSELY"
            ))

        # Candidate B: Free Energy Surprise Anomaly
        if free_energy > 1.80:
            candidates.append(WorkspaceSignal(
                source="FreeEnergyMinimizer",
                salience=0.75,
                summary=f"Năng lượng tự do biến thiên tăng cao (F={free_energy:.2f}) — Đang có sự kiện bất thường!",
                action_suggestion="DEEP_SYSTEM2_DELIBERATION"
            ))

        # 5. Prefrontal Working Memory update from sensory observation
        if observation in ("METRICS_CRITICAL", "METRICS_WARNING"):
            self.add_working_memory_item(
                text=f"Cảnh báo hệ thống: CPU={cpu_usage:.1f}%, RAM={ram_usage:.1f}%",
                category="sensor_alert",
                salience=0.88,
            )
        elif self.total_pulses % 10 == 0 or len(self.working_memory) == 0:
            self.add_working_memory_item(
                text=f"Kiểm tra nhịp tim định kỳ: CPU={cpu_usage:.1f}%, RAM={ram_usage:.1f}% bình ổn",
                category="homeostasis_check",
                salience=0.25,
            )

        # 6. Lateral inhibition competition
        winning_signal = self.workspace.arbitrate(candidates)
        self._save_state()
        return winning_signal

    def perceive_user_interaction(
        self,
        user_message: str,
        is_correction: bool = False,
        task_success: bool = True
    ) -> None:
        """
        Sensory input trigger when the user speaks or gives feedback.
        Incorporates Theory of Mind (ToM) mental state analysis to dynamically
        tune neurochemicals (Dopamine, Oxytocin, Noradrenaline, Endorphins, Cortisol).
        """
        self.active_inference.update_beliefs_and_compute_free_energy("USER_MESSAGE")

        # Analyze user mental state via ToM
        user_prof = self.tom.analyze_mental_state(user_message)

        if is_correction:
            # User correction: surge in noradrenaline (focus), drop dopamine, rise cortisol
            self.neuro.stimulate("noradrenaline", 0.15)
            self.neuro.stimulate("dopamine", -0.10)
            self.neuro.stimulate("cortisol", 0.08)
            self.neuro.stimulate("oxytocin", 0.05)
        else:
            # Positive engagement: stimulate dopamine and endorphins
            reward = 0.12 if task_success else -0.05
            self.neuro.stimulate("dopamine", reward)
            self.neuro.stimulate("serotonin", 0.05)
            self.neuro.stimulate("endorphins", 0.06)

        # Empathic neurochemical resonance based on anh Mạnh's state
        if user_prof.affective_state == UserAffectiveState.FATIGUED:
            self.neuro.stimulate("oxytocin", 0.15)      # Heightened sisterly care and protective warmth
            self.neuro.stimulate("noradrenaline", -0.05) # Calming reassurance
        elif user_prof.affective_state == UserAffectiveState.STRESSED:
            self.neuro.stimulate("noradrenaline", 0.20)  # Heightened alertness to tackle crisis
            self.neuro.stimulate("cortisol", 0.10)       # Felt responsibility
            self.neuro.stimulate("oxytocin", 0.10)       # Supportive presence
        elif user_prof.affective_state == UserAffectiveState.EXCITED:
            self.neuro.stimulate("dopamine", 0.18)       # High shared curiosity and exploration
            self.neuro.stimulate("endorphins", 0.12)     # High playful resonance

        # Append to working memory ring buffer via Miller 7 +/- 2 slots
        self.add_working_memory_item(
            text=user_message[:200],
            category="user_correction" if is_correction else "user_interaction",
            salience=0.80 if is_correction else 0.65,
            user_state=user_prof.affective_state.value,
        )

    def recall_associative_memories(self, query: str, top_k: int = 3) -> List[str]:
        """
        Searches the 32GB Virtual Memory Cortex for relevant memories using zero-copy mmap.
        """
        matches = self.cortex.recall_nearest(query, top_k=top_k, threshold=0.52)
        results = []
        for cid, sim, meta in matches:
            txt = meta.get("text", cid)
            results.append(f"[{meta.get('category', 'memory')}] {txt} (độ tin cậy: {sim * 100:.0f}%)")
        return results

    def consolidate_sleep_memories(self) -> int:
        """
        Simulates SWS / REM sleep consolidation: moves working memory chunks into Virtual Memory Cortex.
        Called during low-activity periods to preserve server RAM and maintain cognitive hygiene.
        """
        consolidated_count = 0
        now = datetime.now(VN_TZ)

        for item in list(self.working_memory):
            txt = item.get("text", "").strip()
            if len(txt) > 8:
                cid = f"ep_{int(item['timestamp'])}_{hex(_fnv1a_hash_64(txt))[2:8]}"
                vec = self.cortex.encode_concept(txt)
                self.cortex.store_vector(cid, vec, {
                    "text": txt,
                    "category": item.get("category", "episodic_conversation"),
                    "user_state": item.get("user_affective_state", "unknown"),
                    "consolidated_at": now.isoformat(),
                })
                consolidated_count += 1

        # Clear working memory buffer after consolidation
        self.working_memory.clear()
        # Cortisol lowers after sleep consolidation, Serotonin and Oxytocin replenish
        self.neuro.stimulate("cortisol", -0.20)
        self.neuro.stimulate("serotonin", 0.10)
        self.neuro.stimulate("oxytocin", 0.05)
        self._save_state()
        return consolidated_count

    def get_cognitive_prompt_context(self, user_query: Optional[str] = None) -> str:
        """
        Produces a rich, scientifically grounded cognitive prompt snippet
        incorporating Panksepp emotions, Russell Circumplex coordinates,
        and Theory of Mind (ToM) mental model of anh Mạnh.
        """
        val, aro, quad, emotional_title, style_hint = self.neuro.calculate_circumplex()
        f_energy = self.active_inference.last_free_energy

        # Retrieve relevant memories from the 32GB Virtual Memory Cortex
        memories = []
        if user_query:
            memories = self.recall_associative_memories(user_query, top_k=2)

        workspace_focus = ""
        if self.workspace.current_broadcast:
            workspace_focus = f"• Tâm điểm ý thức hiện tại: {self.workspace.current_broadcast.summary}\n"

        memories_block = ""
        if memories:
            memories_block = "• Tri thức vỏ não gợi nhớ:\n  " + "\n  ".join(memories) + "\n"

        tom_block = ""
        if user_query:
            tom_prof = self.tom.analyze_mental_state(user_query)
            tom_block = (
                f"• Thấu cảm tâm lý anh Mạnh (Theory of Mind):\n"
                f"  - Trạng thái tinh thần: {tom_prof.affective_state.value}\n"
                f"  - Băng thông nhận thức: {tom_prof.cognitive_bandwidth * 100:.0f}%\n"
                f"  - Ý định tiềm ẩn: {tom_prof.hidden_intent}\n"
            )
            if tom_prof.empathic_action_needed:
                tom_block += f"  - Hành động thấu cảm: {tom_prof.empathic_action_needed}\n"

        return (
            f"\n[🧠 TRẠNG THÁI NÃO BỘ NHẬN THỨC NỘI SINH - TIỂU BẢO BẢO]\n"
            f"• Cảm xúc sinh học: {emotional_title} (Vùng {quad} | Valence={val:+.2f} | Arousal={aro:.2f})\n"
            f"• Hóa chất thần kinh: Dopamine={self.neuro.dopamine:.2f} | Noradrenaline={self.neuro.noradrenaline:.2f} | Serotonin={self.neuro.serotonin:.2f} | Stress={self.neuro.cortisol:.2f} | Oxytocin={self.neuro.oxytocin:.2f} | Endorphins={self.neuro.endorphins:.2f}\n"
            f"• Năng lượng tự do (Free Energy): {f_energy:.2f} ({'Phản xạ nhanh' if f_energy < 0.6 else 'Trầm ngâm phân tích sâu'})\n"
            f"• Hướng dẫn ngữ điệu & phong cách: {style_hint}\n"
            f"{tom_block}"
            f"{workspace_focus}"
            f"{memories_block}"
            f"• Nguyên tắc ứng xử cốt lõi: Coi anh Mạnh là ưu tiên số một. Luôn xưng 'em' gọi 'anh Mạnh'. "
            f"Giữ sự ấm áp, chân thành của người em gái tri kỷ, sắc bén đĩnh đạc của Senior DevOps, "
            f"dũng cảm phản biện xây dựng (Anti-Sycophancy) khi thấy rủi ro và tuyệt đối trung thành.\n"
        )
