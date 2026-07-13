# `qrp.infrastructure.brokers.ibkr` — IBKR adapter

## Purpose

Implement the broker-neutral `MarketDataSource` (ADR-0002) against Interactive Brokers via
`ib_async`. This is the **only** package allowed to import `ib_async`; the boundary is
enforced by the import-linter contract in `pyproject.toml` and checked in CI.

## Architecture

- `pacing.py` — `PacingLimiter`: a rolling-window weighted rate limiter enforcing IBKR's
  ≤60 requests / 10 min, with `BID_ASK` counting double (§5). Pure, injectable clock/sleep,
  no `ib_async` import.
- `adapter.py`:
  - `IBClient` — a narrow `Protocol` mirroring the `ib_async.IB` methods used, so a fake
    can be injected in tests.
  - `_bar_from_ibkr` — converts `BarData` → neutral `Bar` in UTC (bar-start semantics,
    ADR-0004; naive datetimes localised with the pinned request timezone).
  - `IBKRMarketDataSource` — connection management, contract qualification, the **hybrid
    depth probe** (head-stamp anchor + forward-find + backward-pin, OQ-1), and paced,
    backed-off, chunked historical fetch.

## Dependencies

`ib_async`, plus `qrp.config`, `qrp.domain`, `qrp.observability`. Every historical request
goes through the `PacingLimiter`; nothing bypasses it.

## Public interface

```python
from qrp.infrastructure.brokers.ibkr import IBKRMarketDataSource, PacingLimiter
from qrp.config import load_config

cfg = load_config("config")
source = IBKRMarketDataSource(cfg.ibkr, cfg.universe.symbols)
with source.connected():
    earliest = source.earliest_available_timestamp("TSLA", WhatToShow.TRADES, bar_size="1 min")
    bars = source.fetch_bars("TSLA", start_utc=..., end_utc=..., what_to_show=WhatToShow.TRADES,
                             bar_size="1 min", use_rth=False, request_timezone=cfg.ibkr.request_timezone)
```

## Testing strategy

Unit tests for pacing (`tests/infrastructure/test_pacing.py`, fake clock — no real waiting)
and for the adapter (`tests/infrastructure/test_ibkr_adapter.py`) against a synthetic
`FakeIB` that generates a contiguous 1-min series on demand: conversion, hybrid depth probe,
windowed fetch, BID_ASK double-weight, retry/backoff, and unknown-symbol handling. **Never a
live gateway** (§9).

## Open questions

Live-gateway behaviours this code assumes are tracked in
[`docs/ibkr-open-questions.md`](../../../../../docs/ibkr-open-questions.md) (OQ-1…OQ-6) and
referenced inline. Resolve them by running against a real gateway and updating fixtures.

## Extension points

A second broker is a sibling package under `infrastructure/brokers/` implementing the same
`MarketDataSource` protocol; nothing above the boundary changes. Larger per-request windows
(OQ-3) are a one-line change to `_DURATION_BY_BAR_SIZE`.
