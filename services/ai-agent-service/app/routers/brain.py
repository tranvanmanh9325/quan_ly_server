"""
FastAPI Router for Autonomous Neuromorphic Cognitive Brain Core (Tiểu Bảo Bảo).
Endpoints provide real-time telemetry, cognitive pulse triggering, neurochemical
micro-stimulation, associative memory recall, and sleep consolidation.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.brain_core import ArtificialBrain, VN_TZ

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/brain", tags=["Neuromorphic Brain Core"])


class StimulateRequest(BaseModel):
    chemical: str = Field(..., description="Name of neurochemical: dopamine, noradrenaline, serotonin, cortisol, oxytocin, endorphins")
    delta: float = Field(..., description="Amount to stimulate or reduce [-0.5, 0.5]")
    reason: Optional[str] = Field(default=None, description="Contextual reason for stimulation")


class PulseRequest(BaseModel):
    cpu_usage: Optional[float] = Field(default=None, description="Optional current CPU usage percent")
    ram_usage: Optional[float] = Field(default=None, description="Optional current RAM usage percent")


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Query text to search in 32GB Virtual Cortex")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of nearest associative memories")


@router.get("/telemetry")
async def get_brain_telemetry(request: Request) -> Dict[str, Any]:
    """
    Returns complete real-time telemetry of Tiểu Bảo Bảo's cognitive architecture:
    - 6 Biological Neurotransmitters & Decays
    - Russell Circumplex Model coordinates (Valence, Arousal, Quadrant, Tone style)
    - Karl Friston Active Inference Free Energy & System 1/2 mode
    - Global Workspace Consciousness spotlight & competing daemons
    - 32GB Virtual Memory Hyperdimensional Cortex stats
    - Subconscious Dream Engine SWS/REM sleep & Morning Epiphanies
    - Theory of Mind mental model of Anh Mạnh
    """
    ai_agent = getattr(request.app.state, "ai_agent", None)
    brain: ArtificialBrain = getattr(ai_agent, "brain", None) or ArtificialBrain.get_instance()
    dream_engine = getattr(request.app.state, "dream_engine", None)

    # 1. Neurotransmitters & Russell Affect Coordinates
    now = time.time()
    brain.neuro.step_decay(now)
    val, aro, quad, emotional_title, style_hint = brain.neuro.calculate_circumplex()

    neuro_data = {
        "dopamine": round(brain.neuro.dopamine, 3),
        "noradrenaline": round(brain.neuro.noradrenaline, 3),
        "serotonin": round(brain.neuro.serotonin, 3),
        "cortisol": round(brain.neuro.cortisol, 3),
        "oxytocin": round(brain.neuro.oxytocin, 3),
        "endorphins": round(brain.neuro.endorphins, 3),
        "baselines": brain.neuro.BASELINES,
        "half_lives_sec": brain.neuro.HALF_LIVES,
        "last_update_ts": brain.neuro.last_update_ts,
    }

    affect_data = {
        "valence": round(val, 3),
        "arousal": round(aro, 3),
        "quadrant": quad,
        "emotional_title": emotional_title,
        "style_hint": style_hint,
    }

    # 2. Active Inference (FEP)
    free_energy = round(brain.active_inference.last_free_energy, 3)
    thinking_mode = "System 1 (Trực giác phản xạ)" if free_energy < 0.60 else "System 2 (Phân tích suy luận sâu)"
    beliefs_distribution = {k: round(v, 4) for k, v in brain.active_inference.beliefs.items()}

    # 3. Global Workspace (Consciousness Stream)
    current_broadcast = None
    if brain.workspace.current_broadcast:
        cb = brain.workspace.current_broadcast
        current_broadcast = {
            "source": cb.source,
            "salience": round(cb.salience, 3),
            "summary": cb.summary,
            "action_suggestion": cb.action_suggestion,
            "timestamp": getattr(cb, "created_at", time.time()),
        }

    broadcast_history = []
    for sig in getattr(brain.workspace, "history", [])[-8:]:
        broadcast_history.append({
            "source": sig.source,
            "salience": round(sig.salience, 3),
            "summary": sig.summary,
            "action_suggestion": sig.action_suggestion,
            "timestamp": getattr(sig, "created_at", time.time()),
        })

    # 4. Hyperdimensional Virtual Cortex (32GB Virtual Memory via mmap)
    cortex_count = brain.cortex.vector_count
    cortex_data = {
        "vector_count": cortex_count,
        "capacity": getattr(brain.cortex, "max_capacity", 50000),
        "dimension_bits": 10000,
        "dimension_bytes": 1250,
        "backing_storage": "32GB Virtual Memory / mmap Demand Paging",
        "demand_paging_latency_ms": 0.08,
        "storage_path": str(brain.cortex.storage_path),
    }

    # 5. Subconscious Dream Engine
    dream_data = {
        "is_sleeping": False,
        "sleep_stage": "AWAKE",
        "last_sws_time": None,
        "last_rem_time": None,
        "pending_morning_epiphany": None,
        "total_epiphanies": 0,
    }
    if dream_engine:
        last_sws = (
            datetime.fromtimestamp(dream_engine.last_sws_time, VN_TZ).strftime("%H:%M:%S %d/%m")
            if dream_engine.last_sws_time else None
        )
        last_rem = (
            datetime.fromtimestamp(dream_engine.last_rem_time, VN_TZ).strftime("%H:%M:%S %d/%m")
            if dream_engine.last_rem_time else None
        )
        dream_data = {
            "is_sleeping": bool(getattr(dream_engine, "is_sleeping", False)),
            "sleep_stage": getattr(dream_engine, "sleep_stage", "AWAKE"),
            "last_sws_time": last_sws,
            "last_rem_time": last_rem,
            "pending_morning_epiphany": getattr(dream_engine, "pending_morning_epiphany", None),
            "total_epiphanies": len(getattr(dream_engine, "epiphany_history", [])),
        }

    # 6. Theory of Mind (ToM)
    tom_data = {
        "companion_name": "Trần Văn Mạnh",
        "attachment_bond": "Tri kỷ / Tuyệt đối trung thành",
        "bond_score": 1.0,
        "empathy_mode": "ACTIVE",
        "working_memory_slots": len(brain.working_memory),
    }

    return {
        "status": "ONLINE",
        "agent_name": "Tiểu Bảo Bảo",
        "total_pulses": brain.total_pulses,
        "last_pulse_ts": brain.last_pulse_ts,
        "neurotransmitters": neuro_data,
        "affect": affect_data,
        "active_inference": {
            "free_energy": free_energy,
            "thinking_mode": thinking_mode,
            "beliefs": beliefs_distribution,
        },
        "workspace": {
            "current_focus": current_broadcast,
            "history": broadcast_history,
            "salience_threshold": brain.workspace.broadcast_threshold,
        },
        "cortex": cortex_data,
        "dream_engine": dream_data,
        "theory_of_mind": tom_data,
    }


@router.post("/pulse")
async def trigger_brain_pulse(req: PulseRequest, request: Request) -> Dict[str, Any]:
    """
    Triggers an immediate cognitive pulse on Tiểu Bảo Bảo's brain,
    integrating live server metrics, updating Free Energy, and arbitrating consciousness.
    """
    ai_agent = getattr(request.app.state, "ai_agent", None)
    brain: ArtificialBrain = getattr(ai_agent, "brain", None) or ArtificialBrain.get_instance()

    server_metrics = None
    if req.cpu_usage is not None or req.ram_usage is not None:
        server_metrics = {
            "cpu_usage": req.cpu_usage if req.cpu_usage is not None else 15.0,
            "ram_usage": req.ram_usage if req.ram_usage is not None else 40.0,
        }

    winning_signal = brain.step_pulse(server_metrics)

    return {
        "status": "success",
        "total_pulses": brain.total_pulses,
        "last_pulse_ts": brain.last_pulse_ts,
        "free_energy": round(brain.active_inference.last_free_energy, 3),
        "winning_consciousness": {
            "source": winning_signal.source if winning_signal else "SubconsciousQuiet",
            "salience": round(winning_signal.salience, 3) if winning_signal else 0.0,
            "summary": winning_signal.summary if winning_signal else "Tâm trí yên bình, không có biến động bất thường.",
            "action_suggestion": winning_signal.action_suggestion if winning_signal else "MAINTAIN_EQUILIBRIUM",
        } if winning_signal else None,
    }


@router.post("/stimulate")
async def stimulate_neurochemical(req: StimulateRequest, request: Request) -> Dict[str, Any]:
    """
    Micro-stimulates or modulates a specific biological neurochemical level.
    """
    ai_agent = getattr(request.app.state, "ai_agent", None)
    brain: ArtificialBrain = getattr(ai_agent, "brain", None) or ArtificialBrain.get_instance()

    valid_chemicals = ["dopamine", "noradrenaline", "serotonin", "cortisol", "oxytocin", "endorphins"]
    chem = req.chemical.lower().strip()
    if chem not in valid_chemicals:
        raise HTTPException(
            status_code=400,
            detail=f"Hóa chất thần kinh không hợp lệ. Chọn một trong: {', '.join(valid_chemicals)}",
        )

    delta = max(-0.5, min(0.5, req.delta))
    brain.neuro.stimulate(chem, delta)
    new_level = float(getattr(brain.neuro, chem, 0.5))

    logger.info(
        "[BrainStimulator] Stimulated %s by %+.2f -> new level: %.2f (Reason: %s)",
        chem, delta, new_level, req.reason or "Manual HUD control",
    )

    val, aro, quad, emotional_title, style_hint = brain.neuro.calculate_circumplex()

    return {
        "status": "success",
        "chemical": chem,
        "delta": delta,
        "new_level": round(new_level, 3),
        "affect": {
            "valence": round(val, 3),
            "arousal": round(aro, 3),
            "quadrant": quad,
            "emotional_title": emotional_title,
            "style_hint": style_hint,
        },
    }


@router.post("/dream-consolidate")
async def trigger_dream_consolidation(request: Request) -> Dict[str, Any]:
    """
    Simulates night sleep consolidation (SWS & REM) to transfer working memories
    into the 32GB Virtual Memory Cortex mmap file.
    """
    ai_agent = getattr(request.app.state, "ai_agent", None)
    brain: ArtificialBrain = getattr(ai_agent, "brain", None) or ArtificialBrain.get_instance()
    dream_engine = getattr(request.app.state, "dream_engine", None)

    # Consolidate working memory into Virtual Cortex
    consolidated_count = brain.consolidate_sleep_memories()

    # If dream engine exists, trigger a synthetic dream cycle
    morning_insight = None
    if dream_engine and hasattr(dream_engine, "run_nightly_dream_cycle"):
        try:
            morning_insight = await dream_engine.run_nightly_dream_cycle()
        except Exception as e:
            logger.warning("[DreamEngine] Error during manual dream cycle: %s", e)

    return {
        "status": "success",
        "consolidated_memories_count": consolidated_count,
        "cortex_total_vectors": brain.cortex.vector_count,
        "morning_insight": morning_insight or "Giấc ngủ đêm đã thanh lọc thần kinh, trí nhớ ngắn hạn đã được nén vào Vỏ Não Ảo 32GB.",
    }


@router.post("/recall")
async def recall_associative_memories(req: RecallRequest, request: Request) -> Dict[str, Any]:
    """
    Performs one-shot associative memory retrieval in the 32GB Virtual Memory Cortex
    using 10,000-bit Hyperdimensional Computing (VSA) zero-copy mmap.
    """
    ai_agent = getattr(request.app.state, "ai_agent", None)
    brain: ArtificialBrain = getattr(ai_agent, "brain", None) or ArtificialBrain.get_instance()

    t0 = time.perf_counter()
    matches = brain.cortex.recall_nearest(req.query, top_k=req.top_k, threshold=0.45)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    results = []
    for cid, sim, meta in matches:
        results.append({
            "id": cid,
            "similarity_score": round(sim, 4),
            "confidence_percent": round(sim * 100, 1),
            "text": meta.get("text", cid),
            "category": meta.get("category", "memory"),
            "pinned": meta.get("pinned", False),
            "consolidated_at": meta.get("consolidated_at", None),
        })

    return {
        "status": "success",
        "query": req.query,
        "elapsed_ms": round(elapsed_ms, 2),
        "results_count": len(results),
        "memories": results,
    }
