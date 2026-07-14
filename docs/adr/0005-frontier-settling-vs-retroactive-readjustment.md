# ADR-0005: Frontier settling vs. retroactive re-adjustment in conflict detection

- **Status:** Accepted
- **Date:** 2026-07-14
- **Deciders:** Romesh Sharma (approved 2026-07-14; settling horizon set to 2 days)
- **Charter refs:** §5 (data contract, incomplete last bar), §2 invariant I2; refines ADR-0003

## Context

ADR-0003 / §5 require the validator to diff overlapping bars across immutable snapshots and
**raise** on mismatch, so IBKR's retroactive split re-adjustment cannot pass silently. The
first full 16-year TSLA backfill surfaced a case that rule did not anticipate: the resumable
supervisor re-fetches recent bars on every pass, and **recent bars legitimately change
between fetches** while they are still settling —

- the most recent bar is incomplete at fetch time (§5: timestamps mark the bar *start*), and
- thin extended-hours/overnight bars receive late-reported prints and quote updates for a
  while after the minute closes.

Result: reporting hard-crashed with `SnapshotConflictError` on 8 timestamps, all in the last
~day (overnight/pre-market minutes). These are **not** re-adjustments; the check fired in the
wrong regime. A genuine re-adjustment, by contrast, rewrites *old* history (bars from before
a split, re-fetched long after they closed).

## Options considered

- **Keep the global raise (status quo).** Any overlap disagreement aborts. Pro: simplest,
  maximally strict. Con: the live frontier *always* produces disagreements, so any dataset
  that has been incrementally updated becomes unreadable. Rejected — it breaks normal use.
- **Always resolve overlaps by latest fetch; never raise.** Pro: never crashes. Con: throws
  away the split-re-adjustment alarm the charter explicitly requires (§5). Rejected.
- **Prefer-latest, but restrict the raise to settled history (chosen).** Distinguish the two
  regimes by age: bars older than a *settling horizon* relative to the most recent fetch are
  final, so a disagreement there is a real re-adjustment → raise. Bars within the horizon may
  still be settling → resolve by keeping the value from the latest fetch, no raise.

## Decision

- Immutability is unchanged: every snapshot is still written once and retained (I2). Only the
  **read/assemble** step changes.
- `find_conflicts` / `assert_no_conflicts` take a `settled_before` cutoff; only bars with
  `ts_utc < settled_before` are compared for re-adjustment.
- `assemble_validated` sets `settled_before = max(fetch_ts_utc) - SETTLING_HORIZON` (**2 days**),
  asserts no conflicts among settled bars, then resolves any remaining overlaps by keeping the
  row with the latest `fetch_ts_utc`.
- Split re-adjustments (old bars, re-fetched years later) are always older than the horizon,
  so they still raise. Frontier settling (bars re-fetched within days) is resolved to the most
  recent, most-complete value.

## Consequences

- Reporting/validation is robust to incremental re-fetching while retaining the split-detection
  teeth for genuine history rewrites (§5, I2 preserved).
- Introduces one tunable, `SETTLING_HORIZON` (2 days). Too small risks flagging slow-settling
  thin-session bars; too large risks masking a re-adjustment that happens to touch very recent
  data (rare — splits rewrite deep history). 2 days gives safe margin over the observed ~1-day
  settling while keeping re-adjustment detection strict.
- Follow-up (not required by this ADR): ingestion could additionally drop the incomplete last
  bar at fetch time (`ts_utc > now - bar_size`) to reduce frontier churn at the source.
- Reproducibility (I6) is unaffected: given the same snapshots, assembly is deterministic
  (latest fetch is a total order via `fetch_ts_utc`).
