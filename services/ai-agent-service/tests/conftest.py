"""
Pytest configuration and shared fixtures for ai-agent-service test suite.
"""
from pathlib import Path
from typing import Generator
import pytest

from app.core.brain_core import ArtificialBrain


@pytest.fixture
def temp_cortex_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provides an isolated temporary directory for HyperdimensionalCortex testing with guaranteed cleanup."""
    yield tmp_path
    ArtificialBrain.reset_instance()


@pytest.fixture(autouse=True)
def cleanup_brain_singleton() -> Generator[None, None, None]:
    """Guarantees that any ArtificialBrain singleton is cleanly closed after each test."""
    yield
    ArtificialBrain.reset_instance()

