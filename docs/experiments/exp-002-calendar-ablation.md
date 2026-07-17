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

## Results (appended after the run — 2026-07-16)

Ran once, exactly as registered. Three trials registered (15 total on this dataset with EXP-001's 12).

| trial | features | wAUC | share of full's excess |
|---|---:|---:|---:|
| **calendar floor** (clock alone) | 4 | **0.5225** | **77.9%** |
| **market-only** | 7 | **0.5108** | 37.3% |
| full (EXP-001 winner) | 11 | 0.5289 | 100% |

**VERDICT (pre-declared rule): calendar_excess (0.0225) ≥ 0.5 × full_excess (0.0145) →
SUBSTANTIALLY BASE-RATE → back to FEATURES.**

### What this means

**The edge is mostly a calendar.** A model with **no market information whatsoever** — only
`minute_of_day` and the session flags — reaches **0.5225**, capturing **78%** of the entire edge.
That is base-rate quoting: some times of day and sessions carry a directional skew, and the model
ranks by it with **zero timing ability**. There is no per-trade signal to execute against.

**The market features carry almost nothing.** Market-only is **0.5108** — real (≈7σ above the
measured null std of 0.00154) but ≈0.011 of AUC. Adding all seven market features to the clock lifts
the full model from 0.5225 to only **0.5289** (+0.0064).

**The parts over-sum (78% + 37% = 115%)** — calendar and market signal are partially redundant, so
the market features are substantially re-expressing the same intraday pattern rather than adding
independent information.

**This is what the ablation was for.** EXP-001's headline 0.5289 was hiding this, and the Phase-5
cost gate run first would have **green-lit a mirage** — building a cost model around a clock.

### Consequences

- **Next step is better features, not a wider grid and not a nudged label** (foreclosed by
  pre-registration). The current market feature set — lagged returns, EWMA/range vol, relative
  volume — carries ~0.011 of AUC. That is the honest ceiling of *this* direction.
- **Open design question for the next round:** should `minute_of_day` / session flags be in a
  *directional* model at all? They are what let it quote a base rate that isn't tradeable alpha.
  Either exclude them, or de-mean the target by session base rate so the model must earn its AUC
  from conditional timing.
- The calendar tilt itself may be a real intraday seasonality, but it is a drift/seasonality play,
  not the timing model we thought we had — and at 0.0225 of AUC it would need its own honest
  evaluation, almost certainly cost-dead.
