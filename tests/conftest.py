"""Shared pytest fixtures.

``valid_config_dir`` writes a complete, valid configuration tree to a temp directory so
negative tests can copy and mutate it, differing from the baseline by exactly one field.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from tests.support import VALID_CONFIG, write_config_dir


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Reset structlog's global config after each test.

    ``configure_logging`` binds ``sys.stdout`` into structlog's process-wide state; under
    ``capsys`` that stream is later closed, so without this reset a logging test would leak
    a closed stream into unrelated tests.
    """
    yield
    structlog.reset_defaults()


@pytest.fixture
def valid_config_dir(tmp_path: Path) -> Path:
    """A temp directory containing a complete, valid configuration."""
    return write_config_dir(tmp_path / "config", VALID_CONFIG)
