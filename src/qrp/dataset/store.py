"""The research dataset: features aligned to labels at the decision time (ADR-0003).

Joins the point-in-time feature vector (as of the decision bar) with the triple-barrier
label, and addresses the result by a reproducible ``dataset_id`` (see
:mod:`qrp.dataset.manifest`). The dataset is derived (regenerable; I2 governs raw only) but
its ``dataset_id`` + manifest let any result be traced and regenerated bit-for-bit (I6).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from qrp.config.models import StoragePathsConfig
from qrp.dataset.manifest import DatasetManifest, compute_dataset_id
from qrp.observability.logging import get_logger

_log = get_logger(__name__)
_PARQUET_NAME = "dataset.parquet"
_MANIFEST_NAME = "_build.json"


def assemble_dataset(features: pl.DataFrame, labels: pl.DataFrame) -> pl.DataFrame:
    """Join the feature vector at each decision bar onto its label.

    The feature vector is already point-in-time correct (as of ``decision_ts - 1min``,
    ADR-0006), and the label looks forward from entry, so this join introduces no leakage.
    Returns empty if there are no labels.
    """
    if labels.is_empty() or features.is_empty():
        return pl.DataFrame()
    return labels.join(features, left_on="decision_ts", right_on="ts_utc", how="left").sort(
        "decision_ts"
    )


class DatasetStore:
    """Reads and writes research datasets and their manifests."""

    def __init__(self, paths: StoragePathsConfig) -> None:
        self._root = paths.datasets_dir
        self._manifests = paths.manifests_dir / "datasets"

    def write(self, symbol: str, frame: pl.DataFrame) -> int:
        """Write ``frame`` partitioned by decision-date (UTC), overwriting prior builds."""
        dated = frame.with_columns(pl.col("decision_ts").dt.date().alias("_date"))
        written = 0
        for (date_val,), group in dated.group_by(["_date"], maintain_order=True):
            partition_dir = self._root / f"symbol={symbol}" / f"date={date_val}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            group.drop("_date").write_parquet(partition_dir / _PARQUET_NAME)
            written += group.height
        return written

    def write_manifest(self, manifest: DatasetManifest) -> None:
        """Persist the manifest both per-symbol (current) and id-addressed (ADR-0003)."""
        symbol_dir = self._root / f"symbol={manifest.symbol}"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        payload = manifest.model_dump_json(indent=2)
        (symbol_dir / _MANIFEST_NAME).write_text(payload, encoding="utf-8")
        self._manifests.mkdir(parents=True, exist_ok=True)
        (self._manifests / f"{manifest.dataset_id}.json").write_text(payload, encoding="utf-8")

    def read(self, symbol: str) -> pl.DataFrame:
        """Read the full research dataset for ``symbol`` (empty if not built)."""
        files = sorted((self._root / f"symbol={symbol}").glob(f"date=*/{_PARQUET_NAME}"))
        if not files:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(path) for path in files]).sort("decision_ts")

    def read_manifest(self, symbol: str) -> DatasetManifest | None:
        """Read the current dataset manifest for ``symbol`` (``None`` if not built)."""
        path = self._root / f"symbol={symbol}" / _MANIFEST_NAME
        if not path.is_file():
            return None
        return DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def read_manifest_by_id(self, dataset_id: str) -> DatasetManifest | None:
        """Read a manifest by its ``dataset_id`` (``None`` if unknown)."""
        path = self._manifests / f"{dataset_id}.json"
        if not path.is_file():
            return None
        return DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def build_and_store(
    features: pl.DataFrame,
    labels: pl.DataFrame,
    store: DatasetStore,
    *,
    symbol: str,
    feature_spec_version: str,
    label_spec_version: str,
    cost_model_version: str,
    raw_snapshot_ids: Sequence[str],
    feature_columns: Sequence[str],
    git_sha: str,
) -> DatasetManifest | None:
    """Assemble the dataset, address it by ``dataset_id``, persist it, and return the manifest.

    Returns ``None`` if there is nothing to assemble.
    """
    frame = assemble_dataset(features, labels)
    if frame.is_empty():
        _log.warning("dataset.build.no_data", symbol=symbol)
        return None

    dataset_id = compute_dataset_id(
        raw_snapshot_ids=raw_snapshot_ids,
        feature_spec_version=feature_spec_version,
        label_spec_version=label_spec_version,
        cost_model_version=cost_model_version,
        git_sha=git_sha,
    )
    rows = store.write(symbol, frame)
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        symbol=symbol,
        built_at_utc=datetime.now(UTC),
        git_sha=git_sha,
        feature_spec_version=feature_spec_version,
        label_spec_version=label_spec_version,
        cost_model_version=cost_model_version,
        raw_snapshot_ids=sorted(raw_snapshot_ids),
        feature_columns=list(feature_columns),
        row_count=rows,
    )
    store.write_manifest(manifest)
    _log.info(
        "dataset.build.done",
        symbol=symbol,
        dataset_id=dataset_id,
        rows=rows,
        git_sha=git_sha,
    )
    return manifest
