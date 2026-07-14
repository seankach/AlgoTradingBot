# ADR-0006: Feature store — interface, point-in-time contract, and initial feature spec

- **Status:** Proposed
- **Date:** 2026-07-14
- **Deciders:** (awaiting approval)
- **Charter refs:** §4 (feature store), §6 (features feed labels), §7 (leakage tests),
  §2 invariants I1 (no look-ahead), I6 (reproducibility); builds on ADR-0004 (timestamp
  semantics), ADR-0001/0003 (storage, dataset_id)

## Context

Phase 2, Module 2. With the validated-bar lake in place (session-tagged, gap-complete,
`is_traded`), we need the feature layer: point-in-time-correct features that labels and the
validation framework consume. This decision fixes a **public interface**, a **versioned
schema** (`feature_spec_version` feeds `dataset_id`), and the **enforcement of I1** — all
ADR-gated (§3).

The single most dangerous property here is look-ahead (I1). Per ADR-0004/§5, a feature
"as of *t*" may use only bars whose start-stamp is `≤ t − 1min` (the bar stamped *t* is not
complete until *t*+1). The charter is explicit that this must be encoded and *tested*, not
left to vigilance (§5, §7).

We also must respect the small **effective sample size**: with H=30 the labels overlap
heavily (§7), so a large feature set overfits instantly and the framework cannot reject
cleanly. The first feature set therefore exists to *exercise the pipeline and the leakage
tests*, not to find alpha — success is the framework **rejecting** it (shuffle → chance,
deflated Sharpe ≈ 0).

## Options considered

**Point-in-time enforcement**

- **Per-feature causality by author discipline.** Each generator "just uses past data."
  Rejected — exactly the vigilance the charter forbids; one forgotten shift silently leaks.
- **Central uniform 1-bar lag at materialization (chosen).** Generators compute features
  naturally *through* bar *t*; the feature store then applies a single mandatory 1-bar lag on
  the gap-complete minute index so the stored row at *t* reflects only bars `≤ t − 1min`.
  One rule, one place, impossible to forget per-feature; leakage tests (Module 5) verify it.
- **Type-system wrapper only.** A `PointInTime[T]` type. Kept as a complementary aid, but the
  materialization lag is the load-bearing guarantee; types alone don't survive Polars ops.

**Interface shape**

- **Functional `build_features(bars, spec)`.** Simple but not pluggable.
- **`FeatureGenerator` protocol + registry (chosen).** Mirrors the `LabelGenerator` protocol
  (§6). Each generator owns one feature family, declares the columns it emits, and computes
  through bar *t*; the store composes them, applies the lag, and persists. New families are
  additive and independently testable.

**Feature-spec location**

- **In code only.** Rejected — not versionable into `dataset_id`.
- **Versioned `FeatureSpec` (Pydantic), config-backed (chosen).** `config/features.yaml`,
  loaded and validated like the rest; `feature_spec_version` participates in `dataset_id`
  (ADR-0003). No result-affecting silent defaults (§9).

## Decision

**Alignment convention (the I1 guardrail).** A feature row stamped at bar time *t* contains
only information from bars stamped `≤ t − 1min`, and represents the information available to
**enter at the open of bar *t*** — which unifies §5 ("as of *t* uses ≤ t−1min") with §6
("signal at close of bar *t* → fill at open of bar *t*+1": the signal for entry bar *t* is
formed from bars through *t*−1). Enforced by a **single mandatory 1-bar lag** applied by the
feature store to the whole feature block on the gap-complete index. Untraded minutes keep
null features (no forward-fill, §5); "last value" features use the last *past* valid bar.

**Interface.**

- `FeatureGenerator` protocol: `name`, `output_columns`, and
  `generate(bars: pl.DataFrame, spec: FeatureSpec) -> pl.DataFrame` returning columns keyed
  by `ts_utc`, computed *through* bar *t* (the store applies the lag).
- `FeatureStore` (derived Parquet lake, partitioned `symbol/date`, like validated bars):
  composes generators, applies the point-in-time lag once, persists, and writes a manifest
  stamping `feature_spec_version` and the source validated-build lineage.

**Initial `FeatureSpec` (v1) — deliberately minimal, causal, one per family:**

1. **Lagged log returns** of close over horizons `[1, 5, 15, 30]` minutes.
2. **Session-conditional EWMA volatility** — the *same* causal estimator the triple-barrier
   labels require (§6), so features and labels share one vol definition (window from config;
   open-hour and midday not sharing an estimator).
3. **Range-based volatility** (Parkinson / Garman–Klass style) over a trailing window — an
   independent OHLC-based estimate that exercises a different code path.
4. **Relative volume** — trailing-window z-score of volume vs its session-typical level
   (IBKR's *view* of volume, §5; flagged as such).
5. **Time-of-day / session context** — minutes-since-session-open and session one-hot
   (`PRE/RTH/POST`); deterministic and causal.

All normalization is rolling/expanding on **past** data only — never full-sample statistics
(the classic silent leak). Windows are frozen in `FeatureSpec`; nothing is tuned.

**No new dependencies** (Polars only).

## Consequences

- **Protects I1** structurally: one central lag + leakage tests, not per-feature vigilance.
  Any feature referencing bar `≥ t` must fail the Module-5 tests; the shuffle test must
  collapse performance to chance.
- **Reproducibility (I6):** `feature_spec_version` enters `dataset_id`; the feature store is
  a deterministic function of the validated lake + spec + code (regenerable, like validated
  bars — not raw, so I2 does not apply).
- Features and labels share one volatility estimator, preventing drift between the signal and
  the barrier that defines the strategy (I3-adjacent).
- The minimal set keeps effective sample size manageable and makes the first Phase-2 outcome
  a *rejection* test, not an alpha hunt. Expanding the feature set is additive and bumps
  `feature_spec_version` (invalidating prior `dataset_id`s, by design).
- Commits Module 2 to: the `FeatureGenerator` protocol, the `FeatureSpec` schema +
  `config/features.yaml`, the feature-store schema/partitioning, and the central-lag
  materialization. Changing any of these later needs a new ADR (§3).
