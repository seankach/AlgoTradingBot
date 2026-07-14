"""Tests for triple-barrier labelling — the barrier walk with explicit sigma."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from qrp.config.models import StoragePathsConfig
from qrp.labels.store import LabelStore, build_and_store
from qrp.labels.triple_barrier import TripleBarrier

_START = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)  # RTH
# k=2, sigma=0.01 -> barriers at +/-2% of the entry open (100 -> 102 / 98).
_TB = TripleBarrier(k=2.0, h_bars=5)


def _frames(
    ohlc: list[tuple[float, float, float, float]],
    *,
    sigma: float = 0.01,
    traded: list[bool] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    n = len(ohlc)
    ts = [_START + timedelta(minutes=i) for i in range(n)]
    bars = pl.DataFrame(
        {
            "ts_utc": ts,
            "session": ["RTH"] * n,
            "open": [float(o) for o, _, _, _ in ohlc],
            "high": [float(h) for _, h, _, _ in ohlc],
            "low": [float(low) for _, _, low, _ in ohlc],
            "close": [float(c) for _, _, _, c in ohlc],
            "is_traded": traded if traded is not None else [True] * n,
        }
    )
    sig = pl.DataFrame({"ts_utc": ts, "sigma": [sigma] * n})
    return bars, sig


def _first(out: pl.DataFrame) -> dict[str, object]:
    return out.sort("decision_ts").row(0, named=True)


def test_take_profit_label() -> None:
    bars, sigma = _frames(
        [
            (100, 100.0, 100.0, 100.0),  # decision 0
            (100, 100.5, 99.6, 100.2),  # entry (open 100 -> upper 102, lower 98)
            (100.2, 101.0, 100.0, 100.8),
            (100.8, 102.5, 100.5, 102.2),  # high 102.5 >= 102 -> take-profit
            (102, 102, 101, 101.5),
            (101, 101, 100, 100.5),
        ]
    )
    row = _first(_TB.generate(bars, sigma))
    assert row["label"] == 1
    assert row["touched"] == "tp"
    gross = row["gross_return"]
    assert isinstance(gross, float) and gross > 0
    assert row["entry_ts"] == _START + timedelta(minutes=1)


def test_stop_loss_label() -> None:
    bars, sigma = _frames(
        [
            (100, 100.0, 100.0, 100.0),
            (100, 100.2, 99.8, 100.0),  # entry
            (100, 100.0, 99.0, 99.2),
            (99.2, 99.4, 97.5, 97.8),  # low 97.5 <= 98 -> stop-loss
            (98, 98.5, 97, 97.5),
            (97.5, 98, 97, 97.2),
        ]
    )
    row = _first(_TB.generate(bars, sigma))
    assert row["label"] == -1
    assert row["touched"] == "sl"
    gross = row["gross_return"]
    assert isinstance(gross, float) and gross < 0


def test_vertical_timeout_label() -> None:
    # Stays strictly inside +/-2% for longer than H -> timeout.
    bars, sigma = _frames([(100, 100.5, 99.5, 100.0)] * 8)
    row = _first(_TB.generate(bars, sigma))
    assert row["label"] == 0
    assert row["touched"] == "vertical"


def test_same_bar_both_touch_resolves_to_stop() -> None:
    # A bar spanning both barriers is a whipsaw; OHLCV cannot reveal order, so resolve
    # conservatively to the stop (label -1), keeping touched="both" as a diagnostic (ADR-0008).
    bars, sigma = _frames(
        [
            (100, 100.0, 100.0, 100.0),
            (100, 100.1, 99.9, 100.0),  # entry
            (100, 102.5, 97.5, 100.0),  # straddles both 102 and 98 in one bar
            (100, 100, 100, 100),
        ]
    )
    row = _first(_TB.generate(bars, sigma))
    assert row["label"] == -1  # conservative stop, NOT a silent 0/timeout
    assert row["touched"] == "both"
    gross = row["gross_return"]
    assert isinstance(gross, float) and gross < 0  # exit at the lower barrier


def test_entry_skips_untraded_bar() -> None:
    # Bar 1 is untraded; the entry for decision at bar 0 becomes the next traded bar (bar 2).
    bars, sigma = _frames(
        [
            (100, 100, 100, 100),
            (0, 0, 0, 0),  # untraded -> filtered out
            (105, 105, 105, 105),  # entry open = 105
            (105, 108, 104, 107),
            (107, 108, 106, 107),
        ],
        traded=[True, False, True, True, True],
    )
    row = _first(_TB.generate(bars, sigma))
    assert row["entry_ts"] == _START + timedelta(minutes=2)  # skipped the untraded minute


def test_build_and_store_round_trip_and_manifest(tmp_path: Path) -> None:
    store = LabelStore(StoragePathsConfig(data_root=tmp_path))
    bars, sigma = _frames(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.6, 100.2),
            (100.2, 101, 100, 100.8),
            (100.8, 102.5, 100.5, 102.2),
            (102, 102, 101, 101.5),
            (101, 101, 100, 100.5),
        ]
    )
    manifest = build_and_store(bars, sigma, _TB, store, symbol="TSLA", label_spec_version="t")
    assert manifest is not None
    assert manifest.method == "triple_barrier"
    assert sum(manifest.label_distribution.values()) == manifest.label_count
    assert store.read("TSLA").height == manifest.label_count
    assert store.read_manifest("TSLA") == manifest
