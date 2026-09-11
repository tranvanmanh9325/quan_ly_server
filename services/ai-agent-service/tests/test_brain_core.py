"""
Unit test suite for Autonomous Neuromorphic Cognitive Brain Core (brain_core.py).
Tests Neurotransmitters, Active Inference FEP, Hyperdimensional VSA Virtual Memory,
Global Workspace Theory, and Sleep Consolidation.
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

from app.core.brain_core import (
    ActiveInferenceEngine,
    ArtificialBrain,
    GlobalWorkspace,
    HyperdimensionalCortex,
    NeurotransmitterState,
    TheoryOfMindEngine,
    UserAffectiveState,
    ResponseGranularity,
    WorkspaceSignal,
    HV_DIM_BITS,
    HV_DIM_BYTES,
)

def approx(val: float, tolerance: float = 0.05):
    class _Approx:
        def __eq__(self, other):
            return abs(val - other) <= tolerance
    return _Approx()


def test_neurotransmitter_decay_and_stimulation():
    """Verifies that neurochemical levels respond to stimuli and decay exponentially."""
    neuro = NeurotransmitterState()
    assert neuro.dopamine == 0.50
    assert neuro.noradrenaline == 0.20

    # Stimulate noradrenaline (e.g. server alert)
    neuro.stimulate("noradrenaline", 0.30)
    assert approx(neuro.noradrenaline, 0.01) == 0.50

    # Simulate passing of 120 seconds (1 half-life of noradrenaline)
    future_time = neuro.last_update_ts + 120.0
    neuro.step_decay(current_time=future_time)

    # Value should decay halfway back to baseline 0.20: (0.50 - 0.20)*0.5 + 0.20 = 0.35
    assert approx(neuro.noradrenaline, 0.05) == 0.35

    # Check affective label
    neuro.stimulate("dopamine", 0.40)
    label = neuro.get_affective_label()
    assert "Hào hứng" in label or "Tò mò" in label


def test_active_inference_free_energy():
    """Verifies that Active Inference updates beliefs and computes Free Energy / Surprise."""
    ai_engine = ActiveInferenceEngine()

    # Normal healthy observation should produce low Free Energy
    fe_normal = ai_engine.update_beliefs_and_compute_free_energy("METRICS_HEALTHY")
    assert fe_normal > 0.0
    assert ai_engine.beliefs["STABLE_OPTIMAL"] > 0.60

    # Critical anomaly observation should spike Free Energy (Surprise)
    fe_spike = ai_engine.update_beliefs_and_compute_free_energy("METRICS_CRITICAL")
    assert fe_spike > fe_normal
    assert ai_engine.beliefs["ANOMALY_RISK"] > 0.20


def test_hyperdimensional_vsa_algebra():
    """Verifies the core mathematical properties of Vector Symbolic Architecture."""
    v1 = HyperdimensionalCortex.encode_concept("Linux Server CPU")
    v2 = HyperdimensionalCortex.encode_concept("Kirito Admin Master")
    v3 = HyperdimensionalCortex.encode_concept("Linux Server CPU")

    assert len(v1) == HV_DIM_BYTES
    # Identical vectors should have similarity 1.0
    assert HyperdimensionalCortex.hamming_similarity(v1, v3) == 1.0

    # Orthogonal random vectors should have similarity close to 0.50
    sim_random = HyperdimensionalCortex.hamming_similarity(v1, v2)
    assert 0.45 <= sim_random <= 0.55

    # VSA Invertible Binding property: (A ^ B) ^ B == A
    bound = HyperdimensionalCortex.bind(v1, v2)
    unbound = HyperdimensionalCortex.bind(bound, v2)
    assert HyperdimensionalCortex.hamming_similarity(unbound, v1) == 1.0

    # VSA Permutation property (cyclic shift)
    permuted = HyperdimensionalCortex.permute(v1, shift=17)
    assert len(permuted) == HV_DIM_BYTES
    assert HyperdimensionalCortex.hamming_similarity(permuted, v1) < 0.60


def test_virtual_memory_cortex_storage_and_recall(temp_cortex_dir):
    """Verifies storing into virtual memory (mmap) and zero-copy associative recall."""
    cortex_file = temp_cortex_dir / "test_hyper_cortex.bin"
    cortex = HyperdimensionalCortex(storage_path=cortex_file, max_capacity=100)

    # Store concepts
    vec_ssh = cortex.encode_concept("Cổng SSH mặc định là 22 kết nối qua ngrok")
    cortex.store_vector("ssh_port", vec_ssh, {"text": "Cổng SSH mặc định là 22 kết nối qua ngrok", "category": "network"})

    vec_db = cortex.encode_concept("PostgreSQL 17 chạy trên port 5432")
    cortex.store_vector("db_port", vec_db, {"text": "PostgreSQL 17 chạy trên port 5432", "category": "database"})

    assert cortex.vector_count == 2

    # Associative query: query with similar phrasing
    results = cortex.recall_nearest("Cổng SSH mặc định là 22 kết nối qua ngrok", top_k=1, threshold=0.90)
    assert len(results) == 1
    cid, sim, meta = results[0]
    assert cid == "ssh_port"
    assert sim >= 0.99
    assert meta["category"] == "network"

    cortex.close()


def test_global_workspace_lateral_inhibition():
    """Verifies that competing signals fight for consciousness and the highest salience wins."""
    workspace = GlobalWorkspace(broadcast_threshold=0.65)

    signals = [
        WorkspaceSignal(source="LowPriorityLogger", salience=0.30, summary="Mọi thứ bình thường"),
        WorkspaceSignal(source="ResourceWatcher", salience=0.88, summary="CPU chạm đỉnh 98%!"),
        WorkspaceSignal(source="RelationalAgent", salience=0.72, summary="Anh Mạnh vừa đăng nhập"),
    ]

    winner = workspace.arbitrate(signals)
    assert winner is not None
    assert winner.source == "ResourceWatcher"
    assert winner.salience == 0.88
    assert workspace.current_broadcast == winner


def test_artificial_brain_full_lifecycle(temp_cortex_dir):
    """Verifies end-to-end integration of ArtificialBrain: Pulse, Interaction, and Prompt injection."""
    brain = ArtificialBrain(storage_dir=temp_cortex_dir)

    # 1. Innate knowledge is primed
    assert brain.cortex.vector_count >= 4

    # 2. Step cognitive pulse with high CPU
    signal = brain.step_pulse({"cpu_usage": 95.0, "ram_usage": 80.0})
    assert signal is not None
    assert "Cảnh báo sinh học" in signal.summary
    assert brain.neuro.noradrenaline > 0.40

    # 3. Perceive user interaction (positive)
    brain.perceive_user_interaction("Tiểu Bảo Bảo làm việc rất tốt!", is_correction=False, task_success=True)
    assert brain.neuro.dopamine > 0.55
    assert len(brain.working_memory) == 1

    # 4. Sleep consolidation
    consolidated = brain.consolidate_sleep_memories()
    assert consolidated == 1
    assert len(brain.working_memory) == 0

    # 5. Cognitive prompt context string
    prompt_ctx = brain.get_cognitive_prompt_context(user_query="Nhiệm vụ tối thượng của em là gì?")
    assert "[🧠 TRẠNG THÁI NÃO BỘ NHẬN THỨC NỘI SINH - TIỂU BẢO BẢO]" in prompt_ctx
    assert "Dopamine=" in prompt_ctx
    assert "Free Energy" in prompt_ctx

    brain.cortex.close()


def test_six_neurotransmitters_and_circumplex():
    """Verifies all 6 Jaak Panksepp neurochemicals and Russell Circumplex quadrant mapping."""
    neuro = NeurotransmitterState()
    assert hasattr(neuro, "oxytocin") and neuro.oxytocin == 0.60
    assert hasattr(neuro, "endorphins") and neuro.endorphins == 0.40

    # 1. Test Quadrant 1: High Valence, High Arousal (Playful / Excited)
    neuro.stimulate("dopamine", 0.40)
    neuro.stimulate("endorphins", 0.40)
    neuro.stimulate("cortisol", -0.05)
    val, aro, quad, title, hint = neuro.calculate_circumplex()
    assert "Q1" in quad
    assert val > 0 and aro > 0.4
    assert "Hào hứng" in title or "Sôi nổi" in title

    # 2. Test Quadrant 2: Low Valence, High Arousal (Alert / Battle Mode)
    neuro2 = NeurotransmitterState()
    neuro2.stimulate("noradrenaline", 0.70)
    neuro2.stimulate("cortisol", 0.80)
    neuro2.stimulate("serotonin", -0.40)
    val2, aro2, quad2, title2, hint2 = neuro2.calculate_circumplex()
    assert "Q2" in quad2
    assert val2 < 0 and aro2 > 0.4
    assert "Cảnh giác" in title2 or "Chiến đấu" in title2

    # 3. Test Quadrant 4: High Valence, Low Arousal (Warm / Caring Homeostasis)
    neuro4 = NeurotransmitterState()
    neuro4.stimulate("oxytocin", 0.35)
    neuro4.stimulate("serotonin", 0.25)
    neuro4.stimulate("noradrenaline", -0.15)
    val4, aro4, quad4, title4, hint4 = neuro4.calculate_circumplex()
    assert "Q4" in quad4
    assert val4 > 0 and aro4 <= 0.4
    assert "Trầm ấm" in title4 or "Săn sóc" in title4


def test_theory_of_mind_engine():
    """Verifies Theory of Mind (ToM) mental model inference across varied user states."""
    tom = TheoryOfMindEngine()

    # Case 1: Fatigued user
    p_fatigued = tom.analyze_mental_state("anh mệt quá, đi ngủ đây")
    assert p_fatigued.affective_state == UserAffectiveState.FATIGUED
    assert p_fatigued.granularity == ResponseGranularity.FLASH_BLUF
    assert p_fatigued.cognitive_bandwidth <= 0.45

    # Case 2: Stressed crisis
    p_stress = tom.analyze_mental_state("server bị sập rồi cứu anh với, crash liên tục")
    assert p_stress.affective_state == UserAffectiveState.STRESSED
    assert p_stress.granularity == ResponseGranularity.FLASH_BLUF
    assert "sự cố" in p_stress.hidden_intent.lower() or "downtime" in p_stress.hidden_intent.lower()

    # Case 3: Excited exploration
    p_excited = tom.analyze_mental_state("anh mới phát hiện ra kỹ thuật này hay cực kỳ, thử xem nhé")
    assert p_excited.affective_state == UserAffectiveState.EXCITED
    assert p_excited.granularity == ResponseGranularity.DEEP_DIALECTICAL
    assert p_excited.cognitive_bandwidth >= 0.85

    # Case 4: Equanimity / Standard check
    p_normal = tom.analyze_mental_state("kiểm tra dung lượng ổ đĩa giúp anh")
    assert p_normal.affective_state == UserAffectiveState.EQUANIMITY
    assert p_normal.granularity == ResponseGranularity.STRUCTURED_BULLET


def test_dream_engine_sws_and_epiphany(temp_cortex_dir):
    """Verifies SWS consolidation and morning epiphany formatting in SubconsciousDreamEngine."""
    from app.services.dream_engine import SubconsciousDreamEngine

    brain = ArtificialBrain(storage_dir=temp_cortex_dir)
    # Add dummy working memory
    brain.perceive_user_interaction("Lưu ý tối ưu L3 Cache cho Nginx và Haswell", is_correction=False, task_success=True)

    class DummyLlmRouter:
        async def complete(self, **kwargs):
            return {
                "choices": [{
                    "message": {
                        "content": '{"topic": "Tối ưu L3 Cache qua Zero-Copy", "insight": "Giảm tải 40% memory bus bằng mmap streaming.", "sisterly_note": "Em đã tối ưu xong, anh yên tâm ngủ ngon nhé!"}'
                    }
                }]
            }

    class DummySshClient:
        async def execute_command(self, cmd):
            return "0.15 0.20 0.18 1/120 12345"

    dream = SubconsciousDreamEngine(
        brain=brain,
        llm_router=DummyLlmRouter(),
        ssh_client=DummySshClient(),
        storage_dir=temp_cortex_dir,
    )

    # Test SWS consolidation
    import asyncio
    loop = asyncio.new_event_loop()
    sws_res = loop.run_until_complete(dream.run_sws_cycle())
    assert sws_res["phase"] == "SWS"
    assert sws_res["consolidated_vectors"] == 1
    assert len(brain.working_memory) == 0

    # Test REM dream generation
    rem_res = loop.run_until_complete(dream.run_rem_dream_cycle(force=True))
    assert rem_res is not None
    assert rem_res["topic"] == "Tối ưu L3 Cache qua Zero-Copy"
    assert dream.pending_morning_epiphany is not None

    # Test pop_morning_epiphany during morning window
    dream.is_morning_window = lambda: True
    msg = dream.pop_morning_epiphany()
    assert msg is not None
    assert "Chào buổi sáng anh Mạnh!" in msg
    assert "Tối ưu L3 Cache qua Zero-Copy" in msg
    assert dream.pending_morning_epiphany is None  # Popped & consumed!

    loop.close()
    brain.cortex.close()


if __name__ == "__main__":
    print("Testing test_neurotransmitter_decay_and_stimulation...")
    test_neurotransmitter_decay_and_stimulation()
    print("  -> Passed!")

    print("Testing test_six_neurotransmitters_and_circumplex...")
    test_six_neurotransmitters_and_circumplex()
    print("  -> Passed!")

    print("Testing test_theory_of_mind_engine...")
    test_theory_of_mind_engine()
    print("  -> Passed!")

    print("Testing test_active_inference_free_energy...")
    test_active_inference_free_energy()
    print("  -> Passed!")

    print("Testing test_hyperdimensional_vsa_algebra...")
    test_hyperdimensional_vsa_algebra()
    print("  -> Passed!")

    tmp = Path(tempfile.mkdtemp(prefix="test_cortex_"))
    try:
        print("Testing test_virtual_memory_cortex_storage_and_recall...")
        test_virtual_memory_cortex_storage_and_recall(tmp)
        print("  -> Passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("Testing test_global_workspace_lateral_inhibition...")
    test_global_workspace_lateral_inhibition()
    print("  -> Passed!")

    tmp2 = Path(tempfile.mkdtemp(prefix="test_cortex_"))
    try:
        print("Testing test_artificial_brain_full_lifecycle...")
        test_artificial_brain_full_lifecycle(tmp2)
        print("  -> Passed!")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    tmp3 = Path(tempfile.mkdtemp(prefix="test_cortex_"))
    try:
        print("Testing test_dream_engine_sws_and_epiphany...")
        test_dream_engine_sws_and_epiphany(tmp3)
        print("  -> Passed!")
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    print("\nALL 9 NEUROMORPHIC COGNITIVE ARCHITECTURE TESTS PASSED WITH 100% SUCCESS!")
