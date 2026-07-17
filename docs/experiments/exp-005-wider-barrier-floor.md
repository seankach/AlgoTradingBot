# EXP-005 (pre-registered): does the cost floor actually come down at (k=6, H=270, RTH)?

- **Status:** PRE-REGISTERED — committed to git **before** the run.
- **Date registered:** 2026-07-16
- **Charter refs:** §6 (k/H are config values; raise H for longer holds), §8 (frozen costs; the bar is
  **2×**), I3 (the label **is** the exit policy — changing k/H is a new strategy, not a re-cut);
  EXP-004 (death-at-cost at k=2)

## Why

EXP-004 killed the k=2 setup: barrier 20 bps vs 6.15 bps round-trip cost → 1× breakeven **65.4%**
against an observed ~51.7%. The structural finding that followed is that **H was never the lever**:

    upper = entry_open * (1 + k*sigma);  exit_price = upper|lower at a touch
    => |gross_return| = k*sigma, INDEPENDENT of H.

H is the **timeout**, not the barrier. Raising H 30→120 leaves barrier, cost, and breakeven exactly
where they were; it only lowers the timeout rate. **`k` is the lever.** Measured σ̄ = 10.03 bps
(all-session) / 13.47 (RTH), and `k=2 → 20.06 bps` reproduces the measured 20.03 — the model is
exact, so any `k` can be priced directly. RTH compounds two advantages: **higher σ** (13.47 vs 10.03
→ wider barrier) and **tighter spread** (2.20 vs 3.47 → cheaper). The promising cell:

| scope | k | H≈7.5k² | barrier | cost 1× | BE 1× | **BE 2× (§8's bar)** |
|---|---:|---:|---:|---:|---:|---:|
| all-session | 2 | 30 | 20.1 | 6.15 | 65.3% | 80.7% |
| **RTH-only** | **6** | **270** | **80.8** | **4.88** | **53.0%** | **56.0%** |

The `H≈7.5k²` column is a **random-walk estimate, not a measurement**. This experiment turns the
estimated cells into measured ones.

## What is measured (no model, no features)

Re-label the 2021–2025 **RTH-only** series at **k=6, H=270** and measure:

1. **Barrier magnitude** — mean/median `|gross_return|` of resolved labels (predicted 80.8 bps).
2. **Timeout rate** — the k² estimate's actual test (predicted "similar to today's 11.2%").
3. **Round-trip cost** — from the measured RTH spread + frozen `config/costs.yaml` (predicted 4.88).
4. **Resulting 1× / 2× breakeven** (predicted 53.0% / 56.0%).
5. **Session-crossing fraction** — see below; found while scoping, measured not assumed.

**New strategy, not a re-cut (I3).** k/H are config (§6), and the label *is* the exit policy, so this
mints a **new `label_spec_version`** and a **new `dataset_id`**. Prior results are untouched and
remain valid under their own spec. Registered as a trial against the new `dataset_id`.

## A problem found while scoping — measured, not assumed

`TripleBarrier.generate` walks `h_bars` over the **traded bar series**. RTH is ~390 bars/day, so a
270-bar window fits inside one session only for decisions in the first ~120 bars (09:30–11:30):
**~69% of RTH decisions would walk into the next day's session.** Two consequences, both reported:

- The "~4.5h intraday hold" framing would be **wrong** — it is mostly a **multi-day swing**, with a
  different risk profile (overnight gap exposure) than anything tested so far.
- `exit_price = upper|lower` assumes a fill **at** the barrier. That is ~true intraday and **false
  across an overnight gap**, where price opens through the level. So `gross_return` would be
  **optimistic** for gap-crossing exits — negligible at H=30, material at H=270.

This does **not** move the breakeven arithmetic (barrier = k·σ and cost are both independent of H),
but it changes **what the strategy is** and whether the barrier-fill assumption holds. It is part of
the finding.

## The read — declared before the run, against the **2×** floor

- **Confirms the cell** — measured barrier ≈ 80 bps, cost ≈ 4.9 bps, **2× breakeven lands ~55–56%**,
  and the timeout rate is not pathological → **the door is unbolted** → a **separate, pre-registered
  feature experiment** is authorised.
- **Materially off** — if the measured timeout rate, barrier, or RTH spread at this longer horizon
  moves the 2× breakeven **outside ~55–57%** → **that is the finding.** Report it; do **not** proceed
  to features on a floor that moved.
- **Session-crossing is reported either way** and qualifies any "door unbolted" verdict: if most
  exits cross a gap, the honest statement is "the floor is lower *for a multi-day swing strategy*",
  which is a different thing to go build features for.

## What this experiment does and does **not** establish

**Does:** whether the cost floor is still arithmetically foreclosing at a wider barrier.

**Does NOT:** say anything about whether **any signal exists** at a ~270-bar / ~80 bps horizon. **A
lower floor does not summon an edge.** The current 1-min microstructure features (lagged returns,
EWMA/range vol, relative volume) are the **least likely** candidates at this horizon. The verdict is
strictly **"door unbolted / still bolted"** — and even an unbolted door leads to a *separate,
pre-registered feature experiment*, **not** to a model run on the existing features at the new
horizon. That would be exactly the reflex this framework exists to stop.

## Noted for the record (an ADR-0010 §5 gap at the label level)

Changing the label spec mints a new `dataset_id`, which starts a **fresh trial count**. So
**label-spec search is not counted by the registry** — trying (k, H) combinations until the
arithmetic works would be invisible to the deflation, the same class of hole as notebook search. This
experiment's (k=6, H=270) is **derived from the measured arithmetic table, not searched**, and this
pre-registration is the record of that. Worth an ADR follow-up.

---

## Results (appended after the run — empty until then)

_pending_
