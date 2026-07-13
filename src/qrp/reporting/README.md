# `qrp.reporting` — Stage B evidence

## Purpose

Produce the numbers that decide whether extended-hours trading is viable (the Stage B
deliverables): the discovered earliest 1-minute timestamp, traded row counts by session,
and the spread distribution by session.

## Architecture

- `build.py` — `assemble_validated`: reads every snapshot for a symbol/series, asserts
  cross-snapshot consistency (raising on retroactive re-adjustment, §5), unions the bars,
  and runs the validation pipeline (session tags, complete index, quality flags).
- `evidence.py` — pure functions over a validated frame: `earliest_traded`,
  `row_counts_by_session`, `add_spread_columns`, `spread_distribution_by_session`, and a
  text renderer. Spread uses the IBKR BID_ASK convention (open = avg bid, close = avg ask;
  OQ-5) — flagged for confirmation against a live gateway.
- `cli.py` / `__main__.py` — reads the lake (no gateway needed) and prints the report.

## Dependencies

`polars`, `qrp.validation`, `qrp.infrastructure.storage`, `qrp.config`.

## Public interface

```bash
uv run python -m qrp.reporting --config config
```

```python
from qrp.reporting import assemble_validated, row_counts_by_session, spread_distribution_by_session
frame = assemble_validated(store, SessionTagger(), symbol="TSLA",
                           what_to_show=WhatToShow.TRADES, sessions_included=[...])
counts = row_counts_by_session(frame)
```

## Testing strategy

`tests/reporting/test_evidence.py`: session row counts (traded only), earliest-traded,
spread column derivation + per-session distribution, and end-to-end assembly from a
snapshot written to a temp lake.

## Extension points

Spread definition lives in `add_spread_columns` (revise once OQ-5 is confirmed). Additional
per-session statistics are added in `spread_distribution_by_session`.
