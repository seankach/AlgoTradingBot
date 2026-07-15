"""Tests for the purged/embargoed CPCV splitter (ADR-0009, step 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.validation.splits import PurgedCPCV, purged_train_mask

_MIN = 60_000_000  # one minute in microseconds


def test_purge_boundary_is_exact() -> None:
    # Samples 0,1,2 are train candidates; group 1 = {3,4} is the test fold.
    # Test span = [10min, 20min]. A train lifespan whose exit lands one bar BEFORE the span
    # start is kept; exactly ON it is purged; one bar AFTER is purged (ADR-0009 test 5c).
    entry = np.array([9, 10, 11, 10, 15], dtype=np.int64) * _MIN
    exit_ = np.array([9, 10, 11, 20, 20], dtype=np.int64) * _MIN
    bounds = [0, 3, 5]

    mask = purged_train_mask(entry, exit_, [1], bounds, embargo=0)

    assert mask.tolist() == [True, False, False, False, False]
    #                         ^exit 9  ^exit 10 ^exit 11  ^--- test ---^
    #                         keep     purge    purge


def test_embargo_removes_trailing_train_samples() -> None:
    n = 10
    entry = (np.arange(n) * _MIN).astype(np.int64)
    exit_ = entry.copy()  # point labels: only the embargo (not purge) trims the tail
    bounds = [0, 3, 6, 10]  # 3 groups

    mask = purged_train_mask(entry, exit_, [0], bounds, embargo=2)

    # group 0 = {0,1,2} test; samples 3,4 embargoed; 5..9 remain train.
    assert mask.tolist() == [False, False, False, False, False, True, True, True, True, True]


def _labels(n: int) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],  # H=5 lifespan
        }
    )


def test_cpcv_split_count_and_disjoint() -> None:
    cv = PurgedCPCV(n_groups=4, k_test_groups=2)
    splits = list(cv.split(_labels(40), h_bars=5))

    assert len(splits) == 6  # C(4, 2)
    for train_idx, test_idx in splits:
        assert test_idx.size > 0
        assert set(train_idx).isdisjoint(set(test_idx))  # purge/embargo guarantee no overlap
        # Purged train is strictly smaller than "everything not in test".
        assert train_idx.size <= 40 - test_idx.size
