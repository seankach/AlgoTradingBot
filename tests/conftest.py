"""Shared pytest fixtures.

``valid_config_dir`` writes a complete, valid configuration tree to a temp directory so
negative tests can copy and mutate it, differing from the baseline by exactly one field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import VALID_CONFIG, write_config_dir


@pytest.fixture
def valid_config_dir(tmp_path: Path) -> Path:
    """A temp directory containing a complete, valid configuration."""
    return write_config_dir(tmp_path / "config", VALID_CONFIG)
