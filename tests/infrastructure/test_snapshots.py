"""Unit tests for immutable content-addressed snapshot storage (ADR-0001/0003, I2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.infrastructure.storage.snapshots import (
    SnapshotManifest,
    SnapshotStore,
    compute_snapshot_id,
)


def _bar(ts: datetime, close: float = 1.5) -> Bar:
    return Bar(
        ts_utc=ts,
        open=1.0,
        high=2.0,
        low=0.5,
        close=close,
        volume=100.0,
        bar_count=10,
        wap=1.4,
    )


def _bars(start: datetime, n: int, close: float = 1.5) -> list[Bar]:
    return [_bar(start + timedelta(minutes=i), close) for i in range(n)]


def _store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(StoragePathsConfig(data_root=tmp_path))


_T0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def _write(store: SnapshotStore, bars: list[Bar], **kw: object) -> SnapshotManifest:
    return store.write_snapshot(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        bars=bars,
        request_timezone="America/New_York",
        bar_size="1 min",
        **kw,  # type: ignore[arg-type]
    )


def test_write_creates_partitioned_files_and_manifest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    manifest = _write(store, _bars(_T0, 5))

    assert manifest.row_count == 5
    assert manifest.range_start_utc == _T0
    assert manifest.range_end_utc == _T0 + timedelta(minutes=4)
    assert len(manifest.partition_files) == 1  # single UTC date
    for rel in manifest.partition_files:
        assert (tmp_path / "raw_snapshots" / rel).is_file()
        assert "symbol=TSLA" in rel
        assert "date=2024-01-02" in rel


def test_content_addressing_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _write(store, _bars(_T0, 5), fetch_ts_utc=datetime(2024, 1, 3, tzinfo=UTC))
    # Re-write identical data at a different fetch time -> same id, not duplicated.
    second = _write(store, _bars(_T0, 5), fetch_ts_utc=datetime(2024, 6, 1, tzinfo=UTC))
    assert first.snapshot_id == second.snapshot_id
    assert second.fetch_ts_utc == first.fetch_ts_utc  # existing manifest returned unchanged
    assert len(store.list_manifests()) == 1


def test_changed_values_yield_new_coexisting_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _write(store, _bars(_T0, 5, close=1.5))
    # Simulate IBKR retroactive split re-adjustment: same range, different prices.
    readjusted = _write(store, _bars(_T0, 5, close=0.3))
    assert original.snapshot_id != readjusted.snapshot_id
    assert len(store.list_manifests()) == 2  # both retained; nothing overwritten


def test_partitions_split_across_utc_dates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # Straddle midnight UTC: 23:58, 23:59, 00:00, 00:01
    start = datetime(2024, 1, 2, 23, 58, tzinfo=UTC)
    manifest = _write(store, _bars(start, 4))
    assert len(manifest.partition_files) == 2


def test_read_snapshot_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    manifest = _write(store, _bars(_T0, 3))
    frame = store.read_snapshot(manifest)
    assert frame.height == 3
    assert frame["snapshot_id"].unique().to_list() == [manifest.snapshot_id]
    assert frame["ts_utc"].to_list()[0] == _T0


def test_empty_snapshot_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty snapshot"):
        _write(_store(tmp_path), [])


def test_snapshot_id_depends_on_series(tmp_path: Path) -> None:
    bars = _bars(_T0, 3)
    trades = compute_snapshot_id(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        request_timezone="America/New_York",
        bar_size="1 min",
        bars=bars,
    )
    bid_ask = compute_snapshot_id(
        symbol="TSLA",
        what_to_show=WhatToShow.BID_ASK,
        request_timezone="America/New_York",
        bar_size="1 min",
        bars=bars,
    )
    assert trades != bid_ask
