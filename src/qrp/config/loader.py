"""Load and validate platform configuration from a directory of YAML files.

One file per configuration domain. ``costs.yaml`` as a standalone file is mandated by
CLAUDE.md §8; the same one-file-per-section convention is applied throughout for
symmetry. A top-level ``config.yaml`` carries cross-cutting metadata (``config_version``).

Validation happens here, at load time, via Pydantic — never at point of use
(CLAUDE.md §4). Any problem (missing file, unparseable YAML, failed validation) raises
:class:`ConfigError` with the offending path in the message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from qrp.config.models import AppConfig

_META_FILE: Final = "config.yaml"

#: Maps an :class:`AppConfig` section name to the YAML file that populates it.
_SECTION_FILES: Final[dict[str, str]] = {
    "ibkr": "ibkr.yaml",
    "universe": "universe.yaml",
    "session": "session.yaml",
    "costs": "costs.yaml",
    "labels": "labels.yaml",
    "features": "features.yaml",
    "storage": "storage.yaml",
    "logging": "logging.yaml",
}


class ConfigError(Exception):
    """Raised when configuration is missing, unparseable, or fails validation."""


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file that must contain a top-level mapping.

    Args:
        path: File to read.

    Returns:
        The parsed mapping.

    Raises:
        ConfigError: If the file is missing, empty, unparseable, or not a mapping.
    """
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        raise ConfigError(f"empty config file: {path}")
    if not isinstance(data, dict):
        raise ConfigError(
            f"expected a mapping at the top level of {path}, got {type(data).__name__}"
        )
    return data


def load_config(config_dir: Path | str) -> AppConfig:
    """Load, assemble, and validate the full platform configuration.

    Args:
        config_dir: Directory containing ``config.yaml`` plus one file per section
            (see ``_SECTION_FILES``).

    Returns:
        A fully-validated, immutable :class:`AppConfig`.

    Raises:
        ConfigError: If the directory or any required file is missing, a file is
            unparseable, or the assembled configuration fails validation (including
            unknown keys and any missing result-affecting value).

    Example:
        >>> config = load_config("config")  # doctest: +SKIP
        >>> config.labels.vertical_barrier_bars_h  # doctest: +SKIP
        30
    """
    directory = Path(config_dir)
    if not directory.is_dir():
        raise ConfigError(f"config directory not found: {directory}")

    assembled: dict[str, Any] = dict(_read_yaml_mapping(directory / _META_FILE))
    for section, filename in _SECTION_FILES.items():
        assembled[section] = _read_yaml_mapping(directory / filename)

    try:
        return AppConfig.model_validate(assembled)
    except ValidationError as exc:
        raise ConfigError(f"configuration failed validation:\n{exc}") from exc
