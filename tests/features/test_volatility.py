"""Tests for the time-of-day-bucketed causal barrier volatility (ADR-0007)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from qrp.features.volatility import barrier_volatility

_TZ = "America/New_York"


def _rth_day(day: datetime, closes: list[float]) -> pl.DataFrame:
    """One day's worth of contiguous RTH 1-min bars starting 15:00 UTC (10:00 ET)."""
    n = len(closes)
    return pl.DataFrame(
        {
            "ts_utc": [day + timedelta(minutes=i) for i in range(n)],
            "close": closes,
        }
    )


def test_sigma_is_null_on_first_day_then_defined() -> None:
    # Bucket EWMA uses only PRIOR days, so day 1 has no history -> sigma null.
    day1 = datetime(2024, 1, 2, 15, 0, tzinfo=UTC)
    day2 = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
    closes = [100.0 + 0.1 * i for i in range(40)]
    bars = pl.concat([_rth_day(day1, closes), _rth_day(day2, closes)])

    vol = barrier_volatility(bars, bucket_minutes=30, ewma_span_days=20, timezone=_TZ)
    joined = bars.join(vol, on="ts_utc")
    day1_sigma = joined.filter(pl.col("ts_utc") < day2).get_column("sigma")
    day2_sigma = joined.filter(pl.col("ts_utc") >= day2).get_column("sigma")
    assert day1_sigma.null_count() == day1_sigma.len()  # no prior day
    assert day2_sigma.null_count() < day2_sigma.len()  # day 1 supplies history
    assert (day2_sigma.drop_nulls() >= 0).all()


def test_open_and_midday_buckets_have_separate_sigma() -> None:
    # Day 1: calm open bucket, volatile midday bucket. Day 2 sigma must reflect that the two
    # intraday buckets are estimated separately (open != midday, §6).
    day1 = datetime(2024, 1, 2, 15, 0, tzinfo=UTC)  # 10:00 ET -> buckets 20 (10:00) & 21 (10:30)
    day2 = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
    calm = [100.0 + 0.001 * i for i in range(30)]  # first 30 min: tiny moves
    wild = [100.0 * (1.02 if i % 2 else 0.98) for i in range(30)]  # next 30 min: big swings
    closes = calm + wild
    bars = pl.concat([_rth_day(day1, closes), _rth_day(day2, closes)])

    vol = barrier_volatility(bars, bucket_minutes=30, ewma_span_days=20, timezone=_TZ)
    joined = bars.join(vol, on="ts_utc").filter(pl.col("ts_utc") >= day2)
    open_sigma = joined.filter(pl.col("ts_utc") < day2 + timedelta(minutes=30))["sigma"][0]
    midday_sigma = joined.filter(pl.col("ts_utc") >= day2 + timedelta(minutes=30))["sigma"][0]
    assert midday_sigma > open_sigma  # the volatile bucket carries a higher estimate
