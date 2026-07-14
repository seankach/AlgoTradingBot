"""Tests for the point-in-time feature store — the priority is proving no future leak (I1)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from qrp.config.models import (
    FeatureSpecConfig,
    StoragePathsConfig,
    VolatilityEstimatorConfig,
)
from qrp.features.protocols import FeatureGenerator
from qrp.features.store import FeatureStore, build_and_store, build_features, default_generators

_TZ = "America/New_York"


def _generators() -> list[FeatureGenerator]:
    spec = FeatureSpecConfig(
        version="t",
        return_horizons_min=[1, 5, 15, 30],
        range_vol_window_min=30,
        relative_volume_window_min=60,
    )
    vol = VolatilityEstimatorConfig(method="ewma", window_bars=60, session_conditional=True)
    return default_generators(spec, vol, timezone=_TZ)


def _validated(closes: list[float]) -> pl.DataFrame:
    n = len(closes)
    start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)  # 10:00 ET, RTH
    return pl.DataFrame(
        {
            "ts_utc": [start + timedelta(minutes=i) for i in range(n)],
            "session": ["RTH"] * n,
            "open": list(closes),
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": list(closes),
            "volume": [100.0 + i for i in range(n)],
            "is_traded": [True] * n,
        }
    )


def test_no_future_leak_last_bar_changes_nothing() -> None:
    # Perturbing the final bar's data must not change ANY stored feature: its effect is
    # lagged one bar, which falls off the end. This is the point-in-time guarantee (I1).
    base = _validated([10.0 + i for i in range(25)])
    perturbed = _validated([10.0 + i for i in range(24)] + [1.0e9])
    gens = _generators()
    f_base = build_features(base, gens, timezone=_TZ)
    f_pert = build_features(perturbed, gens, timezone=_TZ)
    assert f_base.equals(f_pert)


def test_returns_are_lagged_by_one_bar() -> None:
    frame = _validated([10.0, 20.0, 40.0, 80.0, 160.0, 320.0])
    out = build_features(frame, _generators(), timezone=_TZ).sort("ts_utc")
    ret1 = out.get_column("ret_1m").to_list()
    # through-t ret_1m(t)=ln(c_t/c_{t-1}); after the 1-bar lag, stored(t)=through(t-1).
    assert ret1[0] is None
    assert ret1[1] is None
    assert ret1[2] == pytest.approx(math.log(2.0))  # ln(c1/c0) = ln 2


def test_deterministic_features_are_not_lagged() -> None:
    out = build_features(_validated([10.0, 11.0, 12.0]), _generators(), timezone=_TZ)
    minute = out.get_column("minute_of_day").to_list()
    # 15:00 UTC = 10:00 ET = minute 600; NOT lagged, so row 1 is 601 (the bar's own time).
    assert minute[0] == 600
    assert minute[1] == 601


def test_expected_feature_columns_present() -> None:
    out = build_features(_validated([10.0 + i for i in range(40)]), _generators(), timezone=_TZ)
    for column in (
        "ret_1m",
        "ret_5m",
        "ret_15m",
        "ret_30m",
        "ewma_vol",
        "range_vol",
        "rel_volume",
        "minute_of_day",
        "is_pre",
        "is_rth",
        "is_post",
    ):
        assert column in out.columns


def test_empty_input_returns_empty() -> None:
    assert build_features(pl.DataFrame(), _generators(), timezone=_TZ).is_empty()


def test_store_round_trip_and_manifest(tmp_path: Path) -> None:
    store = FeatureStore(StoragePathsConfig(data_root=tmp_path))
    frame = _validated([10.0 + i for i in range(30)])
    manifest = build_and_store(
        frame, store, _generators(), symbol="TSLA", feature_spec_version="t", timezone=_TZ
    )
    assert manifest is not None
    assert "ewma_vol" in manifest.feature_columns
    assert store.read("TSLA").height == 30
    assert store.read_manifest("TSLA") == manifest
    assert (tmp_path / "features" / "symbol=TSLA" / "_build.json").is_file()
