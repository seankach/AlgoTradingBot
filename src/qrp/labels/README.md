# `qrp.labels` — triple-barrier labelling (§6, ADR-0007)

## Purpose

Turn validated bars + the barrier volatility into labels. **The label is the exit policy**
(I3): the same object generates the training target and drives the backtest exit, so they
cannot drift.

## Architecture

- `protocols.py` — `LabelGenerator`: `generate(bars, sigma) -> labels`.
- `triple_barrier.py` — `TripleBarrier` (default). Decide at the close of a traded bar, enter
  at the **open of the next traded bar**, walk forward over bars that actually exist (§5)
  until the first of take-profit (`+k*sigma`), stop-loss (`-k*sigma`), or the vertical
  barrier `H` wall-clock minutes. Outcome `+1 / -1 / 0`. `sigma` is the causal,
  time-of-day-bucketed estimate shared with the `ewma_vol` feature (ADR-0007). The barrier
  walk is vectorised over a bounded time offset (H is small), so it runs over millions of
  bars in numpy, not a Python loop.
- `store.py` — `LabelStore` (derived Parquet lake, partitioned by decision-date) +
  `LabelBuildManifest` stamping `label_spec_version` (feeds `dataset_id`, ADR-0003) and the
  label distribution.
- `cli.py` / `__main__.py` — `python -m qrp.labels` builds the lake.

Label schema: `decision_ts, entry_ts, exit_ts, label, touched (tp|sl|both|vertical),
realized_return, sigma`. The `entry_ts/exit_ts` lifespan feeds sample-uniqueness weighting
and purge=H / embargo (§7).

## Dependencies

`polars`, `numpy`, `qrp.validation` (validated lake), `qrp.features` (shared `sigma`),
`qrp.config`.

## Public interface

```bash
uv run python -m qrp.labels --config config
```

```python
from qrp.labels import TripleBarrier, LabelStore, build_and_store
from qrp.features.volatility import barrier_volatility
tb = TripleBarrier(k=cfg.labels.barrier_sigma_multiple_k, h_minutes=cfg.labels.vertical_barrier_bars_h)
sigma = barrier_volatility(validated, bucket_minutes=..., ewma_span_days=..., timezone="America/New_York")
build_and_store(validated, sigma, tb, LabelStore(cfg.storage), symbol="TSLA",
                label_spec_version=cfg.labels.version)
```

## Testing strategy

`tests/labels/test_labels.py` drives the barrier walk with **explicit sigma** (isolating it
from the vol estimator): take-profit, stop-loss, vertical timeout, ambiguous same-bar
double-touch (→ 0), entry skipping an untraded minute, and store round-trip + manifest.
Verified on the real 16y dataset: 3.54M labels, near-symmetric +1/-1 (~38/39%), mean return
≈ ±2σ, max lifespan exactly H.

## Extension points

`FixedHorizonDirection/Magnitude` and `MetaLabeling` implement `LabelGenerator` (reserved,
§10). Purge/embargo and sample-uniqueness weighting (Module 5) consume the label lifespans.
The barrier vol's intraday granularity is governed by ADR-0007 (hybrid refinement deferred).
