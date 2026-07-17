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

## Results (appended after the run — 2026-07-16)

Ran once against the pre-declared breakevens. Both arms registered as trials.

| arm | quantile | tail accuracy | vs 1× breakeven (65.4%) |
|---|---:|---:|---|
| global (most generous) | 0.10 | **0.5133** | below |
| global (most generous) | 0.01 | **0.5174** | below |
| within-bucket (conditional) | 0.10 | 0.5089 | below |
| within-bucket (conditional) | 0.01 | 0.5093 | below |

**VERDICT (pre-declared rule): best tail 0.5174 < 65.4% → signal present but NOT tradeable →
DEATH-AT-COST → new features. Do not build the spread lake.**

### The edge does not concentrate — that is the finding

Going from the decile to the **percentile** — a 10× tightening of the confidence filter — moves
accuracy by **+0.4pp** (0.5133 → 0.5174). A concentrated edge would climb steeply as the filter
tightens; this one is flat. The signal is **diffuse and uniformly weak**, exactly as AUC 0.5072
implied, and the tail hypothesis — the only thing that could have rescued it — is falsified.

The conditional (non-calendar) tail is weaker still (0.5089/0.5093), consistent with EXP-003: the
part that isn't the clock is the smaller part.

**Even the best tail loses money by a wide margin.** At 51.74% accuracy on a 20.03 bps barrier the
gross expectancy is `(2×0.5174 − 1) × 20.03 = 0.70 bps` against **6.15 bps** of round-trip cost —
still **~9× short**, i.e. ≈ −5.5 bps per round trip at 1×, before §8's 2× bar is even considered.

**Decisive against its own resolution.** The gap (65.4% − 51.7% = **13.7pp**) is ~2.5× the
percentile tail's 3σ resolution (±5.4pp) and ~8× the decile's (±1.7pp). This is not a
power-limited null.

### What this settles

**Signal-vs-tradeable — the distinction sign-AUC structurally could not make, and costs can.** The
arc is complete and each step was a real answer:

- **EXP-001** — a directional edge exists: AUC 0.5289, 18.8σ, survives a 12-way search.
- **EXP-002/003** — about half of it was a **calendar** (base rate), not timing; ~53% survives as
  genuine within-minute conditional signal (AUC 0.5072, +4.38σ).
- **EXP-004** — that surviving signal is **real but ~43× too small to trade**, and it does not hide
  in a tail.

The honest conclusion: **this feature family — lagged returns, EWMA/range vol, relative volume on
1-min bars — does not carry tradeable directional timing on TSLA.** No tuning within it changes that;
the ceiling is the features, and it is an order of magnitude below the cost floor. The next move is
**genuinely new features**, not variants of these. The well is dry and we know why.

### Caveat status

The placeholder commission rates never became load-bearing: they are 0.28 of the 6.15 bps, and the
verdict is a 9–43× miss. A death verdict is safe against any plausible commission schedule, so the
§8 "supply your real rates" requirement is **not** a blocker for *this* conclusion. It becomes
mandatory the moment any candidate strategy gets near the cost line.
