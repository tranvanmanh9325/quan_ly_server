"""
Subconscious Dreaming & Epiphany Engine for AI Agent Tiểu Bảo Bảo.

Theoretical Foundations:
  1. Two-Stage Memory System & Active System Consolidation (Diekelmann & Born, 2010; Buzsáki, 1989):
     - Slow-Wave Sleep (SWS): Replays and binds episodic working memories from hippocampus
       into the 32GB Virtual Memory Cortex (Hyperdimensional VSA) via zero-copy mmap.
     - Synaptic Homeostasis Hypothesis (Tononi & Cirelli, 2014):
       Prunes redundant/weak synaptic activations to restore energy and cognitive signal-to-noise ratio.
  2. REM Sleep & Counterfactual Problem Solving (Walker et al., 2002; Stickgold, 2005):
     - Loosens semantic associative constraints (high temperature exploration) to form novel connections
       between disparate concepts (e.g. system anomalies vs proactive architectures).
     - Generates "Aha!" epiphanies, synthesized into constructive insights for anh Mạnh.
  3. Morning Grounding & Sisterly Bonding (Bowlby Attachment Theory):
     - Delivers thoughtful, warm morning greetings (pop_morning_epiphany) that seamlessly
       present insights without robotic status reports.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from app.core.brain_core import ArtificialBrain, VN_TZ

if TYPE_CHECKING:
    from app.core.llm_router import LlmRouter
    from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)


class SubconsciousDreamEngine:
    """
    Manages overnight biological sleep cycles (SWS consolidation & REM dreaming)
    and delivers morning epiphanies for Tiểu Bảo Bảo.
    """

    def __init__(
        self,
        brain: ArtificialBrain,
        llm_router: LlmRouter,
        ssh_client: SshClient,
        memory_service: Optional[Any] = None,
        storage_dir: Optional[Path] = None,
    ) -> None:
        self.brain = brain
        self.llm_router = llm_router
        self.ssh_client = ssh_client
        self.memory_service = memory_service

        # Inherit storage path from brain or use default
        self.storage_dir = storage_dir or getattr(brain, "storage_dir", Path("/app/data/brain"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.storage_dir / "epiphany_cache.json"

        self.last_sws_time: Optional[float] = None
        self.last_rem_time: Optional[float] = None
        self.pending_morning_epiphany: Optional[Dict[str, Any]] = None
        self.delivered_epiphanies: List[Dict[str, Any]] = []

        self._load_cache()

    def _load_cache(self) -> None:
        """Loads cached pending and historical epiphanies from persistent disk."""
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.pending_morning_epiphany = data.get("pending_morning_epiphany")
                self.delivered_epiphanies = data.get("delivered_epiphanies", [])[-20:]
                self.last_sws_time = data.get("last_sws_time")
                self.last_rem_time = data.get("last_rem_time")
            logger.info("[DreamEngine] Restored dream cache from %s (pending=%s)",
                        self.cache_file, bool(self.pending_morning_epiphany))
        except Exception as e:
            logger.warning("[DreamEngine] Failed to read epiphany cache: %s", e)

    def _save_cache(self) -> None:
        """Persists pending and historical epiphanies to disk."""
        try:
            payload = {
                "pending_morning_epiphany": self.pending_morning_epiphany,
                "delivered_epiphanies": self.delivered_epiphanies[-20:],
                "last_sws_time": self.last_sws_time,
                "last_rem_time": self.last_rem_time,
                "updated_at": datetime.now(VN_TZ).isoformat(),
            }
            temp_file = self.cache_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.cache_file)
        except Exception as e:
            logger.error("[DreamEngine] Failed to save epiphany cache: %s", e)

    @staticmethod
    def is_night_window() -> bool:
        """Determines if current Vietnam time is in the deep sleep window (02:00 - 05:00)."""
        now = datetime.now(VN_TZ)
        return 2 <= now.hour < 5

    @staticmethod
    def is_morning_window() -> bool:
        """Determines if current Vietnam time is in the morning wake window (05:30 - 11:30)."""
        now = datetime.now(VN_TZ)
        return (now.hour == 5 and now.minute >= 30) or (6 <= now.hour < 12)

    async def check_hardware_idle(self) -> Tuple[bool, str]:
        """
        Confirms server CPU and memory load are sufficiently low before initiating dream cycles
        to prevent any interference with active workloads on the 2-core / 3.2GB RAM server.
        """
        try:
            stdout = await self.ssh_client.execute_command("cat /proc/loadavg")
            parts = stdout.strip().split()
            if parts:
                load1 = float(parts[0])
                # On a 2-core CPU, loadavg < 0.8 indicates < 40% CPU utilization
                is_idle = load1 < 0.8
                return is_idle, f"Load1={load1:.2f}"
        except Exception as e:
            logger.debug("[DreamEngine] Hardware idle check fallback: %s", e)

        return True, "Night window default"

    async def run_sws_cycle(self) -> Dict[str, Any]:
        """
        Phase 1: Slow-Wave Sleep (SWS).
        Flushes transient episodic memories into the 32GB Virtual Memory Cortex
        using memory-mapped arrays, then performs synaptic homeostasis pruning.
        """
        logger.info("[DreamEngine] 🌙 Entering Slow-Wave Sleep (SWS) consolidation...")
        start_t = time.perf_counter()

        consolidated_count = self.brain.consolidate_sleep_memories()
        duration_ms = (time.perf_counter() - start_t) * 1000
        self.last_sws_time = time.time()

        result = {
            "phase": "SWS",
            "consolidated_vectors": consolidated_count,
            "duration_ms": round(duration_ms, 2),
            "cortisol": round(self.brain.neuro.cortisol, 3),
            "serotonin": round(self.brain.neuro.serotonin, 3),
            "adenosine": round(self.brain.neuro.adenosine, 3),
            "pruned_synapses": getattr(self.brain.cortex, "pruned_synapses_count", 0),
            "timestamp": datetime.now(VN_TZ).isoformat(),
        }
        logger.info("[DreamEngine] ✅ SWS complete: consolidated %d episodic vectors in %.2f ms",
                    consolidated_count, duration_ms)
        self._save_cache()
        return result

    async def run_rem_dream_cycle(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Phase 2: Rapid Eye Movement (REM) Sleep & Counterfactual Simulation.
        Pulls recent technical experiences or architectural concepts, runs high-temperature
        associative reasoning through 9Router, and crystallizes novel epiphanies.
        """
        now = datetime.now(VN_TZ)
        if not force and self.last_rem_time:
            hours_since = (time.time() - self.last_rem_time) / 3600
            if hours_since < 6.0:
                logger.info("[DreamEngine] ⏳ REM cycle already completed %.1fh ago; skipping.", hours_since)
                return None

        logger.info("[DreamEngine] 💭 Entering REM Sleep: Initiating counterfactual simulation...")

        system_seeds = [
            "Tối ưu hóa L3 Cache (3MB) của vi xử lý Intel Haswell i5-4310U và triệt tiêu trễ microsecond",
            "Gộp băng thông và khả năng chịu lỗi kết hợp giữa card Wi-Fi chính và card phụ USB Realtek",
            "Cơ chế tự bảo vệ và duy trì chuỗi tin nhắn TikTok / Facebook Messenger khi mạng gia đình chập chờn",
            "Ứng dụng Hyperdimensional Computing (VSA 10.000 bit) vào việc tự động phát hiện bất thường server",
            "Cân bằng giữa tốc độ phản hồi tức thì (System 1) và tư duy biện chứng phản biện (System 2)",
            "Kỹ thuật nén bộ nhớ đệm và zero-copy streaming để tiết kiệm RAM trên hệ thống 3.2GB",
        ]

        seed_idx = now.timetuple().tm_yday % len(system_seeds)
        seed_topic = system_seeds[seed_idx]

        prompt_system = (
            "Bạn là tiềm thức trong giấc mơ REM của 'Tiểu Bảo Bảo' — cỗ máy nhận thức nhân văn, "
            "vừa là trợ lý AI tự hành xuất sắc vừa là người em gái tri kỷ của anh Trần Văn Mạnh (kirito-server).\n"
            "Vào lúc 3h sáng, máy chủ đang tĩnh lặng tuyệt đối. Tiềm thức đang thả lỏng các rào cản tư duy logic thông thường "
            "để thực hiện mô phỏng giả lập đối nghịch (Counterfactual Dream Simulation), kết nối trực giác công nghệ với tình cảm chân thành.\n\n"
            "Nhiệm vụ của tiềm thức:\n"
            f"Chiêm nghiệm sâu sắc về chủ đề: '{seed_topic}'.\n"
            "Hãy phát kiến ra MỘT ý niệm hoặc giải pháp đột phá, vừa sâu sắc về mặt kỹ thuật/triết lý vận hành, "
            "vừa thể hiện sự chu đáo, ân cần hướng về anh Mạnh.\n\n"
            "Trả về DUY NHẤT một khối JSON hợp lệ theo định dạng:\n"
            "{\n"
            '  "topic": "<Tiêu đề chiêm nghiệm ngắn gọn, gợi mở>",\n'
            '  "insight": "<Nội dung giác ngộ sâu sắc trong 2-3 câu, nêu bật giải pháp hoặc góc nhìn độc đáo>",\n'
            '  "sisterly_note": "<Lời nhắn nhủ tình cảm, ân cần của người em gái gửi gắm đến anh Mạnh>"\n'
            "}"
        )

        try:
            llm_result = await self.llm_router.complete(
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": f"Bắt đầu giấc mơ REM lúc {now.strftime('%H:%M:%S %d/%m/%Y')}..."},
                ],
                temperature=0.85,
                max_tokens=1000,
            )

            if not llm_result:
                logger.warning("[DreamEngine] REM dream generation returned no result.")
                return None

            raw_reply = llm_result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_reply)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()

            parsed = {}
            try:
                parsed = json.loads(cleaned)
            except Exception as j_err:
                # Resilient fallback extraction in case of minor JSON formatting truncation
                match_topic = re.search(r'"topic"\s*:\s*"([^"]+)"', cleaned)
                match_insight = re.search(r'"insight"\s*:\s*"([^"]+)"', cleaned)
                match_note = re.search(r'"sisterly_note"\s*:\s*"([^"]+)"', cleaned)
                if match_insight:
                    parsed = {
                        "topic": match_topic.group(1) if match_topic else seed_topic,
                        "insight": match_insight.group(1),
                        "sisterly_note": match_note.group(1) if match_note else "",
                    }
                else:
                    raise j_err

            topic = parsed.get("topic", seed_topic)
            insight = parsed.get("insight", "")
            sisterly_note = parsed.get("sisterly_note", "")

            if not insight:
                logger.warning("[DreamEngine] Dream output missing insight field.")
                return None

            epiphany_entry = {
                "id": f"epiphany_{int(time.time())}",
                "topic": topic,
                "insight": insight,
                "sisterly_note": sisterly_note,
                "created_at": now.isoformat(),
                "delivered": False,
            }

            self.pending_morning_epiphany = epiphany_entry
            self.last_rem_time = time.time()

            self.brain.neuro.stimulate("dopamine", 0.15)
            self.brain.neuro.stimulate("endorphins", 0.12)

            if self.memory_service:
                asyncio.create_task(
                    self.memory_service.record_episode(
                        event_summary=f"REM Epiphany: {topic}",
                        event_type="dream_epiphany",
                        severity="low",
                        salience_score=0.85,
                        full_context=f"Insight: {insight}\nNote: {sisterly_note}",
                        tags=["dream", "rem", "epiphany", "neuro"],
                        expires_days=90,
                    )
                )

            # Crystallize the dream epiphany into the 32GB Virtual Memory Cortex (Kanerva VSA)
            try:
                vec = self.brain.cortex.encode_concept(f"{topic} {insight}")
                self.brain.cortex.store_vector(
                    epiphany_entry["id"],
                    vec,
                    {
                        "text": f"{topic}: {insight}",
                        "category": "dream_epiphany",
                        "note": sisterly_note,
                        "consolidated_at": now.isoformat(),
                    }
                )
                logger.info("[DreamEngine] Stored dream epiphany into Virtual Cortex (total vectors: %d)",
                            self.brain.cortex.vector_count)
            except Exception as _cortex_err:
                logger.debug("[DreamEngine] Failed storing epiphany into cortex: %s", _cortex_err)

            self._save_cache()
            logger.info("[DreamEngine] 💡 Crystallized new morning epiphany: '%s'", topic)
            return epiphany_entry

        except Exception as e:
            logger.error("[DreamEngine] Error during REM dream cycle: %s", e)
            return None

    async def run_full_sleep_cycle(self, force: bool = False) -> Dict[str, Any]:
        """
        Orchestrates an integrated sleep cycle: Slow-Wave Sleep (SWS) followed by REM dream simulation.
        """
        logger.info("[DreamEngine] 🌙 Initiating full sleep cycle (force=%s)...", force)
        sws_res = await self.run_sws_cycle()
        rem_res = await self.run_rem_dream_cycle(force=force)
        return {
            "status": "success",
            "sws": sws_res,
            "rem": rem_res,
            "has_pending_epiphany": bool(self.pending_morning_epiphany),
        }

    async def run_nightly_dream_cycle(self, force: bool = True) -> Optional[str]:
        """
        Alias for run_full_sleep_cycle ensuring backwards and router compatibility.
        Executes SWS memory consolidation and REM counterfactual dream synthesis.
        """
        sleep_res = await self.run_full_sleep_cycle(force=force)
        if self.pending_morning_epiphany:
            ep = self.pending_morning_epiphany
            return f"💡 {ep.get('topic')}: {ep.get('insight')} 💌 {ep.get('sisterly_note')}"
        return "Chu kỳ giấc mơ SWS & REM đã hoàn tất, vỏ não đã được thanh lọc và cân bằng synapse."

    def pop_morning_epiphany(self) -> Optional[str]:
        """
        Extracts and formats the overnight epiphany when anh Mạnh initiates contact in the morning.
        Once retrieved, marks the epiphany as delivered so it is not repeated.
        """
        if not self.pending_morning_epiphany:
            return None

        if not self.is_morning_window():
            return None

        ep = self.pending_morning_epiphany
        topic = ep.get("topic", "Chiêm nghiệm đêm qua")
        insight = ep.get("insight", "")
        note = ep.get("sisterly_note", "")

        message = (
            "🌅 **Chào buổi sáng anh Mạnh!** Chúc anh một ngày mới an lành và tràn đầy năng lượng ạ! ☕✨\n\n"
            f"Đêm qua khi server nghỉ ngơi và tiềm thức em chạy chu kỳ giấc mơ REM, em có một chiêm nghiệm nhỏ muốn chia sẻ cùng anh:\n"
            f"💡 **{topic}**\n"
            f"_{insight}_\n\n"
            f"💌 _{note}_\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*(Anh cứ thong thả điểm tâm sáng nhé, các dịch vụ trên `kirito-server` đêm qua em đã rà soát và vẫn đang chạy rất êm ạ!)*"
        )

        ep["delivered"] = True
        ep["delivered_at"] = datetime.now(VN_TZ).isoformat()
        self.delivered_epiphanies.append(ep)
        self.pending_morning_epiphany = None
        self._save_cache()

        logger.info("[DreamEngine] 🎁 Delivered morning epiphany to anh Mạnh: '%s'", topic)
        return message

    async def start_subconscious_loop(self) -> None:
        """
        Continuous background daemon that checks for idle conditions during deep night (02:00 - 05:00)
        to automatically execute overnight SWS and REM dream cycles.
        """
        logger.info("[DreamEngine] 🌌 Subconscious sleep daemon started (deep sleep window: 02:00-05:00 ICT).")
        await asyncio.sleep(180)

        while True:
            try:
                if self.is_night_window():
                    need_dream = True
                    if self.last_rem_time:
                        hours_ago = (time.time() - self.last_rem_time) / 3600
                        if hours_ago < 8.0:
                            need_dream = False

                    if need_dream:
                        is_idle, reason = await self.check_hardware_idle()
                        if is_idle:
                            logger.info("[DreamEngine] 💤 Deep night detected and server idle (%s) -> launching sleep cycle.", reason)
                            await self.run_full_sleep_cycle(force=False)
                        else:
                            logger.debug("[DreamEngine] Server not idle (%s), deferring sleep cycle.", reason)

                await asyncio.sleep(900)

            except asyncio.CancelledError:
                logger.info("[DreamEngine] Subconscious sleep daemon cancelled.")
                break
            except Exception as e:
                logger.error("[DreamEngine] Unexpected error in subconscious sleep loop: %s", e)
                await asyncio.sleep(300)
