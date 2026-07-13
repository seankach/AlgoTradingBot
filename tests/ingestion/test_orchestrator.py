"""Tests for the ingestion orchestrator against a fake MarketDataSource."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.infrastructure.storage.snapshots import SnapshotStore
from qrp.ingestion.orchestrator import DepthMarker, Ingestor

_TZ = "America/New_York"


class FakeSource:
    """A MarketDataSource returning a contiguous 1-min series in [data_start, data_end)."""

    def __init__(self, data_start: datetime, data_end: datetime) -> None:
        self.data_start = data_start
        self.data_end = data_end
        self.fetch_calls: list[tuple[datetime, datetime]] = []

    def earliest_available_timestamp(
        self, symbol: str, what_to_show: WhatToShow, *, bar_size: str
    ) -> datetime | None:
        return self.data_start

    def fetch_bars(
        self,
        symbol: str,
        *,
        start_utc: datetime,
        end_utc: datetime,
        what_to_show: WhatToShow,
        bar_size: str,
        use_rth: bool,
        request_timezone: str,
    ) -> list[Bar]:
        self.fetch_calls.append((start_utc, end_utc))
        lo = max(start_utc, self.data_start)
        hi = min(end_utc, self.data_end)
        bars: list[Bar] = []
        cur = lo
        while cur < hi:
            bars.append(
                Bar(
                    ts_utc=cur,
                    open=1.0,
                    high=2.0,
                    low=0.5,
                    close=1.5,
                    volume=100.0,
                    bar_count=1,
                    wap=1.4,
                )
            )
            cur += timedelta(minutes=1)
        return bars


def _ingestor(source: FakeSource, tmp_path: Path, now: datetime) -> Ingestor:
    store = SnapshotStore(StoragePathsConfig(data_root=tmp_path))
    return Ingestor(
        source,
        store,
        request_timezone=_TZ,
        depth_dir=tmp_path / "manifests" / "depth",
        clock=lambda: now,
    )


def test_backfill_windows_history_and_persists_depth(tmp_path: Path) -> None:
    now = datetime(2024, 1, 4, 0, 0, tzinfo=UTC)
    data_start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    source = FakeSource(data_start, now)
    ingestor = _ingestor(source, tmp_path, now)

    manifests = ingestor.backfill("TSLA", WhatToShow.TRADES, window=timedelta(days=1))

    assert len(manifests) == 3  # three 1-day windows
    depth_file = tmp_path / "manifests" / "depth" / "TSLA_TRADES.json"
    assert depth_file.is_file()
    marker = DepthMarker.model_validate_json(depth_file.read_text(encoding="utf-8"))
    assert marker.earliest_utc == data_start
    total_rows = sum(m.row_count for m in manifests)
    assert total_rows == 3 * 24 * 60


def test_incremental_resumes_from_last_end(tmp_path: Path) -> None:
    data_start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    now1 = datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
    source = FakeSource(data_start, data_end=datetime(2024, 1, 5, 0, 0, tzinfo=UTC))

    first = _ingestor(source, tmp_path, now1).incremental("TSLA", WhatToShow.TRADES)
    assert first is not None
    assert first.range_end_utc == now1 - timedelta(minutes=1)

    # A day later, the incremental run must resume from the previous last bar.
    now2 = datetime(2024, 1, 3, 0, 0, tzinfo=UTC)
    source.fetch_calls.clear()
    second = _ingestor(source, tmp_path, now2).incremental("TSLA", WhatToShow.TRADES)
    assert second is not None
    resume_start, resume_end = source.fetch_calls[0]
    assert resume_start == now1 - timedelta(minutes=1)  # one-bar overlap
    assert resume_end == now2


def test_backfill_resumes_from_frontier(tmp_path: Path) -> None:
    data_start = datetime(2024, 1, 1, tzinfo=UTC)
    source = FakeSource(data_start, data_end=datetime(2024, 1, 10, tzinfo=UTC))

    # First backfill up to Jan 4.
    _ingestor(source, tmp_path, now=datetime(2024, 1, 4, tzinfo=UTC)).backfill(
        "TSLA", WhatToShow.TRADES, window=timedelta(days=1)
    )

    # A later backfill must resume near the frontier, not restart at data_start.
    source.fetch_calls.clear()
    _ingestor(source, tmp_path, now=datetime(2024, 1, 7, tzinfo=UTC)).backfill(
        "TSLA", WhatToShow.TRADES, window=timedelta(days=1)
    )
    first_fetch_start = source.fetch_calls[0][0]
    assert first_fetch_start > data_start + timedelta(days=1)


def test_backfill_skips_when_no_depth(tmp_path: Path) -> None:
    now = datetime(2024, 1, 4, tzinfo=UTC)

    class NoDepthSource(FakeSource):
        def earliest_available_timestamp(
            self, symbol: str, what_to_show: WhatToShow, *, bar_size: str
        ) -> datetime | None:
            return None

    source = NoDepthSource(now, now)
    assert _ingestor(source, tmp_path, now).backfill("TSLA", WhatToShow.TRADES) == []
