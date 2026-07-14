"""The initial (v1) feature generators (ADR-0006) — deliberately minimal and causal.

Each generator computes **through bar t**; the store applies the point-in-time lag. All
rolling/EWMA statistics are grouped by ``_session_date`` so they reset each trading day and
never span the overnight gap. Untraded minutes keep null features (no forward-fill, §5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import polars as pl

from qrp.features.volatility import barrier_volatility

_SESSION_DATE = "_session_date"


def _log_close() -> pl.Expr:
    """Natural log of a strictly-positive close, else null (avoids -inf/nan)."""
    return pl.when(pl.col("close") > 0).then(pl.col("close").log()).otherwise(None)


@dataclass(frozen=True)
class LaggedReturns:
    """Lagged log returns of close over the configured horizons, in bars (ADR-0008)."""

    horizons_bars: tuple[int, ...]
    name: str = "lagged_returns"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """One ``ret_{h}b`` column per configured horizon (bars)."""
        return tuple(f"ret_{h}b" for h in self.horizons_bars)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute ``ln(close_t / close_{t-h bars})`` per horizon, within the session date."""
        log_close = _log_close()
        exprs = [
            (log_close - log_close.shift(h)).over(_SESSION_DATE).alias(f"ret_{h}b")
            for h in self.horizons_bars
        ]
        return bars.select("ts_utc", *exprs)


@dataclass(frozen=True)
class BarrierVolatility:
    """Time-of-day-bucketed causal EWMA volatility (ADR-0007; §6).

    Thin feature wrapper over :func:`qrp.features.volatility.barrier_volatility`, so the
    ``ewma_vol`` feature and the triple-barrier's sigma are computed by one estimator (I3).
    """

    bucket_minutes: int
    ewma_span_days: int
    timezone: str
    name: str = "ewma_vol"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """The single ``ewma_vol`` column."""
        return ("ewma_vol",)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute the shared time-of-day-bucketed barrier volatility."""
        vol = barrier_volatility(
            bars,
            bucket_minutes=self.bucket_minutes,
            ewma_span_days=self.ewma_span_days,
            timezone=self.timezone,
        )
        return vol.rename({"sigma": "ewma_vol"})


@dataclass(frozen=True)
class RangeVolatility:
    """Parkinson high-low volatility over a trailing window in bars (an independent estimate)."""

    window_bars: int
    name: str = "range_vol"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """The single ``range_vol`` column."""
        return ("range_vol",)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute Parkinson volatility from trailing high/low ranges, within the session date."""
        hl = pl.when((pl.col("high") > 0) & (pl.col("low") > 0)).then(
            (pl.col("high") / pl.col("low")).log() ** 2
        )
        parkinson = (
            (hl / (4.0 * math.log(2.0)))
            .rolling_mean(window_size=self.window_bars, min_samples=1)
            .over(_SESSION_DATE)
        )
        return bars.select("ts_utc", parkinson.sqrt().alias("range_vol"))


@dataclass(frozen=True)
class RelativeVolume:
    """Trailing-window (bars) z-score of volume (IBKR's *view* of volume, §5)."""

    window_bars: int
    name: str = "relative_volume"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """The single ``rel_volume`` column."""
        return ("rel_volume",)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute the trailing z-score of volume within the session date."""
        volume = pl.col("volume")
        mean = volume.rolling_mean(window_size=self.window_bars, min_samples=2).over(_SESSION_DATE)
        std = volume.rolling_std(window_size=self.window_bars, min_samples=2).over(_SESSION_DATE)
        z = pl.when(std > 0).then((volume - mean) / std).otherwise(None)
        return bars.select("ts_utc", z.alias("rel_volume"))


@dataclass(frozen=True)
class TimeOfDay:
    """Deterministic intraday context: minute-of-day (ET) and session one-hots."""

    timezone: str
    name: str = "time_of_day"
    is_deterministic: bool = True

    @property
    def output_columns(self) -> tuple[str, ...]:
        """Minute-of-day plus the PRE/RTH/POST one-hot columns."""
        return ("minute_of_day", "is_pre", "is_rth", "is_post")

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute deterministic calendar features (not lagged by the store)."""
        et = pl.col("ts_utc").dt.convert_time_zone(self.timezone)
        # Cast before arithmetic: dt.hour()/dt.minute() are Int8 and 10*60 would overflow.
        minute_of_day = et.dt.hour().cast(pl.Int32) * 60 + et.dt.minute().cast(pl.Int32)
        return bars.select(
            "ts_utc",
            minute_of_day.alias("minute_of_day"),
            (pl.col("session") == "PRE").cast(pl.Int8).alias("is_pre"),
            (pl.col("session") == "RTH").cast(pl.Int8).alias("is_rth"),
            (pl.col("session") == "POST").cast(pl.Int8).alias("is_post"),
        )
