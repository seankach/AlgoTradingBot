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
- `assemble.py` — `assemble_validated`: reads all snapshots for a symbol/series, resolves
  frontier settling by latest fetch and raises only on **settled** re-adjustment
  (ADR-0005), then runs session tagging → complete index → quality flags. Shared by the
  lake and reporting.
- `lake.py` — the materialised **validated-bar lake** (ADR-0001): `build_validated_bars`,
  `ValidatedBarStore` (Parquet partitioned `symbol/date`), `build_and_store`, and a
  `ValidatedBuildManifest` recording `source_snapshot_ids` for lineage. Validated bars are
  *derived*, so a rebuild overwrites the prior build (I2 governs raw only).
- `cli.py` / `__main__.py` — `python -m qrp.validation` builds the lake for every
  configured symbol over the ingest sessions (no gateway needed).

## Dependencies

`polars`, `exchange_calendars`, `qrp.domain`, `qrp.infrastructure.storage`, `qrp.config`.

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

Materialise the validated-bar lake from the snapshot lake:

```bash
uv run python -m qrp.validation --config config
```

```python
from qrp.validation import ValidatedBarStore, build_and_store
build_and_store(snapshots, ValidatedBarStore(cfg.storage), SessionTagger(),
                symbol="TSLA", sessions_included=[str(s) for s in cfg.session.ingest_sessions])
frame = ValidatedBarStore(cfg.storage).read("TSLA")
```

### Validation framework (Module 5, ADR-0009)

`Study` is the **only** path to a metric; `PurgedCPCV` derives purge/embargo from the label
lifespans; the leakage suite and the lockbox are load-bearing CI contracts (§9).

```python
from qrp.validation import (
    PurgedCPCV, Study, Lockbox, InMemoryLockboxStore, assert_features_are_not_outcomes,
)
study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))       # 15 CPCV paths
result = study.run(dataset, model, feature_columns=[...], h_bars=30)   # -> StudyResult (AUC ...)

# The lockbox: at most 2 touches for the whole project (I5), enforced by code, not memory.
box = Lockbox(store, dataset_id=did, git_sha=sha)            # store: In-memory or Postgres
result = study.evaluate_lockbox(dataset, model, lockbox=box, justification="baseline OOS",
                                feature_columns=[...], h_bars=30)      # the ONLY lockbox path
```

Scoring scheme: **binary sign-AUC over the resolved (non-zero) labels** — the timeout class is held
out (not macro OVR-AUC). Leakage separation is **structural**, not by score magnitude: a subtle leak
and a real edge produce the same AUC, so each §7 test sits at the layer its leak enters (PIT /
purge / label-shuffle), and the time-order and block-label shuffles are **dormant tripwires** that
arm once a cross-sample (sequence) model exists (Phase 3+).

## Testing strategy

`tests/validation/test_validation.py`: conflict detection + raise; session tags for each of
PRE/RTH/POST/OVERNIGHT and a weekend against the real calendar; index completeness with
untraded minutes kept null; and gap/halt/zero-volume/price-anomaly flags.

`test_cpcv.py` / `test_metrics.py` / `test_study_canary.py`: exact purge boundary, imbalance-robust
metrics, and the planted-leak + graded canaries (resolution limit ρ≈0.05 at n=8k). `test_leakage_
suite.py`: the four §7 tests + the dormant shuffles. `test_lockbox.py`: the **third** touch raises
(and does not increment), blank justifications are refused, and the counter is the append-only row
count. The Postgres store has a roundtrip test skipped unless `QRP_LOCKBOX_TEST_DSN` is set.

## Extension points

`SessionTagger` accepts a different calendar (e.g. `XNAS`) and pre/post edges. The default
research scope (`PRE + RTH + POST`, OVERNIGHT excluded) is applied by passing
`sessions_included` from `config.session.tradable_sessions`. Session boundary times could be
lifted into config if a venue needs different extended-hours edges.
