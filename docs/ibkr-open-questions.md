# IBKR behaviour — open questions

Places where the ingestion code makes an assumption about IBKR/`ib_async` behaviour that
can only be confirmed against a **live gateway** (never done in CI, §9). Each is referenced
in code as `OQ-n`. Resolve by running the ingester against a real gateway and recording the
outcome here; update fixtures to match.

| # | Question | Current assumption | How to confirm |
|---|----------|--------------------|----------------|
| OQ-1 | Does `reqHeadTimeStamp` return the earliest **1-minute** timestamp, or a deeper (daily/tick) head? | Treated as a *coarse lower bound*; the true 1-min floor is pinned by a forward-find + backward-pin walk. | Compare `reqHeadTimeStamp(TRADES)` against the earliest bar the probe actually pins for TSLA. |
| OQ-2 | With `formatDate=2`, are intraday bar timestamps returned as tz-aware UTC? | Assumed UTC; a naive datetime is localised with the pinned `request_timezone` as a fallback. | Inspect `bar.date.tzinfo` on real responses. |
| OQ-3 | Max bars per request for `1 min` / how large a `durationStr` is safe before IBKR rejects it? | Conservative `"1 D"` per request. | Increase `durationStr` until IBKR errors; record the ceiling. |
| OQ-4 | How does a pacing violation (error 162) surface through `ib_async` — exception, empty result, or an `error` event? | Broad `except` + bounded exponential backoff around each request; the limiter aims to prevent it entirely. | Deliberately breach pacing on a test account and observe. |
| OQ-5 | For `whatToShow=BID_ASK`, exact field mapping (open=avg bid? close=avg ask? high=max ask? low=min bid?) and which fields are `-1`. | Stored raw; spread derived downstream in the cost model per the documented convention. | Cross-check a BID_ASK bar against the live quote stream. |
| OQ-6 | Does BID_ASK 1-min depth reach as far back as TRADES depth for TSLA? | Probed independently per `whatToShow`; not assumed equal. | Run the depth probe for both and compare. |

## Findings — live gateway, 2026-07-13 (server v178)

- **OQ-1 (resolved):** `reqHeadTimeStamp` returns **2010-06-29** (TSLA IPO) for both TRADES
  and BID_ASK, and the hybrid probe pinned the true 1-min TRADES floor at **2010-07-28**.
  1-minute depth is effectively the *full* history — contrary to the charter's guess of
  "far less than 16 years." (Re-confirm the deep floor with the extended `diagnose_ibkr.py`.)
- **OQ-2 (resolved):** with `formatDate=2`, bar timestamps come back **tz-aware UTC**
  (e.g. `first=2026-07-13 08:00:00+00:00`); the naive-localise fallback is not exercised.
- **OQ-3 (resolved):** single-request 1-min ceiling — `"10 D"` ≈ 9,019 bars OK, `"30 D"`
  **times out**. Adapter now uses `"10 D"` (was `"1 D"`) with a 120 s request timeout,
  ~10× fewer requests.
- **OQ-4 (resolved):** a "no data" condition surfaces as **error 162 "HMDS query returned
  no data"** logged by `ib_async` while `reqHistoricalData` returns an **empty list** — not
  a raised exception. The adapter treats empty as "no data" and continues; the retry/backoff
  path is for genuine transient failures.
- **OQ-5 / OQ-6 (open):** BID_ASK returned 0 rows in the first run only because the
  interrupted backfill never reached the BID_ASK phase; `reqHeadTimeStamp[BID_ASK]` = 2010,
  so data should exist. Confirm field mapping and depth once a completed run (or the extended
  diagnostic) produces BID_ASK bars.
