# `qrp.infrastructure.storage` — immutable snapshot lake

## Purpose

Persist raw IBKR pulls as **immutable, content-addressed** Parquet snapshots (ADR-0001,
ADR-0003; invariant I2). Nothing is ever overwritten. This is the system of record for raw
market data.

## Architecture

- `snapshots.py`:
  - `compute_snapshot_id(...)` — SHA-256 over a canonical text encoding of the pull's
    provenance (symbol, series, timezone, bar size) and its sorted bar rows. Deterministic,
    independent of Parquet encoding. `fetch_ts_utc` is **not** in the hash, so identity
    tracks data, not wall-clock.
  - `SnapshotStore` — writes Parquet partitioned `symbol=<>/date=<UTC date>/<snapshot_id>.parquet`
    and a JSON manifest per snapshot under `manifests/raw/`. Writing is idempotent (same
    content → same id/path → skipped); differing data (e.g. IBKR split re-adjustment) yields
    a new id that coexists with the old.
  - `SnapshotManifest` — provenance record (id, symbol, series, tz, bar size, fetch time,
    range, row count, partition files).

Raw Parquet schema (ADR-0001): `ts_utc, open, high, low, close, volume, bar_count, wap,
symbol, what_to_show, snapshot_id, fetch_ts_utc`. `ts_utc` is the bar start in UTC.

## Dependencies

`polars` (Parquet I/O), `qrp.domain`, `qrp.config`. No pandas (§4).

## Public interface

```python
from qrp.infrastructure.storage import SnapshotStore
store = SnapshotStore(cfg.storage)
manifest = store.write_snapshot(symbol="TSLA", what_to_show=WhatToShow.TRADES, bars=bars,
                                request_timezone=cfg.ibkr.request_timezone, bar_size="1 min")
frame = store.read_snapshot(manifest)          # -> polars DataFrame
all_manifests = store.list_manifests()
```

## Testing strategy

`tests/infrastructure/test_snapshots.py`: partitioned-file + manifest creation, content-hash
idempotency, split-readjustment producing coexisting snapshots (I2), UTC-date partition
splitting, round-trip read, empty-input rejection, and series-dependent ids.

## Extension points

The validated-bar lake reuses the same partitioning scheme under `validated_bars/`. Snapshot
manifests feed the `dataset_id` hash (ADR-0003) built in Phase 2.
