"""Sample-uniqueness weighting tests (CLAUDE.md §7)."""

from __future__ import annotations

import numpy as np

from qrp.validation.metrics import auc, weighted_auc
from qrp.validation.weights import uniqueness_weights

_MIN = 60_000_000  # one minute in microseconds


def test_non_overlapping_labels_weigh_one() -> None:
    # 1-min bars, each window a single distinct future bar -> concurrency 1 -> uniqueness 1. The
    # last two labels' windows run off the grid (incomplete, end-of-data), so check the interior.
    n = 12
    decision = np.arange(n, dtype=np.int64) * _MIN
    entry = decision + 1 * _MIN  # entry = the next bar
    exit_ = decision + 1 * _MIN  # exit = same bar (1-bar window); consecutive windows are disjoint
    w = uniqueness_weights(decision, entry, exit_)
    assert np.allclose(w[: n - 2], 1.0)


def test_overlapping_labels_are_downweighted() -> None:
    # Consecutive 30-bar windows overlap heavily -> effective sample << row count.
    n = 300
    decision = np.arange(n, dtype=np.int64) * _MIN
    entry = decision + 1 * _MIN
    exit_ = decision + 30 * _MIN
    w = uniqueness_weights(decision, entry, exit_)
    # The densely-overlapped middle (~30 concurrent) is downweighted toward 1/30.
    assert float(w[n // 2]) < 0.1
    # Effective sample size is far smaller than the row count.
    assert float(w.sum()) < n / 5
    assert float(w.max()) <= 1.0 + 1e-9  # uniqueness is bounded by 1


def test_weighted_auc_reduces_to_unweighted_when_uniform() -> None:
    rng = np.random.default_rng(0)
    pos = rng.random(500) < 0.4
    score = rng.standard_normal(500)
    assert weighted_auc(pos, score, np.ones(500)) == auc(pos, score)


def test_weighting_changes_the_auc() -> None:
    # A perfect ranking on the LOW-weight samples but wrong on the HIGH-weight ones scores worse
    # weighted than unweighted -- weighting is actually applied, not cosmetic.
    pos = np.array([True, True, False, False])
    score = np.array([0.9, 0.1, 0.2, 0.8])  # unweighted AUC = 0.5 (one right, one wrong pair-wise)
    weight = np.array([1.0, 5.0, 5.0, 1.0])  # emphasise the mis-ranked middle pair
    assert weighted_auc(pos, score, weight) != auc(pos, score)
