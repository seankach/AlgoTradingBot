"""Tests for the research dataset: dataset_id reproducibility and feature/label alignment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from qrp.config.models import StoragePathsConfig
from qrp.dataset.manifest import compute_dataset_id
from qrp.dataset.store import DatasetStore, assemble_dataset, build_and_store

_START = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)


def _kwargs() -> dict[str, object]:
    return {
        "raw_snapshot_ids": ["a", "b", "c"],
        "bar_spec_version": "b1",
        "feature_spec_version": "f1",
        "label_spec_version": "l1",
        "cost_model_version": "c1",
        "git_sha": "deadbeef",
    }


class TestDatasetId:
    def test_deterministic_and_order_independent(self) -> None:
        a = compute_dataset_id(**_kwargs())  # type: ignore[arg-type]
        shuffled = {**_kwargs(), "raw_snapshot_ids": ["c", "a", "b"]}
        b = compute_dataset_id(**shuffled)  # type: ignore[arg-type]
        assert a == b  # snapshot-id order must not matter

    def test_changes_with_each_component(self) -> None:
        base = compute_dataset_id(**_kwargs())  # type: ignore[arg-type]
        for field, value in [
            ("raw_snapshot_ids", ["a", "b"]),
            ("bar_spec_version", "b2"),
            ("feature_spec_version", "f2"),
            ("label_spec_version", "l2"),
            ("cost_model_version", "c2"),
            ("git_sha", "cafe"),
        ]:
            changed = compute_dataset_id(**{**_kwargs(), field: value})  # type: ignore[arg-type]
            assert changed != base, field


def _features(n: int) -> pl.DataFrame:
    ts = [_START + timedelta(minutes=i) for i in range(n)]
    return pl.DataFrame(
        {
            "ts_utc": ts,
            "session": ["RTH"] * n,
            "is_traded": [True] * n,
            "ret_1b": [0.001 * i for i in range(n)],
            "ewma_vol": [0.01] * n,
        }
    )


def _labels(decision_indices: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "decision_ts": [_START + timedelta(minutes=i) for i in decision_indices],
            "entry_ts": [_START + timedelta(minutes=i + 1) for i in decision_indices],
            "exit_ts": [_START + timedelta(minutes=i + 5) for i in decision_indices],
            "label": [1, -1, 0][: len(decision_indices)],
            "touched": ["tp", "sl", "vertical"][: len(decision_indices)],
            "gross_return": [0.02, -0.02, 0.0][: len(decision_indices)],
            "sigma": [0.01] * len(decision_indices),
        }
    )


def test_assemble_aligns_features_at_decision_ts() -> None:
    features = _features(10)
    labels = _labels([2, 4, 6])
    dataset = assemble_dataset(features, labels)

    assert dataset.height == 3
    # The feature value on each row must be the one stamped at that decision_ts.
    row = dataset.filter(pl.col("decision_ts") == _START + timedelta(minutes=4)).row(0, named=True)
    assert row["ret_1b"] == 0.004  # feature value at decision minute 4
    assert row["label"] == -1
    for column in ("entry_ts", "exit_ts", "sigma", "session"):
        assert column in dataset.columns


def test_build_and_store_round_trip(tmp_path: Path) -> None:
    store = DatasetStore(StoragePathsConfig(data_root=tmp_path))
    manifest = build_and_store(
        _features(10),
        _labels([2, 4, 6]),
        store,
        symbol="TSLA",
        bar_spec_version="b1",
        feature_spec_version="f1",
        label_spec_version="l1",
        cost_model_version="c1",
        raw_snapshot_ids=["a", "b"],
        feature_columns=["ret_1b", "ewma_vol"],
        git_sha="deadbeef",
    )
    assert manifest is not None
    assert store.read("TSLA").height == 3
    assert store.read_manifest("TSLA") == manifest
    assert store.read_manifest_by_id(manifest.dataset_id) == manifest
