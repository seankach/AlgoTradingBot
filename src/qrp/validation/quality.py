"""Data-quality flags — recorded as data, never raised as exceptions (§5).

Gaps, zero-volume bars, halts, and price anomalies are marked as boolean columns so
downstream logic can decide how to handle them, rather than aborting ingestion. Nothing
here forward-fills or mutates prices.
"""

from __future__ import annotations

import polars as pl

_DEFAULT_HALT_MIN_CONSECUTIVE = 5
_DEFAULT_MAX_ABS_MINUTE_RETURN = 0.5


def flag_quality(
    frame: pl.DataFrame,
    *,
    halt_min_consecutive: int = _DEFAULT_HALT_MIN_CONSECUTIVE,
    max_abs_minute_return: float = _DEFAULT_MAX_ABS_MINUTE_RETURN,
) -> pl.DataFrame:
    """Add quality-flag columns to a session-indexed frame.

    Requires columns ``ts_utc``, ``session``, ``is_traded`` and OHLCV (nullable where
    untraded). Adds, all non-null booleans:

    * ``is_gap`` — an untraded minute *inside* RTH (missing bar where trading is expected).
    * ``is_halt`` — part of a run of ``>= halt_min_consecutive`` consecutive RTH gaps.
    * ``is_zero_volume`` — a traded bar with non-positive volume.
    * ``is_price_anomaly`` — a traded bar with ``high < low``, a non-positive price, or a
      one-minute absolute return exceeding ``max_abs_minute_return``.
    """
    frame = frame.sort("ts_utc")

    is_gap = (~pl.col("is_traded")) & (pl.col("session") == "RTH")
    frame = frame.with_columns(is_gap=is_gap)

    # Run-length over consecutive is_gap values to detect halts.
    run_id = (pl.col("is_gap") != pl.col("is_gap").shift(1)).fill_null(value=True).cum_sum()
    frame = frame.with_columns(_run_id=run_id)
    run_len = pl.len().over("_run_id")
    frame = frame.with_columns(is_halt=pl.col("is_gap") & (run_len >= halt_min_consecutive)).drop(
        "_run_id"
    )

    prev_close = pl.col("close").shift(1)
    abs_return = ((pl.col("close") / prev_close) - 1.0).abs()
    is_price_anomaly = pl.col("is_traded") & (
        (pl.col("high") < pl.col("low"))
        | (pl.col("low") <= 0)
        | (pl.col("open") <= 0)
        | (pl.col("close") <= 0)
        | (abs_return > max_abs_minute_return).fill_null(value=False)
    )

    return frame.with_columns(
        is_zero_volume=pl.col("is_traded") & (pl.col("volume") <= 0),
        is_price_anomaly=is_price_anomaly,
    )
