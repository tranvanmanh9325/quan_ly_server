"""
Pytest configuration and shared fixtures for ai-agent-service test suite.
"""
from pathlib import Path
import pytest


@pytest.fixture
def temp_cortex_dir(tmp_path: Path) -> Path:
    """Provides an isolated temporary directory for HyperdimensionalCortex testing."""
    return tmp_path
