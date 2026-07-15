# ADR-0010: Multiple-testing control — PBO now, DSR deferred, and how trials are counted

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Romesh Sharma (approved 2026-07-15 with four resolutions folded in: the AUC null is a
  permutation harness not a formula; PBO block count `S=16` default + a mandatory S-sensitivity
  report; the trial registry is its own table; and an explicit trial-count threat model)
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

- **Input:** an `N`-trials × `S`-blocks matrix of the OOS metric — each entry is a trial's AUC on a
  contiguous, **purged** time block (a boundary purge between blocks, reusing the ADR-0009 lifespan
  logic, so CSCV recombination cannot leak across a block seam). CSCV forms the `C(S, S/2)`
  train/test recombinations; for each, take the IS-best trial, read its OOS rank, logit-transform
  the relative rank `ω` to `λ = ln(ω/(1−ω))`, and set **PBO = fraction of recombinations with
  `λ ≤ 0`** (IS-best is below the OOS median).
- **Block count `S` — committed default with a sensitivity requirement (was OQ1).** `S = 16` by
  default, to stay comparable to the CSCV literature; it lives in `config/validation.yaml` beside
  the CPCV `N/k` with the "this drives the statistic" comment. But the canonical `S = 16` is
  calibrated to *returns series*, not to purged AUC on overlapping intraday labels, where the
  **effective count per block is a fraction of the rows**. So the **first time PBO runs on real
  trials it must report its S-sensitivity at `S ∈ {8, 16, 24}`**: if PBO moves materially with `S`,
  it is measuring the block choice, not overfitting, and that must be surfaced in the report rather
  than allowed to silently gate. `S` is even (the symmetric split); blocks are an independent
  even time partition, not the CPCV test groups.
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
AUC against an **empirically measured null**, and **name it `auc_deflation`, never DSR**.

**The null is a permutation harness, not a formula (was OQ2 — resolved now, because it decides what
the module is).** The entire honesty of `auc_deflation` lives in the null spread `σ` of a single
trial's AUC. Deriving that analytically for overlapping labels is a research project — the overlap
*correlates the pairwise comparisons the Mann–Whitney U is built from*, so the closed-form null
variance does not apply, and a placeholder variance produces a real-looking number on a wrong
denominator: precisely the failure this framework exists to catch. So it is **not** derived
analytically. Instead:

- **Measure the null through the real CPCV machinery.** For the selected best trial, **permute the
  labels within the purged/embargoed splits** and recompute the OOF AUC through the *same*
  `PurgedCPCV` + `Study` path, `B` times. The observed spread of those permuted AUCs **is** the null.
- **This bakes in overlap, class balance, and purging by construction**, because the same splitter
  that scores the model also generates the null — there is nothing to model or mis-specify.
- **It retires the raw-n vs effective-n question entirely.** A permutation null run through the real
  splitter already carries the effective sample size; there is **no `Σ` of uniqueness weights to
  estimate or get wrong**. (This supersedes the earlier Σ-weights framing.)
- **The `K`-trial correction** is then applied on the empirical null's own order statistics — the
  best of `K` draws from the measured single-trial null — not on a Gaussian `E[max]` closed form.
  `auc_deflation` is the resulting probability that `AUC_best` exceeds what `K` null trials would
  produce; a lone spurious best-of-`K` noise trial does **not** survive it.
- **Consequence for the module:** `qrp.validation.overfitting` is a **permutation harness**, not a
  statistics formula sheet — its cost is `B` re-runs of the splitter, and that is deliberate.

**Discontinuity, documented (this is the trap):** a Phase-6-era `auc_deflation` and a Phase-8-era
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
- **Persistence — its own table, confirmed (was OQ3).** Trials accumulate in a **dedicated
  append-only table keyed by `dataset_id`**, the same pattern as the lockbox; the count is
  `COUNT(DISTINCT trial_hash)`, so it cannot be quietly reset by forgetting what was tried. It is
  **not** folded into the MLflow run registry: the count is a *contract* that deflates every result,
  and a contract cannot live in convenience-logging infrastructure whose schema is not ours to pin.
  The `Study` is the only writer (it records a trial on every `run`), keeping trial accumulation a
  property of the choke point, not a caller convention.
- **Consequence for `Study`'s interface:** `Study.run` must **retain the per-block OOS AUC vector**
  (the trial's PBO matrix row over the `S` blocks) in addition to the aggregate `StudyResult`, and
  register the trial. This is the interface change this ADR commits; the PBO matrix reads the
  per-block vectors and `auc_deflation`'s `K` reads the distinct-trial count, both from that registry.

### 5. Trial-count threat model — the limit that backstops the deflation (required)

The trial count is honest **only for search conducted through the `Study`**. It counts what it can
hash, and it cannot hash thoughts: a researcher who tries fifty feature ideas in a notebook and runs
only the winner through the `Study` registers **one** trial and receives near-zero deflation on what
was in truth a **fifty-way selection** — data-snooping through the front door, and the deflation then
gives *false comfort*, which is worse than none. This limit cannot be closed by code (there is no
hash for an idea that never reached the choke point), so it is stated and backstopped by discipline:

- **Exploratory search happens on a designated exploration fold / pre-lockbox period**, never on the
  validation or lockbox ranges. The deflation is only trustworthy for the trials that flowed through
  the `Study` against the evaluation data.
- Reported results must name the exploration surface used, so a fifty-way notebook search cannot be
  laundered into a one-trial deflation. The count is a floor on the true number of bets, not the
  truth; the discipline is what keeps the floor near the truth.

## Consequences

- **Built now (Module 5 step 6):** `qrp.validation.overfitting` — `pbo(...)` (CSCV, `S=16` default)
  and `auc_deflation(...)` (the permutation-null harness); a dedicated append-only `trials` registry
  per `dataset_id`; and per-block OOS AUC retrieval from `Study`. `S`/`B` are explicit parameters
  defaulting to the committed values; their config home is `config/validation.yaml`, created when the
  `ValidationConfig` model lands (carried from ADR-0009, along with the CPCV `N/k` and the
  metric-module import boundary — neither built yet; tracked, not claimed here).
- **Reserved (Phase 5/6):** the returns-series DSR, built on the real backtester's costed P&L.
- **CI contract:** PBO on a *known-overfit* synthetic set (many noise trials, best-IS picked) must
  report **high PBO**; on a single genuine-edge trial replicated, PBO stays low / undefined — the
  same "prove it catches the bad case" discipline as the leak canary. `auc_deflation` run on a
  permutation null must be **≈ uniform under shuffled labels** (a spurious best-of-`K` noise trial
  does not survive it), and a planted genuine edge must clear it. The **S-sensitivity `{8,16,24}`
  report** is required on the first real-trials run.
- **Reversibility:** naming `auc_deflation` distinctly is the cheap, load-bearing decision; because
  the null is a permutation harness (no analytic variance to revisit), refining it later means only
  raising the permutation count `B`, which does not touch the name or interface.
- **Interfaces committed by this ADR (later change needs a new ADR, §3):** the `trials`-registry
  schema and the per-block AUC retention on `Study.run`; the `pbo`/`auc_deflation` signatures; the
  `config/validation.yaml` PBO block (`S`, and `B` for the permutation null).

## Open questions

The three that were open in the Proposed draft are **resolved above** by the 2026-07-15 review: the
AUC null is a permutation harness (not an analytic `Σ`-weights variance), `S=16` is the committed
default with a mandatory sensitivity report, and the trial registry is its own table. What remains is
implementation calibration, not design:

- **Permutation count `B`.** Enough that the null's tail quantiles are stable for the `K`-max
  correction; set empirically (the null spread must not move between two seeds). A config value.
- **Compute cost.** `B` splitter re-runs per deflated result is deliberate but non-trivial on the
  full dataset. Note the null runs the *model* on permuted labels, so it depends on the model's
  capacity to fit noise, not only on the labels + splitter — it is therefore keyed by
  `(dataset_id, model-class + capacity)` and cached there when unchanged, never approximated by a
  formula. A higher-capacity model legitimately has a wider null; that is a feature, not a cost to
  optimise away.
