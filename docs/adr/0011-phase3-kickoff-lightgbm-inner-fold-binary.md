# ADR-0011: Phase 3 kickoff — LightGBM first, Study owns the inner fold, binary-on-resolved

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Romesh Sharma (decided 2026-07-15, in the instruction this ADR records)
- **Charter refs:** §10 (Phase 3 = GBMs first), §4 (deps are ADR-gated), §7 (Study is the only door;
  purge correctness is the framework's, not a library's), §9; builds on ADR-0009/0010 (Study, CPCV,
  trial registry, deflation) and ADR-0007 (LabelSpec lifespans → purge/embargo/uniqueness)

## Context

Module 5 is closed and its two open threads are wired (trial registry into `Study.run`,
sample-uniqueness weighting). Phase 3 begins by running **one real GBM** through the closed
framework and letting it pull requirements — not by building a three-library abstraction up front.
Four decisions are forced before that run; this ADR records them (they were made in review, not
derived here) and gates the one new dependency and the one interface change they require.

## Decisions

### 1. LightGBM is the first (and, for now, only) model dependency

`lightgbm` is added as a runtime dependency (ADR-gated, §4). Chosen first for: native NaN handling
(our features carry warm-up nulls, §dataset), speed on ~3.6M rows, and a sklearn-style
`fit(X, y, sample_weight=…)` / `predict_proba`. **No XGBoost/CatBoost and no multi-library
abstraction yet** — an unused abstraction is a liability (§10). One model, real, first.

### 2. The Model protocol gains a Study-supplied validation fold — Study owns the inner split

Early stopping (and, later, calibration) needs a held-out validation fold carved from *inside* each
training fold, and to not leak it must be **purged/embargoed** against that fold. The invariant
settles ownership: if `fit` accepted a raw eval set the model built itself, purge correctness would
move inside three libraries' native APIs where the framework cannot test or enforce it — a purge
boundary outside the framework, which "Study is the only door" (§7) forbids. Therefore:

- `Model.fit` gains an optional, keyword-only `validation: FitValidation | None = None`, where
  `FitValidation` carries **already-separated, already-purged** `(x, y, sample_weight)` arrays.
- **`Study` carves the inner purged split** from each outer training fold (the last fraction by
  decision order, with the same lifespan-overlap purge as the outer split) and hands the model the
  inner-train arrays plus the `validation` set. **The model never sees timestamps and never carves
  anything.** Models that don't need it ignore `validation` (default `None` keeps every existing
  call working).
- This is opt-in per `Study` (`inner_val_frac`); off by default so the Phase-1/2 reference models and
  the deflation harness are unchanged.

### 3. Calibration consumes the same Study-owned inner fold (answers design question b)

Phase-8 sizing needs probabilities calibrated inside each fold. The calibrator fits on the **same
inner purged validation fold** Study carves for early stopping — one purged inner split serves both.
The calibrator is a wrapper *around* the model that Study feeds the inner fold; it never owns a split
or sees timestamps, for the same reason as (2). Not built now (Phase 8), but the mechanism it will
consume is the one this ADR establishes.

### 4. Train binary on resolved rows; score P(+1) (answers design question a, as a default)

The GBM trains on the **resolved (`±1`) rows only** — the 745k timeout (`0`) rows are dropped from
`fit` — and scores `P(+1)`. Rationale: align the training objective with the binary sign-AUC actually
scored (ADR-0009), and treat timeout-as-abstain as the meta-labelling problem that was **explicitly
deferred to Phase 8**. Three-class-trained / two-class-scored would buy the model the "no clean move"
regime, but that is the meta-labelling value deferred on purpose; Phase 8 earns it back if it matters.
This is a **stated default, not a closed decision** — a real model may pull a change by hitting
friction.

## Consequences

- **Built now:** `lightgbm` dependency; `FitValidation` + `Model.fit(validation=…)`; `Study`'s inner
  purged-split carving (`inner_val_frac`); a `LightGBMModel` adapter (binary-on-resolved, early
  stopping on the Study inner fold, `sample_weight`); the first real run on the assembled dataset,
  reported with trial count, weighted AUC, and deflation.
- **Reserved:** XGBoost/CatBoost and any multi-library abstraction; the calibration wrapper (Phase 8).
- **Interfaces committed (later change needs a new ADR, §3):** `Model.fit`'s `validation` parameter
  and `FitValidation`; `Study`'s inner-fold contract (Study carves, model consumes).
- **CI:** the adapter runs against recorded/synthetic data, never a live service; the LightGBM
  determinism is pinned (fixed seed, single thread in tests) so results are reproducible (I6).

## Open questions (pulled by the real run, not pre-solved)

- Whether early stopping on a single trailing inner fold is stable enough, or the inner split should
  itself be a small purged CV — decided by watching the first run's variance across outer folds.
- LightGBM hyperparameter ranges worth registering as trials — the first tuning pass will show which
  matter; each is a registered trial so the deflation counts them.
