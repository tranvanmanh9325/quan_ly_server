"""
Empirical Adversarial Stress Test Suite: Cortex & Brain Resource Lifecycle
Author: Challenger 2 (Critic / Specialist)
Target: HyperdimensionalCortex & ArtificialBrain resource leak eradication verification.
"""

import gc
import os
import shutil
import tempfile
import threading
import unittest
import warnings
from pathlib import Path

from app.core.brain_core import ArtificialBrain, HyperdimensionalCortex


class TestCortexAndBrainResourceLifecycleAdversarial(unittest.TestCase):
    """
    Adversarial empirical harness stress-testing resource cleanup,
    Windows file lock release, garbage collection behavior, and exception safety.
    """

    def setUp(self):
        self.test_dirs = []
        ArtificialBrain.reset_instance()

    def tearDown(self):
        ArtificialBrain.reset_instance()
        for d in self.test_dirs:
            if d.exists():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass

    def _make_temp_dir(self) -> Path:
        d = Path(tempfile.mkdtemp(prefix="challenger2_stress_"))
        self.test_dirs.append(d)
        return d

    def test_01_cortex_context_manager_normal(self):
        """Context manager cleans up mmap and file handle on normal exit; file can be deleted."""
        d = self._make_temp_dir()
        file_path = d / "test_cortex.bin"

        with HyperdimensionalCortex(storage_path=file_path) as ctx:
            v = ctx.encode_concept("Test concept")
            ctx.store_vector("concept_1", v, {"salience": 0.8})
            self.assertEqual(ctx.vector_count, 1)

        # On Windows, if file is not closed, os.remove will raise PermissionError
        self.assertTrue(file_path.exists())
        file_path.unlink()
        self.assertFalse(file_path.exists())

    def test_02_cortex_context_manager_with_exception(self):
        """Context manager cleans up mmap and file handle even when an uncaught exception is raised."""
        d = self._make_temp_dir()
        file_path = d / "test_cortex_err.bin"

        with self.assertRaises(ZeroDivisionError):
            with HyperdimensionalCortex(storage_path=file_path) as ctx:
                v = ctx.encode_concept("Should be flushed")
                ctx.store_vector("err_vector", v, {"salience": 0.5})
                _ = 1 / 0

        # Verify file is unlocked and can be deleted immediately
        self.assertTrue(file_path.exists())
        file_path.unlink()
        self.assertFalse(file_path.exists())

    def test_03_brain_context_manager_with_exception(self):
        """ArtificialBrain context manager cleans up cortex when exception occurs."""
        d = self._make_temp_dir()

        with self.assertRaises(RuntimeError):
            with ArtificialBrain(storage_dir=d) as brain:
                brain.perceive_user_interaction("Sự cố khẩn cấp", is_correction=True, task_success=False)
                raise RuntimeError("Simulated cognitive explosion")

        # Entire storage dir should be unpinned from Windows process and deletable
        shutil.rmtree(d)
        self.assertFalse(d.exists())

    def test_04_direct_cortex_gc_sweep_no_warning(self):
        """
        When HyperdimensionalCortex is abandoned without close(), __del__ must safely
        close handles without raising ResourceWarning under -W error::ResourceWarning.
        """
        d = self._make_temp_dir()
        file_path = d / "abandoned_cortex.bin"

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", ResourceWarning)
            ctx = HyperdimensionalCortex(storage_path=file_path)
            _ = ctx.encode_concept("Ephemeral concept")
            del ctx
            gc.collect()

        resource_warnings = [
            w for w in recorded_warnings
            if issubclass(w.category, ResourceWarning) and "unclosed file" in str(w.message).lower()
        ]
        self.assertEqual(len(resource_warnings), 0, f"ResourceWarning triggered: {resource_warnings}")

        # Ensure file lock was released by __del__
        file_path.unlink()
        self.assertFalse(file_path.exists())

    def test_05_direct_brain_gc_sweep_no_warning(self):
        """
        When ArtificialBrain is abandoned without close(), __del__ must cleanly release
        underlying cortex without ResourceWarning.
        """
        d = self._make_temp_dir()

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", ResourceWarning)
            brain = ArtificialBrain(storage_dir=d)
            del brain
            gc.collect()

        resource_warnings = [
            w for w in recorded_warnings
            if issubclass(w.category, ResourceWarning) and "unclosed file" in str(w.message).lower()
        ]
        self.assertEqual(len(resource_warnings), 0, f"ResourceWarning triggered: {resource_warnings}")

        # Directory must be fully unlocked
        shutil.rmtree(d)
        self.assertFalse(d.exists())

    def test_06_singleton_rapid_churn_stress(self):
        """
        Stress test: 50 consecutive cycles of get_instance(), usage, reset_instance(),
        and immediate rmtree() on Windows.
        """
        for i in range(50):
            d = self._make_temp_dir()
            brain = ArtificialBrain.get_instance(storage_dir=d)
            self.assertIs(brain, ArtificialBrain._instance)
            brain.perceive_user_interaction(f"Iteration pulse {i}", is_correction=False, task_success=True)

            # Reset singleton
            ArtificialBrain.reset_instance()
            self.assertIsNone(ArtificialBrain._instance)

            # Must release file lock immediately so directory can be removed
            shutil.rmtree(d)
            self.assertFalse(d.exists())

    def test_07_reset_instance_idempotency(self):
        """reset_instance must be completely idempotent and safe when called repeatedly."""
        d = self._make_temp_dir()
        _ = ArtificialBrain.get_instance(storage_dir=d)

        # Call reset 10 times in a row
        for _ in range(10):
            ArtificialBrain.reset_instance()
            self.assertIsNone(ArtificialBrain._instance)

        shutil.rmtree(d)
        self.assertFalse(d.exists())

    def test_08_close_idempotency(self):
        """Calling close() multiple times on Cortex or Brain must not raise errors."""
        d = self._make_temp_dir()
        cortex = HyperdimensionalCortex(storage_path=d / "cortex_idem.bin")
        cortex.close()
        cortex.close()
        cortex.close()

        brain = ArtificialBrain(storage_dir=d)
        brain.close()
        brain.close()
        brain.close()

        shutil.rmtree(d)

    def test_09_concurrency_singleton_access_and_reset(self):
        """Multi-threaded stress: Concurrent calls to get_instance and reset_instance."""
        d = self._make_temp_dir()
        errors = []

        def worker_access():
            try:
                for _ in range(30):
                    b = ArtificialBrain.get_instance(storage_dir=d)
                    _ = b.neuro.dopamine
            except Exception as e:
                errors.append(e)

        def worker_reset():
            try:
                for _ in range(30):
                    ArtificialBrain.reset_instance()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker_access),
            threading.Thread(target=worker_reset),
            threading.Thread(target=worker_access),
            threading.Thread(target=worker_reset),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors in concurrent access/reset: {errors}")
        ArtificialBrain.reset_instance()
        gc.collect()

    def test_10_cortex_vector_persistence_roundtrip_after_reset(self):
        """
        Verify data integrity across resets:
        Write data -> reset_instance() -> reopen from disk -> verify vectors and metadata are intact.
        """
        d = self._make_temp_dir()
        brain1 = ArtificialBrain.get_instance(storage_dir=d)
        initial_count = brain1.cortex.vector_count
        v = brain1.cortex.encode_concept("Quy trình khôi phục sự cố Database")
        brain1.cortex.store_vector("db_recovery", v, {"priority": "critical", "salience": 0.95})
        self.assertEqual(brain1.cortex.vector_count, initial_count + 1)

        # Reset singleton
        ArtificialBrain.reset_instance()

        # Reopen
        brain2 = ArtificialBrain.get_instance(storage_dir=d)
        self.assertEqual(brain2.cortex.vector_count, initial_count + 1)
        self.assertIn("db_recovery", brain2.cortex.entry_index)
        meta = brain2.cortex.metadata_index.get("db_recovery")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["priority"], "critical")

        ArtificialBrain.reset_instance()
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
