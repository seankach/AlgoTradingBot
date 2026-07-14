# ADR-0008: Point-in-time, horizon, and tie-break corrections (external review)

- **Status:** Accepted
- **Date:** 2026-07-14
- **Deciders:** Romesh Sharma (directed via external code review 2026-07-14)
- **Charter refs:** §2 invariants I1, I3, I6; §5, §6, §7; amends ADR-0004, ADR-0006, ADR-0007, ADR-0003

## Context

An external review of the Phase-2 modules found three correctness issues and several smaller
ones, all of the "silently inflates the backtest" class the charter exists to prevent. This
ADR records the resulting decisions; the code is aligned to them in the same change.

## Decisions

1. **Event-based features (amends ADR-0006).** Features are computed and lagged over the
   **traded** bar series, not the padded session grid. "Previous bar" means the previous
   *traded event*, so the 1-bar point-in-time lag and all rolling windows are unambiguous.
   (Analysis note: the prior grid was contiguous *within* a session date, so `shift(1)` was a
   true 1-minute lag and did not forward-leak — the added leakage test confirms this — but the
   grid semantics were fragile and inconsistent with the bar-based horizons below, so the
   event-based form is adopted.)

2. **Horizons are in BARS of the active sampler, not wall-clock minutes (amends ADR-0007, §6).**
   The triple-barrier vertical timeout `H` counts **traded bars** after entry; feature return
   horizons and windows count bars. In RTH these equal minutes; across gaps they do not, and
   "walk over bars that actually exist" (§5) wins. Config fields are renamed to `..._bars`.

3. **Conservative intrabar tie-break (amends ADR-0007, I3).** When one bar's range spans both
   barriers, the outcome is resolved to the **stop** (`label = -1`, exit at the lower barrier),
   never silently to a timeout `0`. OHLCV cannot reveal the intrabar path, so the adverse
   assumption is the only honest one. `touched = "both"` is kept as a diagnostic column.
   *Nuance:* for the symmetric long/short label this is conservative under a long-side reading;
   a both-touch is a whipsaw that loses either way, which a directional `+1/-1/0` label cannot
   fully encode. The diagnostic lets us measure frequency and revisit (exclude, or handle per
   meta-label side) later.

4. **Smaller corrections.**
   - `realized_return` → **`gross_return`**: the raw price move from entry to exit, unsigned by
     position. The signed, cost-adjusted strategy return is computed downstream (Phase 4), so
     nothing wires a gross number into a Sharpe by accident.
   - **`dataset_id` includes `bar_spec_version`** (amends ADR-0003), so datasets on different
     samplers cannot collide on the same id.
   - **A dirty tree refuses to build a dataset** by default (`--allow-dirty` to override), since
     a `-dirty` id is unreproducible by construction (I6).
   - The label `touched` string is mapped with a vectorised Polars expression, not a per-row
     Python loop.

## Consequences

- I1 is now guarded by an executable leakage test (a `close_t` feature must never appear on the
  decision bar), as §7 requires — the test that was promised but absent.
- Feature and barrier volatility remain one shared estimator (I3): both compute over the traded
  series, so they stay identical.
- The feature/label spec versions bump; the feature, label, and dataset lakes are rebuilt.
- The full §7 leakage suite (label-into-features, purge/embargo boundaries, shuffle test) is
  built with the validation framework (Module 5); this ADR adds the point-in-time member now.
