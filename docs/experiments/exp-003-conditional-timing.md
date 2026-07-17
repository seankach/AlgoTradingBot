# EXP-003 (pre-registered): once you can't profit from the clock, is any timing signal left?

- **Status:** PRE-REGISTERED — threshold committed to git **before** market-only ran.
- **Date registered:** 2026-07-16
- **Charter refs:** ADR-0009/0010/0011; EXP-001, EXP-002 (`exp-002-calendar-ablation.md`)

## Why

EXP-002 showed EXP-001's 0.5289 is **substantially a calendar**: the clock alone reaches 0.5225
(78% of the excess), and market features add only +0.0064 once it is present. The remaining question
is the only one that matters: **once you cannot profit from knowing the clock, is there any
return/vol timing signal left?**

## De-meaning cannot answer this — proof, and what replaces it

The prescribed method was "de-mean the target by the session base rate". It is **inert for a rank
statistic on binary labels**: for `y ∈ {−1,+1}` and `b = E[y|bucket] ∈ (−1,1)`,

    y=+1 → r = 1−b > 0 ;  y=−1 → r = −1−b < 0  ⟹  sign(r) = sign(y) always.

The residual target has identical sign structure, so a sign-AUC on it reproduces the raw number
exactly. The calendar does not flip any label's sign — it shifts **class balance between buckets**,
and AUC pays it through pos/neg pairs drawn from *different* buckets. Only a **between-bucket**
operation removes it.

**Replacement: conditional (within-bucket) weighted AUC** — only same-bucket pos/neg pairs count.
Inside a bucket the base rate is constant and can contribute nothing. It also **fits no base rate**,
so removing the calendar cannot itself leak: there is no estimated quantity to contaminate with
test-period information. (A base-rate *offset* retrain is unnecessary and is not run: the metric,
not the training target, is what removes the calendar.)

## Bucket = 1 minute — forced, and decidable before any result

**Principle, stated in advance: the bucket must be at least as fine as the finest calendar feature.**
`minute_of_day` has 1-minute resolution, so:

| bucket | calendar-only conditional AUC | verdict |
|---|---:|---|
| 30-min (initial choice) | **0.5068** | **instrument leaks** — the model still ranks by time *inside* a bucket |
| **1-min (adopted)** | **0.5000 exactly** | calendar constant within bucket → removed **by construction** |

At 30-min the calendar-only control *failed its own premise*, which made market-only there (0.5062)
uninterpretable — indistinguishable in size from the leak itself (0.5068). The 1-min choice is a
**repair of a broken instrument, not a tuned knob**: it is provable (0.5000, exactly) **before**
market-only is run, and it is forced by the principle above rather than selected for an outcome.
Bucket count is **not** a free parameter hereafter; if the result is ambiguous the response is
*report ambiguous and go to new features*, never re-bucket.

## Measured 1-min conditional null (B=150) — the threshold's basis

    mean 0.50000   std 0.00164   (1.07x the global null 0.00154 — power cost negligible)

The predicted "2–3× wider" conditional null is **falsified by measurement**: pooling ~805 buckets of
~96 rows uses every sample, so the variance is governed by effective n, not by the pair count.

**PRE-DECLARED THRESHOLD = null mean + 3σ = 0.50492.** Mechanical, derived from the null alone.

## The read — power-bounded, declared before market-only runs

- **market-only ≥ 0.50492** → a within-bucket timing signal is **detectable** → it is genuine
  conditional timing (not the clock) → earns the next gate: **Phase-5 cost analysis**.
- **market-only < 0.50492** → **"no within-bucket timing signal *detectable at this power*"** →
  next move is **genuinely new features**. This is **not** "signal proven absent."

**Effect size this test can and cannot resolve.** At 3σ it resolves an AUC excess ≥ **0.00492**
(AUC 0.5049), i.e. **ρ ≥ 0.0087**. Real intraday edges live at ρ ≈ 0.05–0.20 (AUC 0.528–0.614), so a
null here rules out anything in the real-edge band **with large margin** — an informative negative.
Anything below ρ ≈ 0.0087 is invisible to this test and remains **unknown**, not disproven.

## Trials (registered; the feature set is now part of trial identity, ADR-0010 amendment)

1. **market-only** (7 return/vol features) — the question.
2. **full-11** — control. Since calendar-only is 0.5000 by construction at 1-min, the calendar
   features should add nothing within-bucket; full ≈ market-only. If full materially exceeds
   market-only, calendar features carry within-bucket signal, which would be surprising and worth
   knowing.

Everything else identical to EXP-001/002: span PRE+RTH+POST 2021–2025, stride 15 (77,661 rows / ~74k
effective), H=30/k=2, `PurgedCPCV(6,2)`, LightGBM at the EXP-001 winning hyperparameters, inner
purged fold for early stopping.

## Disclosure

The **30-min** market-only conditional AUC (0.5062) was seen incidentally — measuring the 30-min null
necessarily produced it — and that measurement is what exposed the instrument leak. The **1-min**
market-only value is **unrun** as of this commit. The threshold above is mechanical (`null mean +
3σ`) from the 1-min null, computed from shuffled labels only; the observed plays no part in setting
it, so no latitude exists.

---

## Results (appended after the run — 2026-07-16)

Ran once against the committed threshold. Two trials registered.

| trial | conditional AUC (1-min) | σ vs null | vs threshold 0.50492 |
|---|---:|---:|---|
| calendar-only | **0.5000** | 0.00 | (by construction — validity proof) |
| **market-only** | **0.5072** | **+4.38** | **clears** |
| full-11 | **0.5154** | +9.39 | clears |

**VERDICT (pre-declared rule): market-only 0.5072 ≥ 0.50492 → a within-bucket timing signal is
DETECTABLE → Phase-5 cost analysis.**

### The full-11 control was the surprise, and it is *not* base rate

`full_11 − market_only = +0.0082`. The calendar features add within-bucket signal **despite scoring
exactly 0.5000 alone**. That is not a contradiction and it is not base-rate quoting — the conditional
metric makes base-rate quoting arithmetically impossible. It is **interaction**: constant-within-a-
bucket features cannot *rank* inside a bucket, but a tree can use them to *condition* — learning that
`ret_30b` means something different at 09:35 than at 15:50. The market signal's shape is
time-dependent, and conditioning on time helps. It is out-of-sample (CPCV, purged), so it is real,
not in-sample fitting — though a per-minute mapping learned from ~96 rows/bucket may be regime-fragile.

### This revises EXP-002's headline

EXP-002 reported "78% of the edge is calendar", but that number was **what the calendar achieves
*alone*, globally** — not the fraction of the edge that *is* calendar. The conditional decomposition
is the sharper instrument. For the same config and data:

    full, GLOBAL AUC       0.5289   (excess 0.0289)   [EXP-001]
    full, CONDITIONAL AUC  0.5154   (excess 0.0154)   [EXP-003]
    -> between-bucket calendar ≈ 0.0135  (47% of the excess)
    -> within-bucket, genuine  ≈ 0.0154  (53% of the excess)

So the edge is **roughly half base-rate calendar, half real conditional timing** — not "mostly a
calendar." EXP-002's conclusion is superseded on methodological grounds (its comparison conflated
"what the calendar can do alone" with "how much of the edge is calendar"), **not** because EXP-003 is
newer or more favourable. See the flag below.

### Two things this does NOT mean

1. **Not "we have alpha."** The surviving signal is tiny — AUC 0.5072 (market-only) to 0.5154 (with
   time-conditioning), i.e. 0.007–0.015 of excess. "→ Phase-5 costs" means *there is a non-calendar
   signal worth costing*, not that it will survive half-spread + commissions. A directional edge this
   weak remains the most likely thing to die at the cost gate, and that would still be a real answer.
2. **The two pre-registered rules disagree** (EXP-002 → back to features; EXP-003 → costs). That
   pattern — run another experiment, get the permissive answer — is exactly the shape of
   experiment-shopping, and it deserves naming even though EXP-003 was authorised as a *repair* of a
   broken instrument rather than a second bite. The adjudication is the reviewer's, not the
   experimenter's, precisely because the experimenter has an obvious pull toward "go".
