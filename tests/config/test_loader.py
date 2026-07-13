"""Unit tests for the YAML config loader."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from qrp.config.loader import ConfigError, load_config
from qrp.config.models import Session
from tests.support import VALID_CONFIG, write_config_dir


def test_loads_valid_directory(valid_config_dir: Path) -> None:
    config = load_config(valid_config_dir)

    assert config.config_version == "test-1"
    assert config.universe.symbols[0].symbol == "TSLA"
    assert config.labels.vertical_barrier_bars_h == 30
    assert Session.OVERNIGHT in config.session.ingest_sessions
    assert Session.OVERNIGHT not in config.session.tradable_sessions
    # Derived path property resolves under data_root.
    assert config.storage.raw_snapshots_dir == Path("data") / "raw_snapshots"


def test_accepts_str_path(valid_config_dir: Path) -> None:
    assert load_config(str(valid_config_dir)).config_version == "test-1"


def test_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config directory not found"):
        load_config(tmp_path / "does_not_exist")


def test_missing_section_file(tmp_path: Path) -> None:
    sections = copy.deepcopy(VALID_CONFIG)
    del sections["costs"]
    root = write_config_dir(tmp_path / "config", sections)
    with pytest.raises(ConfigError, match=r"missing config file.*costs\.yaml"):
        load_config(root)


def test_empty_file(tmp_path: Path) -> None:
    root = write_config_dir(tmp_path / "config", copy.deepcopy(VALID_CONFIG))
    (root / "logging.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty config file"):
        load_config(root)


def test_non_mapping_top_level(tmp_path: Path) -> None:
    root = write_config_dir(tmp_path / "config", copy.deepcopy(VALID_CONFIG))
    (root / "logging.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="expected a mapping"):
        load_config(root)


def test_validation_error_wrapped(tmp_path: Path) -> None:
    sections = copy.deepcopy(VALID_CONFIG)
    sections["labels"]["vertical_barrier_bars_h"] = -5  # must be > 0
    root = write_config_dir(tmp_path / "config", sections)
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(root)
