"""The validated-bar lake (ADR-0001) that features and labels consume.

Session-tagged, gap-complete, quality-flagged price bars.

Validated bars are **derived** — a deterministic function of the raw snapshots plus this
code — so, unlike raw snapshots (I2), they are regenerable and rebuilt wholesale. Each
build writes a manifest recording the contributing ``source_snapshot_ids`` and counts, so
lineage is preserved for reproducibility (I6) and feeds the ``dataset_id`` hash later
(ADR-0003).
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from qrp.base import StrictModel
from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.infrastructure.storage.snapshots import SnapshotStore
from qrp.observability.logging import get_logger
from qrp.validation.assemble import assemble_validated
from qrp.validation.sessions import SessionTagger

_log = get_logger(__name__)
_PARQUET_NAME = "validated.parquet"
_MANIFEST_NAME = "_build.json"


class ValidatedBuildManifest(StrictModel):
    """Provenance for one symbol's validated-bar build (persisted as JSON)."""

    symbol: str
    built_at_utc: datetime
    sessions_included: list[str]
    row_count: int
    traded_count: int
    source_snapshot_ids: list[str]


def build_validated_bars(
    store: SnapshotStore,
    tagger: SessionTagger,
    *,
    symbol: str,
    sessions_included: list[str],
) -> pl.DataFrame:
    """Assemble the validated TRADES bar frame for ``symbol`` over the given sessions.

    Returns an empty frame if the symbol has no TRADES snapshots.
    """
    return assemble_validated(
        store,
        tagger,
        symbol=symbol,
        what_to_show=WhatToShow.TRADES,
        sessions_included=sessions_included,
    )


class ValidatedBarStore:
    """Reads and writes the derived validated-bar lake under the configured root."""

    def __init__(self, paths: StoragePathsConfig) -> None:
        self._root = paths.validated_bars_dir

    def write(self, symbol: str, frame: pl.DataFrame) -> int:
        """Write ``frame`` partitioned by UTC date, overwriting any prior build.

        Returns the number of rows written.
        """
        dated = frame.with_columns(_date=pl.col("ts_utc").dt.date())
        written = 0
        for (date_val,), group in dated.group_by(["_date"], maintain_order=True):
            partition_dir = self._root / f"symbol={symbol}" / f"date={date_val}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            group.drop("_date").write_parquet(partition_dir / _PARQUET_NAME)
            written += group.height
        return written

    def write_manifest(self, manifest: ValidatedBuildManifest) -> None:
        """Persist the build manifest for a symbol."""
        symbol_dir = self._root / f"symbol={manifest.symbol}"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        (symbol_dir / _MANIFEST_NAME).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

    def read(self, symbol: str) -> pl.DataFrame:
        """Read the full validated-bar frame for ``symbol`` (empty if not built)."""
        symbol_dir = self._root / f"symbol={symbol}"
        files = sorted(symbol_dir.glob(f"date=*/{_PARQUET_NAME}"))
        if not files:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(path) for path in files]).sort("ts_utc")

    def read_manifest(self, symbol: str) -> ValidatedBuildManifest | None:
        """Read the build manifest for ``symbol`` (``None`` if not built)."""
        path = self._root / f"symbol={symbol}" / _MANIFEST_NAME
        if not path.is_file():
            return None
        return ValidatedBuildManifest.model_validate_json(path.read_text(encoding="utf-8"))


def build_and_store(
    snapshots: SnapshotStore,
    validated: ValidatedBarStore,
    tagger: SessionTagger,
    *,
    symbol: str,
    sessions_included: list[str],
) -> ValidatedBuildManifest | None:
    """Build the validated bars for a symbol, persist them, and return the manifest.

    Returns ``None`` if the symbol has no TRADES snapshots to validate.
    """
    frame = build_validated_bars(
        snapshots, tagger, symbol=symbol, sessions_included=sessions_included
    )
    if frame.is_empty():
        _log.warning("validated.build.no_data", symbol=symbol)
        return None

    rows = validated.write(symbol, frame)
    source_ids = [
        m.snapshot_id
        for m in snapshots.list_manifests()
        if m.symbol == symbol and m.what_to_show == WhatToShow.TRADES
    ]
    manifest = ValidatedBuildManifest(
        symbol=symbol,
        built_at_utc=datetime.now(UTC),
        sessions_included=list(sessions_included),
        row_count=rows,
        traded_count=int(frame.get_column("is_traded").sum()),
        source_snapshot_ids=sorted(source_ids),
    )
    validated.write_manifest(manifest)
    _log.info(
        "validated.build.done",
        symbol=symbol,
        rows=rows,
        traded=manifest.traded_count,
        source_snapshots=len(source_ids),
    )
    return manifest
