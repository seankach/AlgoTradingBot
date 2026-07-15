# ADR-0009: Validation framework — CPCV, the Study choke point, lockbox, and the leakage gate

- **Status:** Accepted
- **Date:** 2026-07-14
- **Deciders:** Romesh Sharma (approved 2026-07-14 with four tightenings, folded in below)
- **Charter refs:** §7 (validation framework), §2 invariants I5 (lockbox), I6, I1/I3; §8
  (costs at 1x/2x/3x); §9 (quality gates); builds on ADR-0007 (LabelSpec lifespans), ADR-0003
  (`dataset_id`), ADR-0002 (CI-enforced boundaries)

## Context

Module 5 is the framework §7 says must exist **before** any model. Its purpose is not to score
models well — it is to make an over-optimistic result impossible to obtain by accident. The
charter's whole thesis is that the dangerous failures never show up as a failing metric, only
as a backtest better than reality. So three things must be **structural, not conventions**:

1. purge and embargo cannot disagree with the labels;
2. a performance number cannot be computed outside the framework;
3. the lockbox cannot be touched more than twice, and the framework must *prove* it catches a
   known leak before it is trusted to clear an unknown one.

The design below makes each of these a mechanism (a CI contract, an append-only registry, a
choke-point object), never a matter of the developer's memory.

## Options considered

- **CV scheme.** k-fold (rejected — ignores label overlap, leaks across folds); walk-forward
  only (kept, but as the *reporting* frame, not the primary — it yields a single path and few
  test points); **CPCV** (chosen primary — combinatorial purged CV gives many backtest paths
  and supports PBO). Walk-forward + CPCV together.
- **Metric access.** Public `compute_sharpe(...)` helpers (rejected — trivially misused to peek
  outside the framework); **`Study` as the sole choke point** with the metric primitives behind
  an import-linter boundary (chosen).
- **Lockbox persistence.** A counter file on disk (rejected — editable, not tamper-evident);
  **an append-only table in the Postgres registry** whose row count *is* the counter (chosen).
- **purge/embargo derivation.** A fixed `H`-bar constant (rejected — drifts from the labels);
  **derived from the actual LabelSpec lifespans** (chosen).
- **Leakage gate.** Manual review (rejected — the exact vigilance §7 forbids); **a code suite of
  the four §7 tests plus a planted-leak canary, CI-blocking** (chosen).

## Decision

### 1. `PurgedCPCV` splitter and `Study`, designed as one unit

- **`PurgedCPCV`** partitions the time-ordered samples into `N` groups; for each size-`k`
  combination of test groups (`C(N, k)`), the remaining groups form the train set. This yields
  `C(N, k)` splits and many distinct backtest paths (López de Prado). It is constructed from the
  **label frame** (`decision_ts, entry_ts, exit_ts`) so it can purge/embargo from real lifespans
  (§2 below), and it emits train/test integer index arrays only. **`N` and `k` are config**
  (`config/validation.yaml`, defaults `N = 6`, `k = 2` → 15 paths), with a comment at the config
  site making the coupling explicit: more paths means more trials, trials feed the deflated
  Sharpe, so raising `N` deflates your own Sharpe — the trade-off must be visible where someone
  would edit it.
- **`Study`** is the orchestrator and the *only* object that turns a `(model, dataset_id)` into a
  metric. It: loads the dataset + labels for the `dataset_id`; builds `PurgedCPCV`; for each split
  fits the model on the purged/embargoed/uniqueness-weighted train fold and predicts the test
  fold; aggregates out-of-fold results across all paths; computes the metrics with
  multiple-testing control; and logs everything to MLflow keyed by `dataset_id` + git sha. The
  same `Study` produces the walk-forward result as the reporting frame. Splitter and Study share
  one purge/embargo implementation, so they cannot disagree.

### 2. purge/embargo derived from the LabelSpec lifespan (never configured)

- Each label occupies `[entry_ts, exit_ts]`. **Purge:** drop any *training* sample whose lifespan
  overlaps the test fold's time span — using the real lifespans, so a label that exited early via
  a barrier touch purges less than one that ran to the H-bar vertical. **Embargo:** additionally
  drop training samples within the embargo horizon *after* the test span, with
  `embargo = max(H, ceil(0.01 × n_samples))` from the active LabelSpec (§7). Both are computed by
  the splitter from the label frame and the LabelSpec's `H`; there is **no independent
  purge/embargo config**, so they cannot drift from the labels.
- **Sample-uniqueness weighting** is on by default: each label's weight is its average uniqueness
  over its lifespan (`1 / concurrency`, from overlapping `[entry, exit]` intervals). Used for both
  training weights and the scored metric, so the wild overstatement of effective sample size under
  H-overlap is corrected everywhere (§7).

### 3. `Study` is the only path to a metric (enforced, not asked)

- The metric primitives — sample-weighted return/Sharpe, the **deflated Sharpe ratio**, and the
  **probability of backtest overfitting (PBO)** — live in a private module imported **only** by
  `qrp.validation.study`. An **import-linter contract** (exactly like the `ib_async` boundary,
  ADR-0002) forbids importing them anywhere else, and CI enforces it (§9). There is no
  `compute_sharpe(dataset)` in the public surface and the dataset exposes no `.score()`.
- The only way to a number is `Study.run(...)`, which *always* applies purge/embargo/uniqueness
  and *always* reports the deflated Sharpe and PBO next to the raw figure, at **1x / 2x / 3x
  costs** (§8). "Sneaking a peek" therefore becomes a CI failure, not a lapse in discipline.

### 4. Lockbox: an append-only counter in the Postgres registry, enforced by code (I5)

- The lockbox is the final out-of-sample period — a time range recorded per `dataset_id`. It can
  be touched *only* via `Study.evaluate_lockbox(justification=...)`, which calls `Lockbox.touch()`.
- `touch()` appends an **immutable row** `(touched_at, dataset_id, git_sha, justification)` to a
  `lockbox_touches` table in the Postgres registry and logs it to MLflow with the incrementing
  counter. The counter is the row count; if it already equals the limit (**2**), `touch()`
  **raises** and no evaluation runs. Append-only + registry-backed makes the count tamper-evident
  and durable across runs; the developer's memory is never the guard.
- Burning the lockbox is itself a recorded event that requires a new range carved from future
  data. All ordinary evaluation runs on train/validation via `Study.run`; the lockbox range is
  refused by every path except `evaluate_lockbox`.

### 5. The leakage gate: four §7 tests + a planted-leak canary, CI-blocking

Module 5 is **not done** until all of these pass in CI (leakage tests are code, §7):

- **(a) No feature reads ≥ t** — extends the feature-level `close_t` point-in-time test to the
  assembled dataset (no column carries information from bar `≥ decision`).
- **(b) No label leaks into features** — a feature must not be recoverable from the label/outcome;
  a feature engineered to correlate with the forward label must fail the check.
- **(c) Purge/embargo boundary correctness** — no train sample's lifespan overlaps its test fold,
  the embargo region contains no train samples, and the removed counts match the spec.
- **(d) Two shuffle tests, each naming the failure mode it targets** — "collapses to chance" is
  underspecified; there are two distinct shuffles proving different things:
  - **Label shuffle** (break the X↔y correspondence): a model's out-of-fold AUC must return to
    ≈ 0.5, proving the model is not memorising noise. *Trap (document in the test):* with
    sample-uniqueness weighting on, a label shuffle can still read slightly above chance because
    the concurrency structure survives the shuffle — that is expected, **not** a framework bug, so
    the criterion is "≈ 0.5 within tolerance", not "exactly 0.5".
  - **Time-order shuffle** (break the sequence): the leak-sensitive path must show **no
    improvement**, proving the CV machinery is not leaking through ordering (purge/embargo, fold
    construction). This targets ordering leaks, which the label shuffle cannot see.
- **(e) Planted-leak canary** — inject a deliberately leaking feature (a copy of the label) and
  assert the framework **flags** it: the raw in-sample metric spikes while the machinery still
  runs, proving the suite can catch a *known* leak. A framework that cannot detect a planted leak
  cannot be trusted to clear an unplanted one — the canary is the meta-gate, and it must pass
  before the first real model is ever scored.

### Reserved / dependencies

- A `Model` protocol (weight-aware `fit`/`predict`) keeps the framework model-agnostic; concrete
  models (GBMs) are Phase 3 and not built now (§10).
- **New dependencies (ADR-gated, §3c, pre-approved):** `mlflow` (tracking client) and `psycopg`
  (Postgres registry) come online here — already the §4 stack, and `docker-compose.yml` exists.
  **`scipy` is pre-approved**: use `scipy.stats` for the deflated-Sharpe normal CDF and the
  PBO rank/logit machinery rather than hand-rolling them in numpy.

### Testing precision (two things to get exactly right)

- **Purge boundary (test 5c) asserts the exact boundary, not "some purging occurred."** Use a
  label whose `exit_ts` lands one bar *before*, *exactly on*, and one bar *after* the test span,
  and assert the correct include/exclude for each. An off-by-one here silently purges nothing on
  some folds.
- **Lockbox enforcement exercises the *third* touch.** The fixture test must assert that the third
  `touch()` **raises**, not merely that the first two append — otherwise the enforcement rots
  untested.

### Build order (corrected — the canary needs a substrate to run through)

1. **purge/embargo primitive + minimal `PurgedCPCV`** — train/test index arrays derived from the
   label lifespans.
2. **Minimal scoring path inside `Study`** — splits → one number.
3. **Plant the canary immediately** — a copy-of-the-label feature; prove this two-component
   pipeline catches it *before* building anything on top. **Stop here for review** — the planted
   leak must be seen to be caught before the full suite or any real number.
4. The full §7 leakage suite (a, b, c, both shuffles).
5. The lockbox (append-only counter + enforcement).
6. The deflated Sharpe / PBO metrics.

## Consequences

- purge/embargo can never disagree with the labels; every number has already paid for overlap,
  uniqueness, and multiple testing; and the lockbox is machine-enforced (I5, I6).
- The metric choke point and the lockbox counter are **load-bearing CI contracts**, like the
  broker boundary — if either is removed, the guarantee is gone, so both are treated as part of §9.
- The planted-leak canary means the framework earns trust by *demonstrably* catching a leak before
  it clears a model — the charter's "prove it can reject before it approves."
- Postgres/MLflow become required for *evaluation*, not just ingestion. CI must test the lockbox
  and Study logic against a **fixture/disposable registry** (no live server), so the enforcement
  logic — not a running database — is what the tests exercise.
- Commits Module 5 to: the `PurgedCPCV` interface, the `Study` API and its metric-module import
  boundary, the `lockbox_touches` schema, the `Model` protocol, and the leakage-gate suite. Any
  later change to these needs a new ADR (§3).
