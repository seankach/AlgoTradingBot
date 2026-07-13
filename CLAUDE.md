# CLAUDE.md — TSLA Quantitative Research Platform

This file is the standing charter for this repository. It applies to **every** session.
Read it in full before writing any code. If a task prompt contradicts this file, stop and ask.

---

## 1. What this project is

An institutional-quality **quantitative research platform**, initially trading a single
instrument (TSLA) on 1-minute bars sourced from Interactive Brokers.

It is **not**:
- a trading bot
- a high-frequency system
- a backtest-maximisation exercise

The primary deliverable is a research pipeline in which strategies can be developed,
validated, and rejected **honestly**. Production trading is a later phase that must remain
architecturally reachable at all times, but is not the current goal.

**Research quality beats backtest performance. Always.** A strategy that shows a Sharpe of
0.6 under a validation framework we trust is worth more than one showing 3.0 under a
framework we don't.

---

## 2. Non-negotiable invariants

These are correctness properties. Violating any of them silently invalidates every result
the platform will ever produce. Treat a violation as a P0 bug.

| # | Invariant |
|---|---|
| I1 | **No look-ahead.** A feature computed for bar *t* may only use information fully observable at the close of bar *t*. See §5 for the timestamp trap. |
| I2 | **Raw data is immutable.** Ingested snapshots are append-only and content-addressed. Nothing is ever overwritten in place. |
| I3 | **The label is the exit policy.** The backtest's exit rule and the label's barrier rule are the same object, derived from the same config. They cannot drift apart. |
| I4 | **Costs are frozen.** The cost model is set in versioned config and is never tuned, fitted, or adjusted to make a result look better. |
| I5 | **The test set is a lockbox.** See §7. |
| I6 | **Everything is reproducible.** Given a `dataset_id` and a `git` SHA, any result can be regenerated bit-for-bit. |
| I7 | **No CSV as a source of truth.** CSV is for debugging exports only. |

---

## 3. Working rules for Claude Code

- **One module at a time.** Do not scaffold the whole project. Do not create empty packages
  "for later". A module is done when it is implemented, typed, tested, documented, and
  integrated — then, and only then, move on.
- **Analyse before you build.** For each module: state the requirements as you understand
  them, propose the design, name the trade-offs, list the failure modes and edge cases.
  Then implement.
- **ADR gate.** Any decision that (a) changes a public interface, (b) changes a storage
  schema, (c) adds or removes a dependency, or (d) affects any invariant in §2 requires an
  ADR at `docs/adr/NNNN-short-title.md` (context / options considered / decision /
  consequences). **Write the ADR, then stop and wait for approval.** Do not proceed on
  assumption.
- **When you don't know, say so.** If a fact about IBKR behaviour, a library API, or a
  market microstructure detail is uncertain, write it down as an open question rather than
  guessing. Guesses in this domain produce results that look correct and are not.
- **No hidden state.** No globals, no module-level mutable singletons, no import-time side
  effects.

---

## 4. Architecture

```
Raw snapshots (immutable, Parquet)
  ↓ validation
Validated bars (Parquet, session-tagged)
  ↓ transforms
Feature store (Parquet, point-in-time correct)
  ↓ labelling
Research dataset (manifest-addressed)
  ↓ validation framework  ← nothing bypasses this
Models → Predictions → Signals → Risk → Execution → Analytics
```

**Stack (decided; see ADRs to overrule):**

- Python 3.12+, `uv` for dependency locking (reproducibility requires a lockfile)
- Polars + PyArrow for data; **no pandas** in the core pipeline
- **Parquet** — all market data, all features. Partitioned by `symbol / date`.
- **DuckDB** — analytical query layer over the Parquet lake. Not a storage engine.
- **PostgreSQL** — MLflow backend store + experiment/run/trade metadata registry.
  It is **not** a feature store. Runs via Docker Compose.
- **MLflow** — experiment tracking and artifact store.
- **No DVC.** Dataset versioning is handled by content-addressed Parquet snapshots plus a
  dataset manifest: `dataset_id = hash{raw_snapshot_ids, feature_spec_version,
  label_spec_version, git_sha}`. A second versioning system is a second source of truth to
  get out of sync. (ADR-0003.)
- `exchange_calendars` for session boundaries — a first-class dependency, not a helper.
- Pydantic v2 for all config and all domain models. Config is validated at load, not at use.
- `structlog` → structured JSON logs.
- **Ruff only.** Ruff lints and formats. **Black is not installed.**
- mypy in `--strict` mode. Not negotiable, not "later".

**Broker isolation:** the research platform depends on a `MarketDataSource` protocol and a
`Broker` protocol. It must never import `ib_async` outside `infrastructure/brokers/ibkr/`.
A second broker must be addable without touching anything above that boundary.

---

## 5. Data contract — IBKR (read this twice)

These are the details that silently corrupt research if ignored.

- **Bar timestamps mark the bar's START.** The bar stamped `09:30` covers `09:30:00–09:30:59`
  and is not complete until `09:31`. Therefore: **features "as of *t*" may only use bars
  stamped ≤ *t* − 1 minute.** This is the single most likely source of a one-bar look-ahead,
  and it is invisible in every backtest metric. Encode it in the type system if you can;
  test for it regardless.
- **Timezones.** Returned bar timezones depend on the TWS login setting. Pin the timezone
  explicitly on every request. Store everything in UTC. Derive session tags from the
  exchange calendar, never from naive local time. A DST bug here surfaces months later.
- **`whatToShow=TRADES` is split-adjusted, not dividend-adjusted.** TSLA pays no dividend,
  so `TRADES` is correct — but split adjustment means **IBKR retroactively rewrites history
  after every split** (TSLA: 5:1 Aug 2020, 3:1 Aug 2022). This collides with invariant I2.
  Resolution: each pull is a new immutable snapshot with a fetch timestamp; re-fetches never
  overwrite; the validator **diffs overlapping ranges across snapshots and raises** on
  mismatch rather than silently accepting the rewrite.
- **Available depth is unknown and must be discovered, not assumed.** TSLA IPO'd 29 June 2010,
  so ≤16 years exist at all, and IBKR's 1-minute depth is far shorter than its daily-bar
  depth. The ingestion module **probes backward** until IBKR returns empty, records the
  discovered earliest timestamp, and persists it. Never hardcode a start date.
- **Pacing.** Max 60 historical requests per 10 minutes. `BID_ASK` requests **count double**.
  Chunk requests to a few thousand bars each. The ingester must respect this by construction,
  with backoff — not by hoping.
- **IBKR volume ≠ consolidated tape volume.** Odd lots, average-price trades, and derivative
  trades are excluded. Volume features are features of *IBKR's view* of volume. That's
  acceptable; mixing vendors mid-dataset is not.
- **Missing bars are real.** Outside RTH, many minutes have no trades. **Never forward-fill
  prices.** Maintain a complete session-time index with an `is_traded` flag. Volatility and
  barrier logic must handle absent bars explicitly.

**Session tagging.** Every bar carries a session label: `PRE | RTH | POST | OVERNIGHT`.
Ingest with `useRTH=0` so nothing is discarded. **Default research scope = PRE + RTH + POST.
OVERNIGHT is ingested but excluded** until its data quality and spread behaviour are
independently verified. Tradable sessions are a config flag, never a hardcode.

---

## 6. Label & strategy contract

**Default (Phase 1):** triple-barrier, and **the barriers are the strategy** (invariant I3).

- Barriers: ±`k`·σ with `k = 2`, where σ is a **causal, session-conditional** volatility
  estimate (EWMA of 1-min returns over a trailing window; open-hour vol and midday vol are
  not the same animal and must not share an estimator).
- Vertical barrier: `H = 30` bars (wall-clock minutes; barriers are checked against bars that
  actually exist, per §5).
- Outcome: first barrier touched → `+1` / `−1` / `0` (timeout).
- Direction: **long and short.**
- **Execution semantics:** signal at close of bar *t* → **fill at open of bar *t*+1**.
  Exit at the first of {take-profit, stop-loss, H bars}. The backtest does exactly this and
  nothing else.
- `k` and `H` are config values. If a longer holding period is wanted, **raise `H`** — do not
  invent a different exit rule, or the model is trained on a game it doesn't play.

`LabelGenerator` is a protocol. Implementations: `FixedHorizonDirection`,
`FixedHorizonMagnitude`, `TripleBarrier` (default), and later `MetaLabeling` (Phase 2).
Purge and embargo lengths are **derived from the active label spec's horizon**, never
configured independently — they cannot be allowed to disagree.

---

## 7. Validation framework (build before models, not after)

No model, no feature, and no hyperparameter is selected outside this framework.

- **Purge = H bars** (from the active label spec).
- **Embargo = max(H, 1% of sample count)**.
- **Sample-uniqueness weighting is ON by default.** With H=30, consecutive labels overlap
  heavily; row count wildly overstates effective sample size. Weight accordingly.
- **CPCV** (combinatorial purged cross-validation) is the primary CV scheme; **walk-forward**
  is the reporting frame.
- **Multiple-testing control is part of evaluation, not an afterthought:** deflated Sharpe
  ratio and probability of backtest overfitting (PBO) are computed for every reported result.
- **Leakage tests are code, not vigilance.** At minimum, automated tests for: features
  referencing bars ≥ *t*; labels leaking into features; purge/embargo boundary correctness;
  and a shuffle test (destroy the time ordering; performance must collapse to chance).
- **Lockbox.** The final out-of-sample period may be touched **at most twice** for the entire
  project. Every touch is logged to MLflow with an incrementing counter and a justification.
  When the counter hits its limit, the lockbox is burned and a new one must be carved from
  future data. Code must enforce this, not the developer's memory.

Every reported result must state, separately: training period, validation period, lockbox
test period, walk-forward results, and (later) paper/live results.

---

## 8. Cost model (frozen — invariant I4)

- **Spread is measured, not assumed.** Ingest `BID_ASK` 1-min bars alongside `TRADES` and
  compute the prevailing spread per bar. (Fallback where BID_ASK is unavailable:
  Corwin–Schultz / Abdi–Ranaldo high-low estimator — flagged as estimated in the data.)
- **Fill model:** fill at bar *t*+1 open, cross half the prevailing quoted spread, plus a
  fixed impact term in basis points.
- **Commissions:** IBKR tiered schedule, per-share with per-order minimum, plus
  exchange/regulatory fees. **Read the actual rate from config — do not hardcode a guess.**
  The developer supplies the number from their account's commission schedule.
- **Every reported result is also reported at 2× and 3× costs.** A strategy that does not
  survive 2× costs is not a strategy and must not be promoted.
- Costs live in `config/costs.yaml`, are versioned, and appear in the `dataset_id` hash.
  Any change to them invalidates prior results and must be flagged as such.

---

## 9. Quality gates (a module is not done until all pass)

- `ruff check` and `ruff format --check` clean
- `mypy --strict` clean
- Unit tests for logic; integration tests against **recorded IBKR fixtures** (never a live
  gateway in CI)
- Public interfaces have docstrings covering: purpose, contract, failure modes, example
- Module README documents: purpose, architecture, dependencies, public interface, usage,
  testing strategy, extension points
- Structured JSON logging at boundaries; no `print`
- Config validated at load via Pydantic; no silent defaults for anything that affects results

---

## 10. Phase plan

1. **Foundation + ingestion** ← current
2. Validation & dataset construction (feature store, labels, CPCV, leakage tests, lockbox)
3. Models (GBMs first — with the effective sample size implied by H=30, deep learning is
   regularisation-constrained; PyTorch comes after the framework has proven it can reject
   a bad model)
4. Meta-labeling, ensembles, evaluation & attribution
5. Portfolio construction, risk, position sizing
6. Paper trading → live

Later phases must have clean interfaces reserved from the start, but **must not be
implemented early**. An unused abstraction is a liability.
