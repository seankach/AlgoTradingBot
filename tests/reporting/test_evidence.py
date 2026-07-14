"""Tests for the evidence reporting functions and lake assembly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.infrastructure.storage.snapshots import SnapshotStore
from qrp.reporting.build import assemble_validated
from qrp.reporting.evidence import (
    add_spread_columns,
    earliest_traded,
    row_counts_by_session,
    spread_distribution_by_session,
)
from qrp.validation.sessions import SessionTagger


def _indexed_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Build a session-indexed frame like the validation layer emits."""
    return pl.DataFrame(rows).with_columns(pl.col("ts_utc").dt.replace_time_zone("UTC"))


def test_row_counts_by_session_counts_only_traded() -> None:
    frame = _indexed_frame(
        [
            {"ts_utc": datetime(2024, 1, 3, 15, 0), "session": "RTH", "is_traded": True},
            {"ts_utc": datetime(2024, 1, 3, 15, 1), "session": "RTH", "is_traded": False},
            {"ts_utc": datetime(2024, 1, 3, 9, 0), "session": "PRE", "is_traded": True},
        ]
    )
    assert row_counts_by_session(frame) == {"RTH": 1, "PRE": 1}


def test_earliest_traded_ignores_untraded_rows() -> None:
    frame = _indexed_frame(
        [
            {"ts_utc": datetime(2024, 1, 3, 14, 0), "session": "PRE", "is_traded": False},
            {"ts_utc": datetime(2024, 1, 3, 15, 0), "session": "RTH", "is_traded": True},
        ]
    )
    assert earliest_traded(frame) == datetime(2024, 1, 3, 15, 0, tzinfo=UTC)


def test_spread_columns_and_distribution() -> None:
    # bid=open, ask=close; spread=ask-bid, midpoint=(bid+ask)/2.
    frame = pl.DataFrame(
        {
            "ts_utc": [datetime(2024, 1, 3, 15, 0, tzinfo=UTC)],
            "session": ["RTH"],
            "is_traded": [True],
            "open": [100.0],  # bid
            "high": [100.6],
            "low": [99.9],
            "close": [100.2],  # ask
            "volume": [10.0],
            "bar_count": [1],
            "wap": [100.1],
        }
    )
    with_spread = add_spread_columns(frame)
    assert with_spread["spread"].to_list()[0] == pytest.approx(0.2)
    # spread_bps = 0.2 / 100.1 * 1e4 ~= 19.98
    assert with_spread["spread_bps"].to_list()[0] == pytest.approx(0.2 / 100.1 * 10_000.0)

    stats = spread_distribution_by_session(frame)
    assert stats.filter(pl.col("session") == "RTH")["n"].to_list() == [1]


def _bars(start: datetime, n: int, close: float) -> list[Bar]:
    return [
        Bar(
            ts_utc=start + timedelta(minutes=i),
            open=1.0,
            high=2.0,
            low=0.5,
            close=close,
            volume=100.0,
            bar_count=1,
            wap=1.4,
        )
        for i in range(n)
    ]


def test_assemble_validated_from_lake(tmp_path: Path) -> None:
    store = SnapshotStore(StoragePathsConfig(data_root=tmp_path))
    # 15:00-15:04 UTC on 2024-01-03 is RTH.
    start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
    store.write_snapshot(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        bars=_bars(start, 5, close=1.5),
        request_timezone="America/New_York",
        bar_size="1 min",
    )
    frame = assemble_validated(
        store,
        SessionTagger(),
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        sessions_included=["RTH", "PRE", "POST", "OVERNIGHT"],
    )
    assert frame.filter(pl.col("is_traded")).height == 5
    assert row_counts_by_session(frame) == {"RTH": 5}


def test_assemble_resolves_frontier_settling_by_latest_fetch(tmp_path: Path) -> None:
    store = SnapshotStore(StoragePathsConfig(data_root=tmp_path))
    ts = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)  # a recent RTH minute
    # Two snapshots of the same bar with different close values (a still-settling frontier
    # bar re-fetched), each tagged with a different fetch time.
    store.write_snapshot(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        bars=_bars(ts, 1, close=1.5),
        request_timezone="America/New_York",
        bar_size="1 min",
        fetch_ts_utc=datetime(2026, 7, 14, 16, 0, tzinfo=UTC),
    )
    store.write_snapshot(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        bars=_bars(ts, 1, close=1.9),  # corrected value, later fetch
        request_timezone="America/New_York",
        bar_size="1 min",
        fetch_ts_utc=datetime(2026, 7, 14, 17, 0, tzinfo=UTC),
    )
    # Must not raise (frontier settling, not re-adjustment) and must keep the latest fetch.
    frame = assemble_validated(
        store,
        SessionTagger(),
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        sessions_included=["RTH"],
    )
    traded = frame.filter(pl.col("is_traded"))
    assert traded.height == 1
    assert traded.get_column("close").to_list() == [1.9]
