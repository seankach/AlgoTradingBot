"""The initial (v1) feature generators (ADR-0006) — deliberately minimal and causal.

Each generator computes **through bar t**; the store applies the point-in-time lag. All
rolling/EWMA statistics are grouped by ``_session_date`` so they reset each trading day and
never span the overnight gap. Untraded minutes keep null features (no forward-fill, §5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import polars as pl

_SESSION_DATE = "_session_date"


def _log_close() -> pl.Expr:
    """Natural log of a strictly-positive close, else null (avoids -inf/nan)."""
    return pl.when(pl.col("close") > 0).then(pl.col("close").log()).otherwise(None)


def _one_minute_log_return() -> pl.Expr:
    """1-minute log return within a session date (null at the day's first minute / gaps)."""
    log_close = _log_close()
    return (log_close - log_close.shift(1)).over(_SESSION_DATE)


@dataclass(frozen=True)
class LaggedReturns:
    """Lagged log returns of close over the configured minute horizons."""

    horizons_min: tuple[int, ...]
    name: str = "lagged_returns"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """One ``ret_{h}m`` column per configured horizon."""
        return tuple(f"ret_{h}m" for h in self.horizons_min)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute ``ln(close_t / close_{t-h})`` per horizon, within the session date."""
        log_close = _log_close()
        exprs = [
            (log_close - log_close.shift(h)).over(_SESSION_DATE).alias(f"ret_{h}m")
            for h in self.horizons_min
        ]
        return bars.select("ts_utc", *exprs)


@dataclass(frozen=True)
class SessionConditionalEwmaVol:
    """Causal EWMA of 1-min squared returns; session-conditional (§6).

    When ``session_conditional`` is true the EWMA resets per ``(session_date, session)`` so
    the open-hour spike does not bleed into midday across sessions. (Finer intraday
    conditioning within RTH is a candidate refinement for the label-spec ADR, since the
    barrier volatility defines the strategy — I3.)
    """

    span_bars: int
    session_conditional: bool
    name: str = "ewma_vol"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """The single ``ewma_vol`` column."""
        return ("ewma_vol",)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute the (session-conditional) EWMA volatility of 1-min returns."""
        group = [_SESSION_DATE, "session"] if self.session_conditional else [_SESSION_DATE]
        variance = (
            (_one_minute_log_return() ** 2)
            .ewm_mean(span=self.span_bars, ignore_nulls=True)
            .over(group)
        )
        return bars.select("ts_utc", variance.sqrt().alias("ewma_vol"))


@dataclass(frozen=True)
class RangeVolatility:
    """Parkinson high-low volatility over a trailing window (an independent OHLC estimate)."""

    window_min: int
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
            .rolling_mean(window_size=self.window_min, min_samples=1)
            .over(_SESSION_DATE)
        )
        return bars.select("ts_utc", parkinson.sqrt().alias("range_vol"))


@dataclass(frozen=True)
class RelativeVolume:
    """Trailing-window z-score of volume (IBKR's *view* of volume, §5)."""

    window_min: int
    name: str = "relative_volume"
    is_deterministic: bool = False

    @property
    def output_columns(self) -> tuple[str, ...]:
        """The single ``rel_volume`` column."""
        return ("rel_volume",)

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute the trailing z-score of volume within the session date."""
        volume = pl.col("volume")
        mean = volume.rolling_mean(window_size=self.window_min, min_samples=2).over(_SESSION_DATE)
        std = volume.rolling_std(window_size=self.window_min, min_samples=2).over(_SESSION_DATE)
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
