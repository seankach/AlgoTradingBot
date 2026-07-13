# `qrp.validation` — data-contract enforcement (§5)

## Purpose

Turn immutable raw snapshots into trustworthy, session-tagged, gap-complete bars, and make
the §5 data hazards impossible to ignore: retroactive re-adjustment is caught (not silent),
sessions come from the exchange calendar, the minute index is complete with an `is_traded`
flag (no forward-fill), and gaps/halts/anomalies are recorded as data.

## Architecture

- `conflicts.py` — `find_conflicts` / `assert_no_conflicts`: compare overlapping timestamps
  across snapshots of the same symbol/series; disagreement (e.g. split re-adjustment) is a
  `SnapshotConflictError`, never a silent overwrite (ADR-0003, I2).
- `sessions.py` — `SessionTagger`: labels each UTC bar `PRE | RTH | POST | OVERNIGHT`.
  Regular-hours boundaries (early closes included) come from `exchange_calendars`; the
  pre/post window edges (04:00 / 20:00 ET) sit on top. pandas is confined to the calendar
  call and immediately converted away (§4).
- `session_index.py` — `build_session_index` (complete minute grid over the sessions in
  scope), `attach_bars` (left-join actual bars, add `is_traded`, **no forward-fill**),
  `bars_to_frame`, `validated_frame`.
- `quality.py` — `flag_quality`: adds `is_gap`, `is_halt`, `is_zero_volume`,
  `is_price_anomaly` as boolean columns. Never raises.

## Dependencies

`polars`, `exchange_calendars`, `qrp.domain`.

## Public interface

```python
from qrp.validation import (
    SessionTagger, assert_no_conflicts, validated_frame, flag_quality,
)
assert_no_conflicts([snapshot_a, snapshot_b])          # raises on retroactive rewrite
frame = validated_frame(bars, start_utc=..., end_utc=..., sessions_included=["PRE","RTH","POST"],
                        tagger=SessionTagger(), what_to_show=WhatToShow.TRADES)
frame = flag_quality(frame)
```

## Testing strategy

`tests/validation/test_validation.py`: conflict detection + raise; session tags for each of
PRE/RTH/POST/OVERNIGHT and a weekend against the real calendar; index completeness with
untraded minutes kept null; and gap/halt/zero-volume/price-anomaly flags.

## Extension points

`SessionTagger` accepts a different calendar (e.g. `XNAS`) and pre/post edges. The default
research scope (`PRE + RTH + POST`, OVERNIGHT excluded) is applied by passing
`sessions_included` from `config.session.tradable_sessions`. Session boundary times could be
lifted into config if a venue needs different extended-hours edges.
