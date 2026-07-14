"""``python -m qrp.dataset`` — assemble the research dataset (features + labels).

Reads the feature and label lakes (no gateway) and writes a ``dataset_id``-addressed dataset
plus its manifest (ADR-0003). Requires the validated/feature/label lakes to be built first.

    uv run python -m qrp.dataset --config config
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from qrp.config import load_config
from qrp.dataset.manifest import git_head_sha
from qrp.dataset.store import DatasetStore, build_and_store
from qrp.features.store import FeatureStore
from qrp.labels.store import LabelStore
from qrp.observability.logging import configure_logging, get_logger
from qrp.validation.lake import ValidatedBarStore

_log = get_logger(__name__)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qrp.dataset", description="Assemble the research dataset."
    )
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Assemble the dataset for every configured symbol."""
    args = _parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)

    validated_store = ValidatedBarStore(config.storage)
    feature_store = FeatureStore(config.storage)
    label_store = LabelStore(config.storage)
    dataset_store = DatasetStore(config.storage)
    git_sha = git_head_sha()

    built = 0
    for spec in config.universe.symbols:
        symbol = spec.symbol
        validated_manifest = validated_store.read_manifest(symbol)
        feature_manifest = feature_store.read_manifest(symbol)
        label_manifest = label_store.read_manifest(symbol)
        if validated_manifest is None or feature_manifest is None or label_manifest is None:
            _log.warning("dataset.cli.missing_inputs", symbol=symbol)
            continue

        manifest = build_and_store(
            feature_store.read(symbol),
            label_store.read(symbol),
            dataset_store,
            symbol=symbol,
            feature_spec_version=feature_manifest.feature_spec_version,
            label_spec_version=label_manifest.label_spec_version,
            cost_model_version=config.costs.version,
            raw_snapshot_ids=validated_manifest.source_snapshot_ids,
            feature_columns=feature_manifest.feature_columns,
            git_sha=git_sha,
        )
        if manifest is not None:
            built += 1
    _log.info("dataset.cli.done", symbols_built=built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
