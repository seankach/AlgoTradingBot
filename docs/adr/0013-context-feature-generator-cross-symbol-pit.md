# ADR-0013: Context-feature generator seam + the cross-symbol point-in-time contract

- **Status:** Proposed
- **Date:** 2026-07-16
- **Deciders:** Romesh Sharma (pending)
- **Charter refs:** §5 (bar stamp = START; features as-of *t* may use only bars ≤ *t*−1 — I1), §7
  (leakage tests are code), §9; extends **ADR-0006** (feature store + the single mandatory lag),
  **ADR-0008** (event-based/traded series); builds on ADR-0011 (the framework owns dangerous splits)

## Context

The feature layer is **single-symbol by construction**: `FeatureGenerator.generate(bars)` sees one
instrument, and `assemble_dataset` joins one symbol on `ts_utc`. Cross-asset features
(beta-residual, relative strength) need the **target's** bars *and* one or more **context symbols'**
bars, aligned point-in-time.

That alignment is a **fresh look-ahead surface**, and the existing `close_t` arbiter **cannot catch
it** — that test only knows single-symbol lag. The specific danger:

> A naive `join(context, on="ts_utc")` pairs SPY's bar *t* with TSLA's decision bar *t*. Under §5 a
> bar stamped *t* covers `[t, t+1)` and is not complete until *t+1*, so features as-of *t* may use
> only bars ≤ *t*−1. The naive join is a **one-bar cross-symbol look-ahead** — invisible to every
> test we have.

Ingestion and validation needed **no change** for this: SPY/QQQ were added to `config/universe.yaml`
and the pipeline picked them up (`{"pending": ["SPY/TRADES", "SPY/BID_ASK", "QQQ/TRADES",
"QQQ/BID_ASK"]}`). There is no symbol-specific logic anywhere in that path. The feature layer is the
only seam that must extend.

## Options considered

- **Generators join context themselves** (rejected). It puts the PIT contract in every generator —
  N places to get wrong, tested nowhere. This is the exact trade ADR-0011 refused when it gave
  `Study` the inner fold: *a dangerous join belongs to the framework, not to the thing being tested.*
- **Two lag paths — context pre-lagged to `t−1` and exempted from the store lag** (rejected). More
  precise during target gaps, but it creates a second lag mechanism next to the tested one. Two paths
  = twice the surface for a silent off-by-one, and the lag is the single most load-bearing line in
  the feature store.
- **Store-owned alignment + the existing single lag** (chosen). See below.

## Decision

### 1. `ContextFeatureGenerator` — extends, does not replace

```python
@runtime_checkable
class ContextFeatureGenerator(Protocol):
    name: str; output_columns: tuple[str, ...]; is_deterministic: bool   # as FeatureGenerator
    def generate(self, bars: pl.DataFrame, context: Mapping[str, pl.DataFrame]) -> pl.DataFrame: ...
```

`bars` is the target's traded frame exactly as today. `context` maps symbol → that symbol's traded
frame, **already aligned by the store**. Existing single-symbol generators are untouched;
`build_features` dispatches on the protocol.

### 2. The store owns the cross-symbol alignment — generators never construct the join

For each target bar *t*, the store attaches an **as-of backward** view of each context symbol: the
most recent **traded** context bar with `ts ≤ t` (the context's own traded series, per ADR-0008 —
never a padded minute, and it respects that SPY's halts are not TSLA's).

Generators **receive** aligned context and **cannot** join it themselves. One place, tested once —
the ADR-0011 principle applied to a second dangerous join.

### 3. One lag, not two — the existing mechanism carries the cross-symbol contract

The generator computes **through bar *t*** using context as-of *t* (the same convention the target's
own bars already use), and the feature store's **single mandatory 1-bar lag** then makes the stored
row at *t* reflect **both** target and context data from ≤ *t*−1:

    generator row at t  : target bar t  + context as-of t
    store lag (shift 1) : stored row at t == generator row at (previous target traded bar)
    => stored at t uses target <= t-1 AND context <= t-1   ✓ §5 / I1

**Consequence, stated:** during a target gap (TSLA has no trade for several minutes) the context is
staler than strictly necessary — SPY's *t*−1 bar is observable but the store will carry SPY as-of the
previous *TSLA* traded bar. That is the **conservative direction** (it discards usable information;
it never adds unusable information), and it buys a single tested lag path instead of two. Accepted
deliberately.

### 4. The leakage test is the acceptance criterion — written **first**

The seam is **not done** until this passes; it is the cross-symbol analogue of the `close_t` arbiter:

- **The gate:** plant a context feature equal to `SPY_close_t`, run it through the seam, and assert
  that on **every** TSLA decision bar it carries the **previous** SPY traded close and **never** the
  concurrent one.
- **The negative control:** the naive `join(context, on="ts_utc")` must **fail** that assertion —
  proving the test bites rather than passing vacuously. A leakage test that cannot fail is decoration
  (the planted-leak canary principle, ADR-0009).

Both go in the §7 suite and are CI-blocking.

### 5. Context symbols are inputs only

SPY/QQQ are **never labelled and never traded** — no label spec, no barriers, no positions. They
exist solely as PIT inputs. The universe config carries the target/context distinction.

### 6. First context features (built only after the seam is green)

- **beta-residual** — regress target returns on context returns over a **causal trailing window**;
  keep the residual (the idiosyncratic move).
- **relative strength** — target return − index return over **matched horizons**.

Horizon-matched to the k=6/H=270 setup, causal, PIT-lagged like everything else. **No feature
experiment is run** as part of this ADR.

## Consequences

- `feature_spec_version` bumps → new `dataset_id` → prior results untouched and still valid under
  their own spec. Per **ADR-0012** the program trial count **carries forward** (K = 19); a new
  feature spec does not reset it.
- The `close_t` arbiter stays as-is and keeps guarding the single-symbol lag; the new test guards the
  cross-symbol join. Neither subsumes the other.
- **Interfaces committed (later change needs a new ADR, §3):** `ContextFeatureGenerator`; the
  store-owned as-of alignment and its `≤ t` / single-lag semantics; the cross-symbol PIT test as the
  seam's acceptance gate.

### Known-pending, flagged now so it is not a surprise later

**The in-fold calibrator** — required before any position sizing — is the **next build after a
cross-asset edge clears the 56.2% floor**, not before. It lands in the **Study inner-fold seam that
ADR-0011 already reserves** (`FitValidation`: the purged inner fold Study carves and hands to the
model, which is also what early stopping consumes). Nothing about it is built or touched here:
calibration and sizing come **after an edge exists**, and there is currently no edge at this horizon.

## Open questions

- Whether target/context is a `role` field on `SymbolSpec` in `universe.yaml` or lives in the feature
  spec (leaning `role` on `SymbolSpec` — ingestion already treats them identically, and the
  distinction is about *use*, which the feature layer reads).
- Whether a context symbol's absence for a span (halt, late listing) should null the feature or drop
  the row (leaning null + an explicit `context_stale_bars` diagnostic, so the model can learn to
  distrust it rather than the row silently vanishing).
