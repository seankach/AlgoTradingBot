# EXP-002 (pre-registered): is EXP-001's edge alpha, or a calendar?

- **Status:** PRE-REGISTERED — committed to git **before** the run. Results appended only after.
- **Date registered:** 2026-07-16
- **Charter refs:** ADR-0009/0010/0011; EXP-001 (`exp-001-lightgbm-current-features.md`)

## Why

EXP-001 found a real but tiny directional edge (wAUC **0.5289**, 18.8σ above an honest null). Binary
sign-AUC **cannot distinguish two different findings**: a model that genuinely *times* moves, versus
one that only reads the clock and quotes the **session base rate**. `minute_of_day` and the session
flags are in the feature set, and the label regime table shows the +1/−1 balance shifts across
sessions — so a pure "afternoons skew long" tilt scores above 0.5 with **zero timing ability**. That
is a calendar, not alpha: there is nothing to execute against, and it cannot survive costs. If the
edge is substantially calendar and we go to costs first, **the cost gate green-lights a mirage**.

This is an **ablation through the same Study**, not a feature-importance ranking — importance would
only tell us the model *uses* `minute_of_day`, not whether that use is base-rate quoting.

## Frozen — identical to EXP-001 except the feature set

Same span (PRE+RTH+POST 2021–2025, stride 15 → 77,661 rows / ~74k effective), same H=30/k=2, same
`PurgedCPCV(6,2)`, same weighted sign-AUC, same model and **the EXP-001 winning hyperparameters**
(`num_leaves=31, learning_rate=0.03, min_child_samples=200`). **Only the feature set varies** — that
is the whole point of the control.

| trial | feature set |
|---|---|
| **calendar floor** | `minute_of_day, is_pre, is_rth, is_post` (the clock alone) |
| **market-only** | `ret_1b, ret_5b, ret_15b, ret_30b, ewma_vol, range_vol, rel_volume` |
| **full** | all 11 (EXP-001 winner, wAUC 0.5289) |

**All three register as trials.** They are configs; the registry counts them and any future deflation
charges for them. They are **not** run outside the Study "just to check" — that is the exploration
leak the framework exists to close, and it is most tempting when you are only looking.

> **Trial-identity gap found while scoping this (ADR-0010 follow-up):** `trial_hash` does *not*
> include the feature **column set** — `feature_spec_version` is the pipeline version, not the
> selected subset. Three ablations differing only in features would hash identically and register as
> **one** trial. Worked around here by folding `feature_set` into `hyperparameters` (which is hashed),
> so the count is honest. The identity itself should be amended — filed, not silently patched.

## The read — declared BEFORE the run

Let `full_excess = 0.5289 − 0.5 = 0.0289` (the entire edge above chance).

- **PRIMARY:** `calendar_excess ≥ 0.5 × full_excess` (**calendar AUC ≥ 0.5145**) → the edge is
  **substantially base-rate** → **back to features** (the pre-registered ambiguous-band response).
- **PASS to costs requires both:** calendar AUC **< 0.5145** *and* market-only AUC **≥ 0.5217**
  (market-only retains ≥ 75% of full's excess) → a real conditional edge → **Phase-5 cost gate**.
- **Anything else → ambiguous → back to features.**

Resolution note: the measured null std at this n is **0.00154**, so these AUCs are resolved to
~±0.003 (2σ) — the thresholds above are far coarser than the noise, so the read is well-powered.
No deflation is needed for a *decomposition*; the trials still register for future charging.

---

## Results (appended after the run — empty until then)

_pending_
