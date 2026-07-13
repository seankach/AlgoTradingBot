# ADR-0004: Bar timestamp semantics and the point-in-time correctness rule

- **Status:** Proposed
- **Date:** 2026-07-13
- **Deciders:** (awaiting approval)
- **Charter refs:** §5 (data contract), §2 invariant I1 (no look-ahead), §7 (leakage tests)

## Context

IBKR stamps a bar with its **start** time: the bar labeled `09:30` covers `09:30:00–09:30:59`
and is not complete until `09:31:00`. A feature computed "as of *t*" that reads the bar
stamped *t* is therefore reading the future — a one-bar look-ahead that is invisible in every
backtest metric (I1, §5). This is the single most likely source of silent leakage in the
platform, so its semantics must be fixed once, centrally, and enforced by tests — not left to
each author to remember.

Compounding it: returned bar timezones depend on the TWS login setting, and naive local time
plus DST produces session-tagging bugs that surface months later (§5).

## Options considered

- **Treat the stamp as the bar's end (relabel on ingest).** Pros: "as of *t* uses bar *t*"
  becomes naively safe. Cons: fights the vendor's own convention, makes cross-checking
  against IBKR confusing, and moves the trap rather than removing it. Rejected.
- **Store naive local time; derive sessions from wall-clock.** Cons: DST correctness is
  impossible to guarantee; violates §5 directly. Rejected.
- **Keep IBKR's start-stamp convention, store UTC, and encode the point-in-time rule in
  types + tests (chosen).** Preserve the vendor semantics, make them explicit, and make
  violation a test failure.

## Decision

1. **Timestamp meaning is fixed:** every stored bar's timestamp is the **bar start**, in UTC.
   The convention is documented at the storage boundary and carried in column naming
   (`ts_utc` = bar start).
2. **Timezone is pinned on every request** (from `IBKRConnectionConfig.request_timezone`) and
   converted to UTC on ingest. Session tags (`PRE|RTH|POST|OVERNIGHT`) are derived from
   `exchange_calendars`, never from naive local time.
3. **Point-in-time rule (the I1 guardrail):** a feature or decision "as of time *t*" may only
   use bars with `ts_utc ≤ t − 1 minute` (i.e. bars whose *close* has occurred by *t*).
   Execution semantics follow the charter: signal at close of bar *t* → fill at **open of bar
   *t*+1** (§6). This rule is expressed in the feature/labeling APIs (Phase 2) so that the
   "safe as-of" boundary is a parameter of the interface, not a convention, and is covered by
   automated leakage tests (§7): features referencing bars ≥ *t* must fail, and a shuffle test
   must collapse performance to chance.
4. **Complete session-time index, never forward-filled.** Absent minutes (common outside RTH)
   are represented with an `is_traded=false` row; prices are never forward-filled (§5).

## Consequences

- **Protects I1** at the type/test level rather than relying on developer vigilance, which is
  the charter's explicit requirement ("Leakage tests are code, not vigilance," §7).
- Establishes the exact contract the feature store and label generator (Phase 2) must honor;
  those modules inherit the `ts_utc ≤ t − 1min` boundary as an API parameter.
- DST bugs are structurally excluded by storing UTC and tagging from the exchange calendar.
- Cost: every consumer of bar data must respect the "start stamp, close at +1min" rule; it is
  therefore stated at the boundary and re-asserted in tests wherever features/labels are
  produced.
- Commits Stage B to: UTC storage, calendar-derived session tags, an `is_traded` flag, and no
  forward-fill — all of which the validation layer will implement and test.
