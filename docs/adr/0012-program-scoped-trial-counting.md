# ADR-0012: Trial counting is program-scoped — label-spec search must be charged too

- **Status:** Proposed
- **Date:** 2026-07-16
- **Deciders:** Romesh Sharma (pending)
- **Charter refs:** §6 (k/H are config), §7, §8, I3 (the label **is** the exit policy); amends
  **ADR-0010** (trial identity + §5 threat model); found in **EXP-005**

## Context

ADR-0010 made the trial count structural: `Study` registers every config it scores, and the
deflation charges `K = COUNT(DISTINCT trial_hash)` for a `dataset_id`. That closes model-space
search. It does **not** close **label-space** search.

Trial identity contains `dataset_id`. Changing the label spec (`k`, `H`, session scope) mints a
**new `dataset_id`** — correctly, under I3 a different exit policy is a different strategy — which
**resets the trial count to zero**. So:

> Try (k, H) combinations until the arithmetic clears, score models under each, report the best.
> Every spec starts a fresh count, so the deflation charges for **none** of the search.

This is ADR-0010 §5's threat model reappearing one level up, and unlike the notebook hole it is
**inside the framework** and therefore closable by code. EXP-005 surfaced it while *legitimately*
moving from k=2 to k=6 — that cell was derived from the measured cost arithmetic and pre-registered,
not searched. But **the next step is horizon/feature search, which is exactly where the hole gets
exploited**, intentionally or not. It must close first.

## Options considered

- **Rely on pre-registration** (rejected). Pre-registration is the backstop for what code *cannot*
  see (ADR-0010 §5). This is something code *can* see; using discipline where a mechanism is
  available is the exact trade ADR-0009/0010 refuse to make.
- **Count label specs and multiply K by the number tried** (rejected). Wrong quantity: a spec under
  which no model was ever scored reveals nothing about signal, so multiplying by it over-charges in
  a way that is arbitrary rather than conservative.
- **Program-scoped counting** (chosen). Introduce a `program_id` that is **stable above
  `dataset_id`**, and count distinct model trials **across the program** — all label specs included.
  A label-spec change no longer resets anything.

## Decision

### 1. `program_id`: a stable key above `dataset_id`

A **research program** is a line of enquiry against a thesis (e.g. `tsla-directional-v1`). It is
**declared in the pre-registration**, never derived from the data — so it cannot be reset by
changing a spec. `TrialSpec` gains `program_id`; the `trials` table gains the column.

### 2. The deflation's `K` is counted over the program, not the dataset

`K = COUNT(DISTINCT trial_hash) WHERE program_id = ?` — spanning every `dataset_id` and label spec in
the program. `auc_deflation`'s `n_trials` is sourced from that count. **A new label spec inherits the
running count; it does not start one.**

### 3. Signal-independent label-spec selection is recorded but charges nothing

A label spec chosen on a criterion that **never observes model performance** — cost arithmetic
(barrier vs spread), timeout rate, sample size — cannot inflate a signal statistic, because no
signal was looked at. Such specs are **recorded** in the registry (auditable) and contribute **0** to
`K`. Every spec under which a **model was scored** counts, because that is when signal was observed.

**The guard is that the criterion must be pre-declared.** Claiming "signal-independent" *post hoc* is
the loophole; the pre-registration is what makes it checkable. EXP-005 is the worked example: k=6 was
chosen by measured barrier/cost/timeout, no model was run, so it contributes 0 — and the
pre-registration proves that was the criterion before the number existed.

### 4. Conservative by construction

`K` counts every trial scored in the program, including diagnostics (ablations, tail checks), not
only "promotion candidates". A subtler rule — count only trials that were *candidates for promotion*
— reintroduces exactly the discretion this ADR removes. Over-charging is the safe direction for a
deflation.

**Concrete consequence, on the record:** the running count for the TSLA directional program is
already **19** — EXP-001 (12) + EXP-002 (3) + EXP-003 (2) + EXP-004 (2). EXP-005 registered a
re-label under a signal-independent criterion and contributes **0**. **The feature experiment's
deflation therefore starts at K = 19, not K = 0**, and each new config increments from there.

## Consequences

- **Schema/interface (ADR-gated):** `program_id` on `TrialSpec`, `Trial`, and the `trials` DDL;
  `TrialStore.count_program(program_id)`; `Study.run` registers it; `auc_deflation` takes `K` from
  the program count. Pre-registrations must declare `program_id`.
- **Prior experiments are re-keyed, not re-run** — their trials belong to `tsla-directional-v1`.
- **The residual hole, stated:** one can always *declare a new program*. That is the same class as
  the notebook hole and cannot be closed by code — a new program is legitimate only for a genuinely
  different instrument or a thesis unrelated to the prior search, must be justified in the
  pre-registration, and is never a quiet re-key. The audit trail is the only guard, so it must exist.
- **What this does not do:** it does not make label-space search *wrong* — searching horizons is
  legitimate research. It makes it **charged**, so a result found after searching 5 specs × 12
  configs is deflated as the 60-way bet it was.

## Open questions

- Whether `program_id` should be an explicit config value or derived from a declared thesis string in
  the pre-registration (leaning explicit config, so it appears in the manifest and the `dataset_id`
  provenance chain).
- Whether signal-independent specs should carry a *recorded reason code* in the registry (leaning
  yes — it makes the §3 guard auditable without reading prose).
