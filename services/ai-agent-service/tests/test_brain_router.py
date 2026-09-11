"""
Unit tests for Neuromorphic Brain Core FastAPI Router (/api/ai/brain).
Tests telemetry snapshot, pulse trigger, neurochemical stimulation,
associative memory recall, and sleep consolidation endpoints.
"""
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure ai-agent-service directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.brain_core import ArtificialBrain
from app.routers import brain


class TestBrainRouter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name)

        # Safely close existing singleton if open
        if ArtificialBrain._instance and hasattr(ArtificialBrain._instance, "cortex"):
            try:
                ArtificialBrain._instance.cortex.close()
            except Exception:
                pass
        ArtificialBrain._instance = None
        self.brain = ArtificialBrain(storage_dir=self.storage_path)
        ArtificialBrain._instance = self.brain

        self.app = FastAPI()
        self.app.state.ai_agent = type("DummyAiAgent", (), {"brain": self.brain})()
        self.app.include_router(brain.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        try:
            if hasattr(self.brain, "cortex"):
                self.brain.cortex.close()
        except Exception:
            pass
        self.temp_dir.cleanup()
        ArtificialBrain._instance = None

    def test_get_telemetry(self):
        """Test GET /api/ai/brain/telemetry returns all 6 neurochemicals and brain metrics."""
        res = self.client.get("/api/ai/brain/telemetry")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "ONLINE")
        self.assertEqual(data["agent_name"], "Tiểu Bảo Bảo")
        self.assertIn("neurotransmitters", data)
        nt = data["neurotransmitters"]
        self.assertIn("dopamine", nt)
        self.assertIn("noradrenaline", nt)
        self.assertIn("serotonin", nt)
        self.assertIn("cortisol", nt)
        self.assertIn("oxytocin", nt)
        self.assertIn("endorphins", nt)

        self.assertIn("affect", data)
        self.assertIn("valence", data["affect"])
        self.assertIn("arousal", data["affect"])

        self.assertIn("active_inference", data)
        self.assertIn("free_energy", data["active_inference"])

        self.assertIn("cortex", data)
        self.assertGreaterEqual(data["cortex"]["vector_count"], 1)

    def test_trigger_pulse(self):
        """Test POST /api/ai/brain/pulse updates pulse counter and returns winning signal."""
        initial_pulses = self.brain.total_pulses
        res = self.client.post("/api/ai/brain/pulse", json={"cpu_usage": 45.0, "ram_usage": 50.0})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total_pulses"], initial_pulses + 1)
        self.assertIn("free_energy", data)

    def test_stimulate_neurochemical(self):
        """Test POST /api/ai/brain/stimulate modulates target chemical level."""
        old_dopamine = self.brain.neuro.dopamine
        res = self.client.post("/api/ai/brain/stimulate", json={"chemical": "dopamine", "delta": 0.20, "reason": "Test praise"})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["chemical"], "dopamine")
        self.assertAlmostEqual(data["new_level"], old_dopamine + 0.20, places=2)

    def test_stimulate_invalid_chemical(self):
        """Test POST /api/ai/brain/stimulate with invalid chemical returns 400."""
        res = self.client.post("/api/ai/brain/stimulate", json={"chemical": "unknown_chem", "delta": 0.1})
        self.assertEqual(res.status_code, 400)

    def test_dream_consolidate(self):
        """Test POST /api/ai/brain/dream-consolidate runs memory consolidation."""
        self.brain.perceive_user_interaction("Hệ thống kirito-server đã được cấu hình tối ưu mmap.")
        res = self.client.post("/api/ai/brain/dream-consolidate")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["consolidated_memories_count"], 1)

    def test_recall_associative_memories(self):
        """Test POST /api/ai/brain/recall performs associative search in 32GB cortex."""
        res = self.client.post("/api/ai/brain/recall", json={"query": "chủ nhân Trần Văn Mạnh", "top_k": 3})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["query"], "chủ nhân Trần Văn Mạnh")
        self.assertIn("memories", data)
        self.assertGreaterEqual(len(data["memories"]), 1)
        self.assertIn("confidence_percent", data["memories"][0])


if __name__ == "__main__":
    unittest.main()
