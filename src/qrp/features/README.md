# `qrp.features` — point-in-time feature store (ADR-0006)

## Purpose

Compute causal, point-in-time-correct features from the validated-bar lake for the labels
and the validation framework to consume. The look-ahead invariant (I1) is enforced
structurally, not by vigilance.

## Architecture

- `protocols.py` — `FeatureGenerator`: one feature family, computes **through bar t**,
  declares its `output_columns` and `is_deterministic`.
- `generators.py` — the v1 set: `LaggedReturns`, `SessionConditionalEwmaVol` (shares the
  label's estimator, I3), `RangeVolatility` (Parkinson), `RelativeVolume`, `TimeOfDay`
  (deterministic). Rolling/EWMA stats are grouped by `_session_date` so they reset each day
  and never span the overnight gap.
- `store.py` — `build_features` composes generators and applies the **single mandatory
  1-bar lag** (`shift(1)` within the session date) to market features so a stored row at t
  reflects only bars `≤ t − 1min`; deterministic calendar features are exempt. `FeatureStore`
  persists the derived Parquet lake (partitioned `symbol/date`) + a manifest stamping
  `feature_spec_version` (feeds `dataset_id`, ADR-0003). `default_generators` builds the set
  from config.
- `cli.py` / `__main__.py` — `python -m qrp.features` builds the lake from validated bars.

## Dependencies

`polars`, `qrp.validation` (validated lake), `qrp.config`. No new third-party deps.

## Public interface

```bash
uv run python -m qrp.features --config config
```

```python
from qrp.features import FeatureStore, build_and_store, default_generators
gens = default_generators(cfg.features, cfg.labels.volatility, timezone="America/New_York")
build_and_store(validated_frame, FeatureStore(cfg.storage), gens,
                symbol="TSLA", feature_spec_version=cfg.features.version,
                timezone="America/New_York")
frame = FeatureStore(cfg.storage).read("TSLA")
```

## Testing strategy

`tests/features/test_features.py`. The priority test is **no future leak** (I1): perturbing
the final bar's data changes *no* stored feature (its effect lags off the end). Plus:
returns are lagged by exactly one bar; deterministic features are *not* lagged;
expected columns present; store round-trip + manifest.

## Extension points

Add a feature family by implementing `FeatureGenerator` and adding it to `default_generators`
(and its params to `FeatureSpecConfig`); bump `feature_spec_version`. The central lag and
leakage tests cover new market features automatically. The session-conditional vol's intraday
granularity (open-hour vs midday within RTH, §6) is a candidate refinement for the label-spec
ADR, since the barrier vol defines the strategy.
