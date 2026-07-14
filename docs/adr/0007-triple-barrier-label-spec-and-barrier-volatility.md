# ADR-0007: Triple-barrier label spec, exit-policy unity, and barrier volatility

- **Status:** Proposed
- **Date:** 2026-07-14
- **Deciders:** (awaiting approval)
- **Charter refs:** §6 (label & strategy contract), §7 (validation), §2 invariants I3
  (label = exit policy), I1; builds on ADR-0006 (shared vol estimator), ADR-0004

## Context

Phase 2, Module 3. The label is the most consequential object in the platform: **the label
is the exit policy** (I3) — the triple-barrier rule that generates the training target and
the backtest's exit rule are the *same* object, from the *same* config, so they can never
drift. This decision fixes the `LabelGenerator` interface, the label output schema, how
purge/embargo derive from the horizon, and — the crux — **how the barrier volatility σ is
estimated**, because ±k·σ *defines the strategy*.

The charter is specific and, on σ, subtle (§6): "a causal, session-conditional volatility
estimate (EWMA of 1-min returns over a trailing window; **open-hour vol and midday vol are
not the same animal and must not share an estimator**)." That last clause rules out a single
trailing EWMA over the continuous return series (the open spike bleeds into the midday
window) and even a per-RTH-session EWMA (RTH contains both open hour and midday). Getting
this right matters more than any feature choice.

Labels look **forward** (barrier outcomes from entry to exit); that is not look-ahead — labels
are targets. Leakage is prevented elsewhere: features use bars `≤ t−1min` (ADR-0006), labels
use bars `≥ t+1`, and CV purge/embargo (§7) remove train/test contamination from overlapping
label lifespans.

## Options considered

**Barrier volatility σ (the crux)**

- **(D) Single trailing EWMA over the continuous 1-min return series.** Simplest. Rejected —
  violates §6: the open-hour spike contaminates the midday estimate.
- **(A) Per-session-label EWMA (PRE/RTH/POST), reset daily.** What the feature v1 currently
  does. Partial: separates PRE/RTH/POST, but RTH bundles open-hour + midday + close, so it
  still lets the open spike bleed into midday *within RTH* — the exact case §6 names. Not
  fully faithful.
- **(B) Time-of-day-bucketed causal EWMA (recommended).** Partition the session into intraday
  buckets (e.g. 15- or 30-min blocks, config); for each bucket maintain σ²_b = an EWMA over
  **past days** of that bucket's realized 1-min variance; σ(t) = σ_{b(t)} using only past days
  (causal). Structurally separates open-hour from midday (they are different buckets, different
  estimators) and captures the intraday U-shape. Faithful to §6.
- **(C) Hybrid: time-of-day seasonal factor × recent trailing level.** Most robust — combines
  the intraday seasonal shape (B) with a recent-realized-level term so a fresh regime change
  (e.g. earnings) is reflected same-day. More complex; more knobs. Proposed as a *documented
  future refinement* rather than v1.

**Label generator interface** — `LabelGenerator` protocol (mirrors `FeatureGenerator`); a
functional form was rejected for the same pluggability reasons as ADR-0006.

**Label storage** — a derived label lake keyed by decision timestamp (like features), vs
computing labels inside dataset assembly. Chosen: a derived lake, so labels are inspectable,
reproducible, and carry the fields sample-uniqueness weighting needs.

## Decision

**σ estimator:** adopt **(B) time-of-day-bucketed causal EWMA** as v1, shared by the barrier
and the `ewma_vol` feature (updating ADR-0006's session-conditional feature to match, so the
signal and the barrier keep one estimator — I3). Bucket size and EWMA span come from
`LabelSpecConfig.volatility` (extended with a `bucket_minutes`). (C) is recorded as a future
refinement behind a new label-spec version. This updates the feature lake (a cheap rebuild).

**Triple-barrier rule (the label = the exit policy, I3):**

- Horizontal barriers at `close_entry × (1 ± k·σ_t)`; `k` and the vertical barrier `H` (bars,
  wall-clock minutes) from `LabelSpecConfig`.
- Execution: signal at **close of bar t** → fill at **open of bar t+1**; walk forward over
  bars that **actually exist** (skip untraded minutes, §5) until the first of {take-profit,
  stop-loss, H bars}. Outcome `+1 / −1 / 0` (timeout). Long **and** short.
- One config object drives both label generation and the backtest exit; they cannot diverge.

**Label output schema** (per decision bar t): `decision_ts, entry_ts, exit_ts, label,
touched (tp|sl|vertical), realized_return, sigma`. `entry_ts/exit_ts` give each label's
lifespan, which the validation framework uses for **sample-uniqueness weighting** and to
derive **purge = H** and **embargo = max(H, 1% of samples)** — never configured independently
(§7).

**Interface & storage:** `LabelGenerator` protocol; `TripleBarrier` default;
`FixedHorizonDirection/Magnitude` and `MetaLabeling` reserved (not built — §10). A derived
label lake (`labels/`, partitioned `symbol/date`) with a manifest stamping
`label_spec_version` (feeds `dataset_id`, ADR-0003). No new dependencies.

## Consequences

- **Protects I3:** a single config-driven object is both the training target and the backtest
  exit; the barrier vol is shared with the feature, so signal and strategy cannot drift.
- **Faithful to §6:** option (B) makes open-hour and midday genuinely separate estimators.
- Requires extending `LabelSpecConfig.volatility` with `bucket_minutes` and **rebuilding the
  feature lake** so `ewma_vol` uses the same estimator (cheap; bumps `feature_spec_version`).
- Commits Module 3 to: the `LabelGenerator` protocol, the label schema, the label lake, and
  the σ definition. The purge/embargo derivation and sample-uniqueness weighting (Module 5)
  consume the label lifespans. Changing any of these needs a new ADR (§3).
- **Open question for your call:** bucket granularity for (B) — 15 vs 30 min — and whether to
  adopt hybrid (C) now instead of deferring it. Both are called out in the questions below.
