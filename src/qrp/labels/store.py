"""The derived label lake (§6, ADR-0007).

Labels are derived (regenerable; I2 governs raw only) and stamp ``label_spec_version`` for
the ``dataset_id`` hash (ADR-0003). Each label carries its ``entry_ts``/``exit_ts`` lifespan,
which the validation framework uses for sample-uniqueness weighting and to derive
purge=H / embargo (§7).
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from qrp.base import StrictModel
from qrp.config.models import StoragePathsConfig
from qrp.labels.protocols import LabelGenerator
from qrp.observability.logging import get_logger

_log = get_logger(__name__)
_PARQUET_NAME = "labels.parquet"
_MANIFEST_NAME = "_build.json"


class LabelBuildManifest(StrictModel):
    """Provenance for one symbol's label build (persisted as JSON)."""

    symbol: str
    built_at_utc: datetime
    label_spec_version: str
    method: str
    label_count: int
    label_distribution: dict[str, int]


class LabelStore:
    """Reads and writes the derived label lake, partitioned by decision-date."""

    def __init__(self, paths: StoragePathsConfig) -> None:
        self._root = paths.labels_dir

    def write(self, symbol: str, frame: pl.DataFrame) -> int:
        """Write ``frame`` partitioned by the decision-date (UTC), overwriting prior builds."""
        dated = frame.with_columns(pl.col("decision_ts").dt.date().alias("_date"))
        written = 0
        for (date_val,), group in dated.group_by(["_date"], maintain_order=True):
            partition_dir = self._root / f"symbol={symbol}" / f"date={date_val}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            group.drop("_date").write_parquet(partition_dir / _PARQUET_NAME)
            written += group.height
        return written

    def write_manifest(self, manifest: LabelBuildManifest) -> None:
        """Persist the build manifest for a symbol."""
        symbol_dir = self._root / f"symbol={manifest.symbol}"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        (symbol_dir / _MANIFEST_NAME).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

    def read(self, symbol: str) -> pl.DataFrame:
        """Read the full label frame for ``symbol`` (empty if not built)."""
        files = sorted((self._root / f"symbol={symbol}").glob(f"date=*/{_PARQUET_NAME}"))
        if not files:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(path) for path in files]).sort("decision_ts")

    def read_manifest(self, symbol: str) -> LabelBuildManifest | None:
        """Read the build manifest for ``symbol`` (``None`` if not built)."""
        path = self._root / f"symbol={symbol}" / _MANIFEST_NAME
        if not path.is_file():
            return None
        return LabelBuildManifest.model_validate_json(path.read_text(encoding="utf-8"))


def build_and_store(
    validated: pl.DataFrame,
    sigma: pl.DataFrame,
    generator: LabelGenerator,
    store: LabelStore,
    *,
    symbol: str,
    label_spec_version: str,
) -> LabelBuildManifest | None:
    """Generate labels for a symbol, persist them, and return the manifest.

    Returns ``None`` if no labels could be produced (no data / no valid barriers).
    """
    labels = generator.generate(validated, sigma)
    if labels.is_empty():
        _log.warning("labels.build.no_data", symbol=symbol)
        return None

    rows = store.write(symbol, labels)
    distribution = {
        str(row["label"]): int(row["n"])
        for row in labels.group_by("label").agg(pl.len().alias("n")).iter_rows(named=True)
    }
    manifest = LabelBuildManifest(
        symbol=symbol,
        built_at_utc=datetime.now(UTC),
        label_spec_version=label_spec_version,
        method=generator.name,
        label_count=rows,
        label_distribution=distribution,
    )
    store.write_manifest(manifest)
    _log.info(
        "labels.build.done",
        symbol=symbol,
        labels=rows,
        distribution=distribution,
        spec_version=label_spec_version,
    )
    return manifest
