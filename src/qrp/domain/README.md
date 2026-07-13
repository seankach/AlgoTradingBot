# `qrp.domain` — broker-neutral domain layer

## Purpose

Define the types and the abstraction boundary the research platform depends on, with **no
vendor SDK** in sight (ADR-0002). Everything above `infrastructure/` speaks only this
vocabulary, so a second broker is additive and tests run against fakes/fixtures.

## Architecture

- `enums.py` — `WhatToShow` (`TRADES`, `BID_ASK`).
- `models.py` — `Bar`, the neutral OHLCV bar. `ts_utc` is the **bar start** in UTC
  (ADR-0004); tz-aware inputs are normalised to UTC, naive inputs are rejected.
- `protocols.py` — `MarketDataSource` (read-only historical data) and `Broker` (reserved
  order-execution boundary, no members until Phase 5, per §10). Both are
  `runtime_checkable` `typing.Protocol`s — adapters satisfy them structurally, without
  inheritance.

## Dependencies

`pydantic` and `qrp.base` only. **Never** `ib_async` or any broker library — that import is
confined to `infrastructure/brokers/ibkr/` and enforced in CI (ADR-0002).

## Public interface

```python
from qrp.domain import Bar, MarketDataSource, Broker, WhatToShow
```

`MarketDataSource.earliest_available_timestamp(symbol, what_to_show, *, bar_size)` and
`MarketDataSource.fetch_bars(symbol, *, start_utc, end_utc, what_to_show, bar_size,
use_rth, request_timezone)` — datetimes tz-aware, results UTC, timezone pinned per call.

## Testing strategy

Unit tests (`tests/domain/`) cover timestamp normalisation (UTC in, non-UTC converted,
naive rejected) and strictness (frozen, unknown-key rejection). Protocol conformance is
exercised by adapter tests under `tests/infrastructure/` against recorded fixtures.

## Extension points

A new broker implements `MarketDataSource` in its own `infrastructure/brokers/<vendor>/`
package. New neutral value types are added here; anything vendor-specific stays below the
boundary.
