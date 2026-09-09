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


if __name__ == "__main__":
    print("Testing test_neurotransmitter_decay_and_stimulation...")
    test_neurotransmitter_decay_and_stimulation()
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

    print("\nALL 6 NEUROMORPHIC BRAIN CORE TESTS PASSED WITH 100% SUCCESS!")
