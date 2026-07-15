# ADR-0010: Multiple-testing control — PBO now, DSR deferred, and how trials are counted

- **Status:** Proposed
- **Date:** 2026-07-15
- **Deciders:** Romesh Sharma (pending)
- **Charter refs:** §7 (deflated Sharpe + PBO for every reported result; sample-uniqueness
  weighting), §10 (phase plan — backtester is Phase 5/6, not Module 5), §2 I6; builds on ADR-0009
  (`Study` choke point, `PurgedCPCV`, lockbox registry) and ADR-0007 (LabelSpec lifespans →
  uniqueness weights)

## Context

Module 5 step 6 is the last piece: §7 requires **deflated Sharpe ratio (DSR)** and **probability of
backtest overfitting (PBO)** on every reported result. The obvious reading — "compute a DSR" — hides
a layering violation, and the obvious shortcut — "compute the DSR on our AUC instead of a Sharpe" —
is a statistical error. Both produce a number that *looks* like a DSR and is not one. This ADR
separates the two statistics by their real dependencies, and pins the trial count that both need,
before any code is written.

The charter's thesis applies to the evaluator itself: the dangerous failure here is a
plausible-looking multiple-testing number that means nothing, because that is *more* dangerous than
no number — it launders overfitting through a statistic people trust.

## Options considered

- **(A) Returns-series-Sharpe DSR now (rejected).** The textbook DSR (Bailey–López de Prado)
  deflates a **Sharpe ratio** computed from a strategy's **returns series**. We do not have a
  returns series: producing one needs positions, fills, and bar-by-bar costs — i.e. the
  **backtester**, which is **Phase 5/6**, not Module 5 (§10). Building a DSR now means building an
  ad-hoc slice of the backtester inside the stats module to feed it. That is out-of-layer and
  premature, and it would be a *worse* backtester than the real one — then the real one arrives and
  the two disagree. An unused/duplicated abstraction is exactly the liability §10 warns against.
- **(B) Drop AUC into the Sharpe-deflation formula (rejected).** The DSR deflation math assumes the
  trial statistic is a **Sharpe** — it uses the variance, skew, and kurtosis of the *Sharpe
  estimates across trials* to compute the expected maximum under the null. **AUC is a Mann–Whitney
  U statistic** with a different null distribution, and its null variance depends on **class balance
  and on label overlap** (concurrency), not on returns moments. Feeding AUC into the Sharpe formula
  yields a mis-specified null and a number that is a DSR in name only.
- **(C) Split the two by dependency (chosen).** PBO is rank-based and distribution-free — it does
  not care whether the metric is Sharpe or AUC — so it belongs in Module 5 and is built now. The
  true returns-series DSR is deferred to Phase 5. A trial-count guard that *is* honest on AUC —
  computed against a **correctly derived AUC null on effective sample size** — is built now under a
  **different name** (`auc_deflation`), so it is never confused with, or compared to, a future DSR.

## Decision

### 1. PBO — build now, metric-agnostic, on the AUC we already have

PBO via **CSCV** (combinatorial symmetric cross-validation) is **rank-based and distribution-free**:
it asks *how often the configuration that looks best in-sample lands below the median out-of-sample*,
using only ranks. It works identically on AUC or Sharpe. It is also the **more important overfitting
guard** for our situation (many configs, overlapping labels, a single instrument), so it is built
correctly now.

- **Input:** an `N`-trials × `S`-blocks matrix of the OOS metric (AUC per block per trial). The `S`
  blocks are contiguous, **purged** time partitions (a boundary purge between blocks, reusing the
  ADR-0009 lifespan logic, so CSCV recombination cannot leak across a block seam). CSCV forms the
  `C(S, S/2)` train/test recombinations; for each, take the IS-best trial, read its OOS rank,
  logit-transform the relative rank `ω` to `λ = ln(ω/(1−ω))`, and set **PBO = fraction of
  recombinations with `λ ≤ 0`** (IS-best is below the OOS median).
- **Design points to pin in implementation (flagged, not yet fixed):** the block count `S` (even,
  for the symmetric split) and its relation to the CPCV group count `N_groups`; whether blocks are
  the CPCV test groups themselves or an independent partition. These are the coupling knobs; they go
  in `config/validation.yaml` alongside the CPCV `N/k`, with the same "these drive the statistic"
  comment.
- **Degeneracy is a result, not an error:** PBO needs **≥ 2 trials** to mean anything (with one
  config there is no selection to overfit). With a single trial the suite reports PBO as undefined
  and says so, rather than emitting `0.0`.

### 2. DSR — defer the true (returns-series) DSR to Phase 5

No returns-series DSR is built in Module 5. It is **reserved** for when the backtester exists (Phase
5/6) and can produce a costed P&L series per trial; at that point DSR is computed the conventional
way, on the Sharpe, and *means what it conventionally means*.

### 3. `auc_deflation` — the trial-count guard we can build honestly now (its own null)

If a multiple-testing deflation is wanted before Phase 5 (recommended — otherwise there is *no*
deflation at all until then, and the trial registry PBO needs is already being built), compute it on
AUC with a **correctly derived AUC null**, and **name it `auc_deflation`, never DSR**:

- Under H0 (no skill) the per-trial AUC is ≈ Normal with mean `0.5` and variance derived from the
  **Mann–Whitney null**, evaluated on **effective n = Σ uniqueness weights**, *not* raw row count —
  the same correction that set the resolution-limit table's `1/√n` band. Overlapping labels inflate
  the apparent sample; the null must use the effective size or it will under-deflate.
- Given `K` trials, the expected maximum null AUC is `0.5 + σ_eff · E[max of K standard normals]`
  (the Euler–Mascheroni `E[max]` form the DSR uses). `auc_deflation = Φ((AUC_best − E[max_null]) /
  σ_eff)` — the probability the best observed AUC beats what `K` null trials would produce by luck.
- **Discontinuity, documented (this is the trap):** a Phase-6-era `auc_deflation` and a Phase-8-era
  returns-`DSR` are **not comparable** — different statistics, different nulls, different units. They
  must never be plotted on the same axis or compared across a report boundary. This is the *same*
  silent-discontinuity failure already flagged for the 3-class scoring (binary sign-AUC vs macro
  OVR-AUC): a name that stays the same while the thing underneath changes. The distinct name is the
  guard; this paragraph is the record so no one "unifies" them later.

### 4. Where the trial count comes from — the number that drives both

Both PBO (the `N` axis) and `auc_deflation` (the `K`) are only as honest as the trial count, so it is
defined precisely and **persisted**, not left to memory:

- **A trial is one distinct configuration evaluated against a dataset's validation.** Trial identity
  is the **content hash** of everything that can change the OOS score: `{model class,
  hyperparameters *including any seed that affects the fit*, feature_spec_version, label_spec_version,
  dataset_id}`. Distinct hash → distinct trial.
- **Counting rule.** A **new configuration increments**; a hyperparameter draw is a trial (that is
  precisely what deflation charges for); **a re-run of an identical hash is idempotent and does
  *not* increment** (I6: same inputs + git_sha reproduce the same result — a reproduction is not a
  new bet). A seed change that alters the fit *is* a new configuration (fishing across seeds is
  fishing). This makes the count robust to both under-counting (forgetting discarded trials) and
  over-counting (re-runs inflating it).
- **Persistence.** Trials accumulate in an **append-only registry keyed by `dataset_id`**, the same
  pattern as the lockbox: the count is `COUNT(DISTINCT trial_hash)`, so it cannot be quietly reset
  by forgetting what was tried. The `Study` is the only writer (it records a trial on every `run`),
  keeping trial accumulation a property of the choke point, not a caller convention.
- **Consequence for `Study`'s interface:** `Study.run` must **retain the per-path score vector** (not
  only the aggregated `StudyResult`) and register the trial. This is the interface change this ADR
  commits; the PBO matrix and `auc_deflation`'s `K` both read from that registry.

## Consequences

- **Built now (Module 5 step 6):** `qrp.validation.overfitting` (or `stats`) behind the same
  import-linter metric boundary as the AUC primitives — `pbo(...)` and `auc_deflation(...)`; the
  `Study` trial registry (append-only, per `dataset_id`) and the per-path score retention.
- **Reserved (Phase 5/6):** the returns-series DSR, built on the real backtester's costed P&L.
- **CI contract:** PBO on a *known-overfit* synthetic set (many noise trials, best-IS picked) must
  report **high PBO**; on a single genuine-edge trial replicated, PBO stays low / undefined — the
  same "prove it catches the bad case" discipline as the leak canary. `auc_deflation` must collapse
  a lone spurious best-of-`K` noise trial toward chance.
- **Reversibility:** naming `auc_deflation` distinctly is the cheap, load-bearing decision; if the
  effective-n null is later refined, the name and interface are unaffected.
- **Interfaces committed by this ADR (later change needs a new ADR, §3):** the `Study` trial-registry
  schema and the per-path retention on `Study.run`; the `pbo`/`auc_deflation` signatures; the
  `config/validation.yaml` PBO block.

## Open questions

- **PBO block partition.** Whether the `S` CSCV blocks are the CPCV test groups directly or an
  independent even partition, and how `S` relates to `N_groups`. Leaning independent-and-configured,
  decided at implementation with a small experiment (does PBO on a known-overfit set read high across
  reasonable `S`?).
- **Uniqueness weights into the AUC null.** Whether `σ_eff` uses `Σ w_i` directly or an
  overlap-adjusted Mann–Whitney variance; to be validated against a null simulation (shuffled labels
  should give `auc_deflation` ≈ uniform), same method as the resolution-limit table.
- **Trial registry vs MLflow.** Whether the append-only trial registry is its own table or rides on
  the MLflow run registry (which also records configs). Leaning on a dedicated table for the same
  reason the lockbox has one: the *count* is a contract, and it should not depend on MLflow's schema.
