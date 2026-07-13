# `qrp.ingestion` — backfill & incremental orchestration

## Purpose

Drive end-to-end ingestion: discover depth, fetch TSLA 1-minute bars (`useRTH=0`) for both
`TRADES` and `BID_ASK`, and write immutable snapshots. Backfill and the daily incremental
update share **one** code path (§5).

## Architecture

- `orchestrator.py`:
  - `Ingestor` — depends only on the broker-neutral `MarketDataSource` (connection
    lifecycle is the caller's job, so it stays broker-agnostic). `backfill` and
    `incremental` both funnel through `_ingest_window` → `fetch_bars` → `SnapshotStore`.
  - `DepthMarker` — persists the discovered earliest timestamp per symbol/series, so depth
    is recorded and never hardcoded (§5).
- `cli.py` / `__main__.py` — wires the IBKR adapter + store, opens the gateway session, and
  runs the chosen mode.

## Dependencies

`qrp.domain`, `qrp.infrastructure` (storage + IBKR adapter), `qrp.config`,
`qrp.observability`.

## Public interface

```python
from qrp.ingestion import Ingestor
ing = Ingestor(source, store, request_timezone=cfg.ibkr.request_timezone,
               depth_dir=cfg.storage.manifests_dir / "depth")
ing.backfill("TSLA", WhatToShow.TRADES)      # full history, windowed
ing.incremental("TSLA", WhatToShow.TRADES)   # tail since last stored bar (same path)
```

CLI (needs a live gateway):

```bash
uv run python -m qrp.ingestion --config config --mode auto   # backfill or update per series
```

## Testing strategy

`tests/ingestion/test_orchestrator.py` drives a fake `MarketDataSource`: windowed backfill
with a persisted depth marker, incremental resuming from the last bar (one-bar overlap for
the conflict validator), and the no-depth short-circuit. No live gateway (§9).

## Extension points

`window` sizing is a parameter. Additional series or symbols come from config. A second
broker's adapter drops in unchanged behind `MarketDataSource`.
