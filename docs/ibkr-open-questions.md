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
