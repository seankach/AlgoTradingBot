"""Tests for the validated-bar lake (build, persist, manifest, rebuild)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from qrp.config.models import StoragePathsConfig
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.infrastructure.storage.snapshots import SnapshotStore
from qrp.validation.lake import ValidatedBarStore, build_and_store, build_validated_bars
from qrp.validation.sessions import SessionTagger

# 15:00-15:04 UTC on 2024-01-03 is RTH.
_START = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
_SESSIONS = ["PRE", "RTH", "POST", "OVERNIGHT"]


def _bars(start: datetime, n: int, close: float = 1.5) -> list[Bar]:
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


def _seed(store: SnapshotStore, bars: list[Bar]) -> None:
    store.write_snapshot(
        symbol="TSLA",
        what_to_show=WhatToShow.TRADES,
        bars=bars,
        request_timezone="America/New_York",
        bar_size="1 min",
    )


def test_build_validated_bars_shape(tmp_path: Path) -> None:
    store = SnapshotStore(StoragePathsConfig(data_root=tmp_path))
    _seed(store, _bars(_START, 5))
    frame = build_validated_bars(store, SessionTagger(), symbol="TSLA", sessions_included=_SESSIONS)

    assert frame.filter(pl.col("is_traded")).height == 5
    for column in (
        "session",
        "is_traded",
        "is_gap",
        "is_halt",
        "is_zero_volume",
        "is_price_anomaly",
    ):
        assert column in frame.columns


def test_build_and_store_round_trip_and_manifest(tmp_path: Path) -> None:
    paths = StoragePathsConfig(data_root=tmp_path)
    snapshots = SnapshotStore(paths)
    validated = ValidatedBarStore(paths)
    _seed(snapshots, _bars(_START, 5))

    manifest = build_and_store(
        snapshots, validated, SessionTagger(), symbol="TSLA", sessions_included=_SESSIONS
    )
    assert manifest is not None
    assert manifest.traded_count == 5
    assert len(manifest.source_snapshot_ids) == 1
    assert (tmp_path / "validated_bars" / "symbol=TSLA" / "_build.json").is_file()

    read_back = validated.read("TSLA")
    assert read_back.filter(pl.col("is_traded")).height == 5
    assert validated.read_manifest("TSLA") == manifest


def test_rebuild_overwrites_without_duplicating(tmp_path: Path) -> None:
    paths = StoragePathsConfig(data_root=tmp_path)
    snapshots = SnapshotStore(paths)
    validated = ValidatedBarStore(paths)
    _seed(snapshots, _bars(_START, 5))

    build_and_store(
        snapshots, validated, SessionTagger(), symbol="TSLA", sessions_included=_SESSIONS
    )
    first = validated.read("TSLA").height
    # Rebuild from the same snapshots -> same rows, one partition file per date.
    build_and_store(
        snapshots, validated, SessionTagger(), symbol="TSLA", sessions_included=_SESSIONS
    )
    assert validated.read("TSLA").height == first
    files = list((tmp_path / "validated_bars" / "symbol=TSLA").glob("date=*/validated.parquet"))
    assert len(files) == 1  # single UTC date, not duplicated on rebuild


def test_no_snapshots_returns_none(tmp_path: Path) -> None:
    paths = StoragePathsConfig(data_root=tmp_path)
    result = build_and_store(
        SnapshotStore(paths),
        ValidatedBarStore(paths),
        SessionTagger(),
        symbol="TSLA",
        sessions_included=_SESSIONS,
    )
    assert result is None
