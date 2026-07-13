"""Tests for the validation layer: conflicts, session tags, gap index, quality flags."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from qrp.validation.conflicts import (
    SnapshotConflictError,
    assert_no_conflicts,
    find_conflicts,
)
from qrp.validation.quality import flag_quality
from qrp.validation.session_index import attach_bars, build_session_index
from qrp.validation.sessions import SessionTagger

_VALUE_COLS = ("open", "high", "low", "close", "volume", "bar_count", "wap")


def _value_frame(ts: list[datetime], closes: list[float]) -> pl.DataFrame:
    n = len(ts)
    return pl.DataFrame(
        {
            "ts_utc": ts,
            "open": [1.0] * n,
            "high": [2.0] * n,
            "low": [0.5] * n,
            "close": closes,
            "volume": [100.0] * n,
            "bar_count": [10] * n,
            "wap": [1.4] * n,
        }
    )


class TestConflicts:
    def test_consistent_snapshots_have_no_conflicts(self) -> None:
        ts = [datetime(2024, 1, 2, 14, 30, tzinfo=UTC)]
        a = _value_frame(ts, [1.5])
        b = _value_frame(ts, [1.5])
        assert find_conflicts([a, b]).height == 0
        assert_no_conflicts([a, b])  # does not raise

    def test_readjusted_prices_conflict_and_raise(self) -> None:
        ts = [datetime(2024, 1, 2, 14, 30, tzinfo=UTC)]
        original = _value_frame(ts, [1.5])
        readjusted = _value_frame(ts, [0.3])  # split re-adjustment
        assert find_conflicts([original, readjusted]).height == 1
        with pytest.raises(SnapshotConflictError, match="disagree"):
            assert_no_conflicts([original, readjusted])

    def test_non_overlapping_snapshots_do_not_conflict(self) -> None:
        a = _value_frame([datetime(2024, 1, 2, 14, 30, tzinfo=UTC)], [1.5])
        b = _value_frame([datetime(2024, 1, 2, 14, 31, tzinfo=UTC)], [9.9])
        assert find_conflicts([a, b]).height == 0


class TestSessionTagging:
    def test_tags_each_session(self) -> None:
        # 2024-01-03 is a regular Wednesday session (EST, UTC-5).
        rows = {
            datetime(2024, 1, 3, 14, 0, tzinfo=UTC): "PRE",  # 09:00 ET
            datetime(2024, 1, 3, 15, 0, tzinfo=UTC): "RTH",  # 10:00 ET
            datetime(2024, 1, 3, 21, 30, tzinfo=UTC): "POST",  # 16:30 ET
            datetime(2024, 1, 3, 2, 0, tzinfo=UTC): "OVERNIGHT",  # 21:00 ET prev day
            datetime(2024, 1, 6, 15, 0, tzinfo=UTC): "OVERNIGHT",  # Saturday
        }
        frame = pl.DataFrame({"ts_utc": list(rows.keys())})
        tagged = SessionTagger().tag_frame(frame).sort("ts_utc")
        got = dict(zip(tagged["ts_utc"].to_list(), tagged["session"].to_list(), strict=True))
        for ts, expected in rows.items():
            assert got[ts] == expected, ts

    def test_empty_frame_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty frame"):
            SessionTagger().tag_frame(pl.DataFrame({"ts_utc": []}))


class TestSessionIndex:
    def test_index_is_complete_and_flags_untraded(self) -> None:
        # A 10-minute RTH window on 2024-01-03: 15:00-15:10 UTC.
        start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
        end = start + timedelta(minutes=10)
        index = build_session_index(start, end, ["RTH"], SessionTagger())
        assert index.height == 10
        assert set(index["session"].unique().to_list()) == {"RTH"}

        # Only two of the ten minutes actually traded.
        traded_ts = [start, start + timedelta(minutes=3)]
        bars = _value_frame(traded_ts, [1.5, 1.6])
        attached = attach_bars(index, bars)
        assert attached["is_traded"].sum() == 2
        untraded = attached.filter(~pl.col("is_traded"))
        assert untraded["close"].null_count() == untraded.height  # never forward-filled


class TestQualityFlags:
    def _rth_frame(self, traded: list[bool], closes: list[float | None]) -> pl.DataFrame:
        start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
        n = len(traded)
        return pl.DataFrame(
            {
                "ts_utc": [start + timedelta(minutes=i) for i in range(n)],
                "session": ["RTH"] * n,
                "is_traded": traded,
                "open": [1.0 if t else None for t in traded],
                "high": [2.0 if t else None for t in traded],
                "low": [0.5 if t else None for t in traded],
                "close": closes,
                "volume": [100.0 if t else None for t in traded],
                "bar_count": [10 if t else None for t in traded],
                "wap": [1.4 if t else None for t in traded],
            }
        )

    def test_gaps_and_halt_flagged(self) -> None:
        # traded, then 5 consecutive gaps (halt), then traded.
        traded = [True, False, False, False, False, False, True]
        closes = [1.5, None, None, None, None, None, 1.5]
        flagged = flag_quality(self._rth_frame(traded, closes), halt_min_consecutive=5)
        assert flagged["is_gap"].sum() == 5
        assert flagged["is_halt"].sum() == 5  # the whole run qualifies

    def test_zero_volume_and_price_anomaly(self) -> None:
        frame = self._rth_frame([True, True], [1.5, 1.6])
        frame = frame.with_columns(
            volume=pl.Series([0.0, 100.0]),
            high=pl.Series([2.0, 0.4]),  # second bar: high < low -> anomaly
        )
        flagged = flag_quality(frame)
        assert flagged["is_zero_volume"].to_list() == [True, False]
        assert flagged["is_price_anomaly"].to_list() == [False, True]
