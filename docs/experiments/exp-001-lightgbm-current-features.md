# EXP-001 (pre-registered): does the current feature set carry a directional edge?

- **Status:** PRE-REGISTERED — committed to git **before** the run. Results appended only after.
- **Date registered:** 2026-07-15
- **Registered by:** Romesh Sharma (design approved) / Claude (execution)
- **Charter refs:** §7 (validation), §10 (Phase 3), ADR-0009/0010/0011; ADR-0010 §5 (trial-count
  threat model — this document *is* the cross-session pre-registration that the in-session trial
  count cannot enforce)

## Why this exists

The framework is trusted; the remaining risk is fitting the data through many small honest-looking
decisions across sessions (a feature added after a flat week, H nudged 30→20). The deflation counts
trials **in a session**, not the ones in the researcher's head. This document forecloses that by
declaring the model space, span, and verdict rule **before** any number is produced. A null result —
"no directional edge in these features" — is the **expected and acceptable** outcome and a success.

## The one question

Does the **current feature set** carry any deflation-surviving directional signal, *before costs*?
This tests direction only; tradeability (costs at 1×/2×/3×) is Phase 5 and is **not** answered here.
A pass is necessary, not sufficient. The lockbox is **not touched**.

## Frozen inputs — no change during or after the run

- **Features (11, fixed):** `ret_1b, ret_5b, ret_15b, ret_30b, ewma_vol, range_vol, rel_volume,
  minute_of_day, is_pre, is_rth, is_post`. No feature engineering this round.
- **Label spec (fixed):** triple-barrier, H=30, k=2. **Not nudged.**
- **CV (fixed):** `PurgedCPCV(N=6, k=2)` → 15 paths; purge=H, embargo=max(H,1%); weighted binary
  sign-AUC (sample-uniqueness weighting on). CPCV groups are contiguous in time, so every path's
  test fold spans a different regime — including the **2022 bear** — and a single-regime artifact
  cannot pass.
- **Model (fixed):** `LightGBMModel`, binary on resolved rows, P(+1), early stopping (rounds=50) on
  the Study-owned purged inner fold (`inner_val_frac=0.2`), deterministic (seed=0, 1 thread).

## Span, and why 2021–2025 (not all history)

**PRE+RTH+POST, 2021-01-01 → 2025-12-31.** Including 2010–2013 is not conservative, it is
**contaminating**: those years carry 44%→27% timeout rates and untradeable early-TSLA spreads, so
training across them is training across two different instruments, and the model can ride the
**non-stationary base rate** (timeout% halving over the decade) as fake skill. 2021–2025 is one
tradeable regime with genuine variety (2021 momentum, 2022 bear, 2023–24 recovery, 2025).

## Effective n sets the subsample — not a round number

Raw rows overstate power; after uniqueness weighting the independent-sample budget is what resolves a
weak edge. Measured on the span:

| subsample | raw rows | effective n (Σ uniqueness) |
|---|---:|---:|
| full span | 1,202,854 | 210,640 |
| stride 5 | 240,571 | 159,201 |
| **stride 15 (chosen)** | **80,191** | **73,893** |
| stride 30 | 40,096 | 40,095 |

**Resolution check (the point of this section).** The resolution-limit table (effective n → smallest
resolvable ρ, 2σ band) gives ρ≈0.009 at effective n≈74k. We care about edges down to **ρ≈0.05**
(AUC≈0.528, the bottom of the real-intraday band); 0.05 sits **~4–5× above** the 74k noise floor —
resolved with margin, with headroom for LightGBM's higher capacity widening the null. stride 30
(40k effective, ~3.8× margin) would also suffice; stride 15 is chosen for the extra cushion at ~1h
compute. **We do not thin to a convenience n.**

## Search budget — this is the entire trial count (K = 12)

The full grid, declared: `num_leaves ∈ {15, 31, 63}` × `learning_rate ∈ {0.03, 0.10}` ×
`min_child_samples ∈ {50, 200}` = **12 configs**, each a registered trial. `num_boost_round=2000`,
`early_stopping_rounds=50`. **No adaptive additions; K stays exactly 12** — a wider grid is a larger
multiple-testing charge the deflation correctly makes us pay, so "widening to be safe" is forbidden.

## Deflation — properly powered

Best config's `auc_deflation(K=12, B=300)`, computed at **3 seeds**. Certification requires the
estimate **stable across seeds (spread < 0.05)**, not a single lucky null.

## Verdict rule — declared now, binding

Read on the best config's deflation (charged for K=12):

- **deflation < 0.5** (best AUC inside the noise band) → **no directional edge in these features.**
  The honest negative. Next step is **better features** — *not* a wider grid, *not* a nudged label.
- **deflation > 0.9 and stable across seeds** → a weak-but-real directional signal survives the
  12-way search → earns the **next gate (cost analysis, Phase 5)**. Not a trade signal.
- **0.5 ≤ deflation ≤ 0.9** → ambiguous. This band **also sends us back to features** — not to a
  wider grid and not to a nudged label. The pre-registration forecloses those by construction.

---

## Results (appended after the run — 2026-07-15)

Ran once, exactly as registered. 77,661 rows (stride 15), K=12 trials registered.

- **All 12 configs cluster tightly:** weighted AUC **0.5250 – 0.5289** — the signal is in the
  *features*, robust to every hyperparameter in the grid, not a config artifact.
- **Best:** wAUC **0.5289** (`num_leaves=31, learning_rate=0.03, min_child_samples=200`).
- **Deflation (K=12, B=300):** **1.0000 at all three seeds**, seed-spread **0.0000** (stable). The
  best AUC is above *all* 300 permutation nulls at every seed — a ~5–6σ separation at this effective
  n, so charging for the 12-way search does not touch it.

**VERDICT (by the pre-registered rule): a weak but real directional edge survives the 12-way search
→ next gate: cost analysis (Phase 5).**

**Reading it honestly.** This is *not* "no edge" — there is a deflation-surviving directional signal.
But "survives deflation" means *statistically distinguishable from noise*, not *economically useful*:
0.529 AUC is a **small** edge, and at 74k effective n a small edge is easily ~5σ real while being
marginal to trade. The tight cluster across all 12 configs says two things at once — the edge is
robust (good) and it is a **feature ceiling** (sobering): more hyperparameter tuning will not move it.
The number is consistent with the ~0.51 return-feature edge seen independently by the memoriser and
the RTH LightGBM smoke test; the all-session span reads slightly higher (0.529).

**This tested direction only.** Whether 0.529 AUC beats half-spread + commissions at 1×/2×/3× costs
is the real question and is Phase 5. The honest expectation remains that a directional edge this weak
may not survive costs — and that finding, when it comes, is also a real answer. Next step is the
cost gate on this edge, *not* a wider grid or a nudged label (foreclosed by pre-registration).
