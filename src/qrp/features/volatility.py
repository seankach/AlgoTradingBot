"""Barrier/feature volatility — time-of-day-bucketed causal EWMA (ADR-0007; §6).

For a bar at intraday bucket ``b`` on trading day ``d``, sigma is the EWMA over **past days**
(``d' < d``) of that bucket's realized 1-min variance. Open-hour and midday fall in different
buckets and therefore have separate estimators (§6), and the estimate uses only prior days, so
it is causal (no look-ahead). Shared by the triple-barrier labels and the ``ewma_vol`` feature
so the signal and the barrier that defines the strategy cannot drift (I3).
"""

from __future__ import annotations

import polars as pl

_SD = "_sd"
_BUCKET = "_bucket"


def barrier_volatility(
    bars: pl.DataFrame,
    *,
    bucket_minutes: int,
    ewma_span_days: int,
    timezone: str,
) -> pl.DataFrame:
    """Return ``ts_utc`` and ``sigma`` (per-bar barrier volatility).

    Args:
        bars: Validated bars with ``ts_utc`` and ``close`` (sorted or unsorted).
        bucket_minutes: Intraday bucket width (e.g. 30).
        ewma_span_days: EWMA span over past days of same-bucket realized variance.
        timezone: Exchange timezone for the trading-date and time-of-day bucketing.

    Returns:
        One row per input ``ts_utc``; ``sigma`` is null until a bucket has at least one prior
        day of history.
    """
    et = pl.col("ts_utc").dt.convert_time_zone(timezone)
    minute_of_day = et.dt.hour().cast(pl.Int32) * 60 + et.dt.minute().cast(pl.Int32)
    tagged = bars.sort("ts_utc").with_columns(
        et.dt.date().alias(_SD),
        (minute_of_day // bucket_minutes).alias(_BUCKET),
    )

    log_close = pl.when(pl.col("close") > 0).then(pl.col("close").log()).otherwise(None)
    ret1 = (log_close - log_close.shift(1)).over(_SD)
    tagged = tagged.with_columns(_r2=ret1**2)

    # Realized variance per (trading day, bucket).
    daily = tagged.group_by(_SD, _BUCKET).agg(pl.col("_r2").mean().alias("_rv"))
    # EWMA over PAST days per bucket (shift(1) => strictly prior days -> causal).
    sigma2 = pl.col("_rv").ewm_mean(span=ewma_span_days, ignore_nulls=True).shift(1).over(_BUCKET)
    daily = daily.sort(_BUCKET, _SD).with_columns(sigma2.sqrt().alias("sigma"))

    return (
        tagged.join(daily.select(_SD, _BUCKET, "sigma"), on=[_SD, _BUCKET], how="left")
        .select("ts_utc", "sigma")
        .sort("ts_utc")
    )
