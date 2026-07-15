"""Tests for the imbalance-robust scoring primitives (ADR-0009; review 2026-07-14)."""

from __future__ import annotations

import numpy as np
import pytest

from qrp.validation.study import auc, balanced_accuracy


def test_metrics_are_imbalance_robust_but_accuracy_is_not() -> None:
    # 70% positive. A constant "always positive" predictor is pure majority-class betting.
    actual_positive = np.array([True] * 70 + [False] * 30)
    predicted_positive = np.ones(100, dtype=bool)
    constant_score = np.ones(100)

    # Raw accuracy is inflated to the majority fraction — the trap the review flagged.
    raw_accuracy = float(np.mean(predicted_positive == actual_positive))
    assert raw_accuracy == pytest.approx(0.70)

    # The robust metrics correctly report chance.
    assert balanced_accuracy(actual_positive, predicted_positive) == pytest.approx(0.5)
    assert auc(actual_positive, constant_score) == pytest.approx(0.5)


def test_auc_is_one_for_perfect_ranking() -> None:
    actual_positive = np.array([True, True, False, False])
    score = np.array([0.9, 0.8, 0.1, 0.2])
    assert auc(actual_positive, score) == pytest.approx(1.0)


def test_auc_nan_when_a_class_is_absent() -> None:
    assert np.isnan(auc(np.array([True, True]), np.array([1.0, 2.0])))
