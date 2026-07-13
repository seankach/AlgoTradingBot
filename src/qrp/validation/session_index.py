"""Complete session-time index with an ``is_traded`` flag (§5).

Outside RTH many minutes have no trade; missing bars are *real*. This builds a complete
minute grid over the sessions in scope, left-joins the actual bars onto it, and marks
``is_traded``. Prices are **never** forward-filled — untraded minutes keep null prices.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import polars as pl

from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.validation.sessions import SessionTagger

_BAR_COLUMNS = ("open", "high", "low", "close", "volume", "bar_count", "wap")


def bars_to_frame(bars: Sequence[Bar]) -> pl.DataFrame:
    """Materialise neutral :class:`Bar` objects into a Polars frame."""
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "ts_utc": pl.Datetime("us", "UTC"),
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
        "bar_count": pl.Int64,
        "wap": pl.Float64,
    }
    return pl.DataFrame(
        {
            "ts_utc": [b.ts_utc for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "bar_count": [b.bar_count for b in bars],
            "wap": [b.wap for b in bars],
        },
        schema=schema,
    )


def build_session_index(
    start_utc: datetime,
    end_utc: datetime,
    sessions_included: Sequence[str],
    tagger: SessionTagger,
) -> pl.DataFrame:
    """Return every minute in ``[start_utc, end_utc)`` whose session is in scope.

    Columns: ``ts_utc`` (UTC, bar start) and ``session``.
    """
    minutes = pl.datetime_range(
        start_utc, end_utc, interval="1m", time_zone="UTC", closed="left", eager=True
    )
    grid = pl.DataFrame({"ts_utc": minutes})
    tagged = tagger.tag_frame(grid)
    return tagged.filter(pl.col("session").is_in(list(sessions_included))).sort("ts_utc")


def attach_bars(index: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """Left-join actual bars onto the session index and add ``is_traded``.

    Untraded minutes keep null OHLCV (no forward-fill, §5).
    """
    joined = index.join(bars.select("ts_utc", *_BAR_COLUMNS), on="ts_utc", how="left")
    return joined.with_columns(is_traded=pl.col("close").is_not_null()).sort("ts_utc")


def validated_frame(
    bars: Sequence[Bar],
    *,
    start_utc: datetime,
    end_utc: datetime,
    sessions_included: Sequence[str],
    tagger: SessionTagger,
    what_to_show: WhatToShow,
) -> pl.DataFrame:
    """Produce the session-tagged, gap-complete frame for a range (no quality flags yet)."""
    index = build_session_index(start_utc, end_utc, sessions_included, tagger)
    attached = attach_bars(index, bars_to_frame(bars))
    return attached.with_columns(what_to_show=pl.lit(str(what_to_show)))
