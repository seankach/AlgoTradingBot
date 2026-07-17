# EXP-004 (pre-registered): is the edge concentrated in a tradeable tail?

- **Status:** PRE-REGISTERED — committed to git **before** the run.
- **Date registered:** 2026-07-16
- **Charter refs:** §8 (frozen cost model; 1×/2×/3×; survive-2×-or-not-a-strategy), ADR-0010/0011;
  EXP-003 (operative verdict: within-bucket timing detectable, AUC 0.5072)

## Why this, and why not the full cost gate

EXP-003 found a **real** within-bucket (non-calendar) timing signal: conditional AUC **0.5072**,
+4.38σ. The arithmetic then forecloses the **average** edge, using only measured quantities and the
frozen `config/costs.yaml`:

    barrier |gross_return| : mean 20.03 bps, median 17.30 bps   (n=1,067,734 resolved, 2021-2025)
    BID_ASK spread on-span : median 3.47 bps                     (n=1,202,943)

    round-trip cost @1x = half-spread 3.47 + impact 2.00 + commission 0.28 + fees 0.40 = 6.15 bps
      1x  6.15 bps -> breakeven accuracy 65.4%
      2x 12.30 bps -> breakeven accuracy 80.7%     <- §8's promotion bar
      3x 18.45 bps -> breakeven accuracy 96.1%     <- cost ≈ the entire barrier

AUC 0.5072 implies ~**50.4%** average accuracy → expectancy ≈ **0.14 bps/trade against 6.15 bps of
cost — short by ~43×**. No sizing or threshold closes a 43× gap.

**But AUC is an aggregate.** A model can be noise almost everywhere and highly accurate in a small
high-confidence tail while still scoring ~0.507. The arithmetic forecloses the *average* edge, not a
*concentrated* one — and assuming otherwise would be assuming the conclusion. So: test the tail,
which reuses the existing model and needs **no spread lake**. Building the full spread-lake + fill
model to price an arithmetically-dead average edge is the mirror of building one around a mirage.

## The test

Out-of-fold directional accuracy of a **trade-only-the-extremes** rule on the EXP-003 **market-only**
model (per the scoping decision: *not* full-11, whose +0.0082 rests on a fragile per-minute mapping
from ~96 rows/bucket): go long the top quantile of score, short the bottom, and measure the weighted
accuracy of exactly those trades — the number a cost breakeven applies to.

- **Quantiles: 0.10 (decile) and 0.01 (percentile).** Fixed; not a knob.
- **Two arms, both registered as trials:**
  1. **global tail** — ranks on the raw score. *The most generous test*: it contains all the signal
     the model has, calendar-proxy included. If even this fails, the conditional tail (a subset)
     certainly fails, so a death verdict here is robust.
  2. **within-bucket tail** — ranks inside each 1-min bucket: the conditional/non-calendar tail that
     EXP-003 actually measured and that the cost gate was scoped on.
- Everything else identical to EXP-003: span, stride-15 subsample, H=30/k=2, `PurgedCPCV(6,2)`,
  LightGBM at the EXP-001 winning hyperparameters, purged inner fold, uniqueness weighting.

## The read — declared before the number

- **Tail accuracy < 65.4%** (the 1× breakeven) → **signal present but NOT tradeable → death-at-cost
  → go to new features.** This is the **complete answer**: it settles *signal-vs-tradeable*, the
  distinction sign-AUC structurally could not make and costs can. It is a success, not a failure.
- **Tail accuracy ≥ 65.4% in a tail of meaningful size** → the concentrated edge survives the
  arithmetic → **then** the full spread-lake + fill-model gate is worth building (and §8's real bar
  is the 2× number, 80.7%).
- Between-arms disagreement (global clears, within-bucket doesn't) → the concentration is calendar,
  not timing → new features.

**What this test can and cannot resolve.** Decile tail ≈ 7,766 rows → accuracy resolved to ~±0.6%
(1σ), ~±1.7% (3σ). Percentile tail ≈ 777 rows → ~±1.8% (1σ), ~±5.4% (3σ). The gap under test
(65.4% breakeven vs ~50–51% expected) is **an order of magnitude larger than the resolution**, so the
test is decisively powered for the question at both quantiles. It cannot resolve differences of a
percent or two in the percentile tail — irrelevant to a 14-point gap.

## Standing caveats

- **Commissions are placeholders.** `config/costs.yaml` states in its own header that the rates are
  IBKR's *published* Tiered schedule and must be replaced with the account's **exact** rates before
  any result is trusted (§8: the developer supplies this number). They are 0.28 of the 6.15 bps, so
  they **cannot rescue a 43× gap** and a death verdict is safe against them — but **any
  surviving-tail result is provisional** until the real schedule is supplied.
- **If the tail dies, the spread lake does not get built.** It is Phase-5 groundwork, but there
  would be nothing to price.

---

## Results (appended after the run — empty until then)

_pending_
