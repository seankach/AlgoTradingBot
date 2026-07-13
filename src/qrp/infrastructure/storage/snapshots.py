"""Immutable, content-addressed raw-snapshot storage (ADR-0001, ADR-0003; invariant I2).

Each ingestion pull is written once as an immutable **snapshot**: Parquet partitioned by
``symbol/date`` (UTC date), with a ``snapshot_id`` derived from the pull's *content*
(symbol, series, timezone, bar size, and the bar rows). Two pulls with identical content
share an id and path — so re-writing is idempotent and nothing is ever overwritten. Two
pulls that differ (e.g. IBKR's retroactive split re-adjustment, §5) get *different* ids and
coexist; the validation layer later diffs their overlap and raises on mismatch (ADR-0003).

The ``fetch_ts_utc`` is recorded as provenance but is deliberately **not** part of the
content hash, so identity tracks data, not wall-clock.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from qrp.base import StrictModel
from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.observability.logging import get_logger

_log = get_logger(__name__)

_ID_LENGTH = 32
_UNIT = "\x1f"  # ASCII unit separator, cannot appear in the encoded values

# Raw-snapshot Parquet column order (ADR-0001).
_COLUMNS = (
    "ts_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bar_count",
    "wap",
    "symbol",
    "what_to_show",
    "snapshot_id",
    "fetch_ts_utc",
)


class SnapshotManifest(StrictModel):
    """Provenance record for one immutable snapshot (persisted as JSON)."""

    snapshot_id: str
    symbol: str
    what_to_show: WhatToShow
    bar_size: str
    request_timezone: str
    fetch_ts_utc: datetime
    range_start_utc: datetime
    range_end_utc: datetime
    row_count: int
    partition_files: list[str]


def compute_snapshot_id(
    *,
    symbol: str,
    what_to_show: WhatToShow,
    request_timezone: str,
    bar_size: str,
    bars: Sequence[Bar],
) -> str:
    """Return a content hash over the pull's provenance and canonicalised bar rows.

    Deterministic and independent of Parquet encoding: the hash is taken over a canonical
    text form of the sorted rows plus the identifying provenance, so identical data always
    yields the same id and any value change yields a different one.
    """
    digest = hashlib.sha256()
    header = _UNIT.join([symbol, str(what_to_show), request_timezone, bar_size])
    digest.update((header + "\n").encode())
    for bar in sorted(bars, key=lambda b: b.ts_utc):
        row = _UNIT.join(
            [
                bar.ts_utc.isoformat(),
                repr(bar.open),
                repr(bar.high),
                repr(bar.low),
                repr(bar.close),
                repr(bar.volume),
                str(bar.bar_count),
                repr(bar.wap),
            ]
        )
        digest.update((row + "\n").encode())
    return digest.hexdigest()[:_ID_LENGTH]


class SnapshotStore:
    """Reads and writes immutable raw snapshots under the configured storage root."""

    def __init__(self, paths: StoragePathsConfig) -> None:
        self._root = paths.raw_snapshots_dir
        self._manifests_dir = paths.manifests_dir / "raw"

    def _manifest_path(self, snapshot_id: str) -> Path:
        return self._manifests_dir / f"{snapshot_id}.json"

    def write_snapshot(
        self,
        *,
        symbol: str,
        what_to_show: WhatToShow,
        bars: Sequence[Bar],
        request_timezone: str,
        bar_size: str,
        fetch_ts_utc: datetime | None = None,
    ) -> SnapshotManifest:
        """Persist ``bars`` as an immutable snapshot and return its manifest.

        Idempotent: if a snapshot with the same content id already exists, the existing
        manifest is returned and no file is rewritten (invariant I2).

        Raises:
            ValueError: If ``bars`` is empty.
        """
        if not bars:
            raise ValueError("cannot write an empty snapshot")

        snapshot_id = compute_snapshot_id(
            symbol=symbol,
            what_to_show=what_to_show,
            request_timezone=request_timezone,
            bar_size=bar_size,
            bars=bars,
        )
        existing = self._manifests_dir / f"{snapshot_id}.json"
        if existing.is_file():
            _log.info("snapshot.exists", snapshot_id=snapshot_id, symbol=symbol)
            return SnapshotManifest.model_validate_json(existing.read_text(encoding="utf-8"))

        fetch_ts = fetch_ts_utc or datetime.now(UTC)
        ordered = sorted(bars, key=lambda b: b.ts_utc)
        frame = self._to_frame(ordered, symbol, what_to_show, snapshot_id, fetch_ts)

        partition_files = self._write_partitions(frame, symbol, snapshot_id)

        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            symbol=symbol,
            what_to_show=what_to_show,
            bar_size=bar_size,
            request_timezone=request_timezone,
            fetch_ts_utc=fetch_ts,
            range_start_utc=ordered[0].ts_utc,
            range_end_utc=ordered[-1].ts_utc,
            row_count=len(ordered),
            partition_files=partition_files,
        )
        self._manifests_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path(snapshot_id).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        _log.info(
            "snapshot.written",
            snapshot_id=snapshot_id,
            symbol=symbol,
            what_to_show=str(what_to_show),
            rows=len(ordered),
            partitions=len(partition_files),
        )
        return manifest

    @staticmethod
    def _to_frame(
        bars: Sequence[Bar],
        symbol: str,
        what_to_show: WhatToShow,
        snapshot_id: str,
        fetch_ts: datetime,
    ) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "ts_utc": [b.ts_utc for b in bars],
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
                "bar_count": [b.bar_count for b in bars],
                "wap": [b.wap for b in bars],
                "symbol": symbol,
                "what_to_show": str(what_to_show),
                "snapshot_id": snapshot_id,
                "fetch_ts_utc": fetch_ts,
            }
        ).select(_COLUMNS)

    def _write_partitions(self, frame: pl.DataFrame, symbol: str, snapshot_id: str) -> list[str]:
        """Write one Parquet file per UTC date; never overwrite an existing file."""
        dated = frame.with_columns(_date=pl.col("ts_utc").dt.date())
        written: list[str] = []
        for (date_val,), group in dated.group_by(["_date"], maintain_order=True):
            partition_dir = self._root / f"symbol={symbol}" / f"date={date_val}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            file_path = partition_dir / f"{snapshot_id}.parquet"
            if not file_path.exists():
                group.drop("_date").write_parquet(file_path)
            written.append(str(file_path.relative_to(self._root)))
        return written

    def list_manifests(self) -> list[SnapshotManifest]:
        """Return all snapshot manifests, sorted by fetch timestamp."""
        if not self._manifests_dir.is_dir():
            return []
        manifests = [
            SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self._manifests_dir.glob("*.json"))
        ]
        return sorted(manifests, key=lambda m: m.fetch_ts_utc)

    def read_snapshot(self, manifest: SnapshotManifest) -> pl.DataFrame:
        """Read all partition files for a snapshot back into a single frame."""
        frames = [pl.read_parquet(self._root / rel) for rel in manifest.partition_files]
        return pl.concat(frames).sort("ts_utc")
