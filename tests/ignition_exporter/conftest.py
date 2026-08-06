"""Shared fixtures for the Ignition exporter test suite.

All committed fixtures are hand-authored and project-agnostic (see
``fixtures/synthetic_ignition.L5X``) -- no proprietary example-project files or
tag names are used by the test suite.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def synthetic_l5x() -> str:
    """Absolute path to the synthetic, project-agnostic L5X fixture."""
    return str(FIXTURES / "synthetic_ignition.L5X")
