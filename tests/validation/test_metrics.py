"""Tests for the imbalance-robust scoring primitives (ADR-0009; review 2026-07-14)."""

from __future__ import annotations

import numpy as np
import pytest

from qrp.validation.metrics import (
    auc,
    balanced_accuracy,
    conditional_weighted_auc,
    tail_accuracy,
)


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


def test_conditional_auc_kills_a_pure_calendar_edge_but_keeps_within_bucket_signal() -> None:
    # The defining property (EXP-003). Two buckets with opposite base rates; the "model" scores by
    # bucket alone (pure calendar, zero timing ability). Globally that ranks well; conditionally it
    # must be exactly chance, because inside a bucket the score is constant.
    rng = np.random.default_rng(0)
    bucket = np.repeat([0.0, 1.0], 400)
    # bucket 0 is 80% negative, bucket 1 is 80% positive -> a real between-bucket base rate
    pos = np.concatenate([rng.random(400) < 0.2, rng.random(400) < 0.8])
    calendar_score = bucket.copy()  # knows only the clock
    w = np.ones(800)

    # Globally the calendar looks like skill; conditionally it is exactly chance.
    assert auc(pos, calendar_score) > 0.7
    assert conditional_weighted_auc(pos, calendar_score, w, bucket) == pytest.approx(0.5)

    # A score with genuine within-bucket ranking survives the conditional metric.
    timing_score = pos.astype(float) + rng.normal(0, 0.1, 800)
    assert conditional_weighted_auc(pos, timing_score, w, bucket) > 0.9


def test_conditional_auc_equals_weighted_auc_with_one_bucket() -> None:
    rng = np.random.default_rng(1)
    pos = rng.random(300) < 0.4
    score = rng.standard_normal(300)
    one = np.zeros(300)
    assert conditional_weighted_auc(pos, score, np.ones(300), one) == pytest.approx(auc(pos, score))


def test_tail_accuracy_recovers_a_concentrated_edge_and_reads_chance_on_noise() -> None:
    # EXP-004's premise: AUC is an aggregate, so an edge could hide in a high-confidence tail.
    # A score that is pure noise EXCEPT in its extremes, where it is 90% right.
    rng = np.random.default_rng(0)
    n = 10_000
    pos = rng.random(n) < 0.5
    score = rng.standard_normal(n)  # noise -> globally uninformative
    # plant a 90%-accurate top/bottom decile
    hi, lo = np.quantile(score, 0.9), np.quantile(score, 0.1)
    top, bot = score >= hi, score <= lo
    pos[top] = rng.random(int(top.sum())) < 0.9  # top tail mostly positive
    pos[bot] = rng.random(int(bot.sum())) > 0.9  # bottom tail mostly negative
    w = np.ones(n)

    tail = tail_accuracy(pos, score, w, quantile=0.1)
    aggregate = auc(pos, score)
    assert tail > 0.85  # the tail edge is recovered...
    assert aggregate < 0.70  # ...while the AGGREGATE badly understates it (0.90 tail -> ~0.64 AUC)
    assert tail - aggregate > 0.2  # the whole premise of EXP-004: AUC can hide a concentrated edge

    # A purely noisy score has no tail edge.
    noise_pos = rng.random(n) < 0.5
    assert abs(tail_accuracy(noise_pos, score, w, quantile=0.1) - 0.5) < 0.05


def test_auc_nan_when_a_class_is_absent() -> None:
    assert np.isnan(auc(np.array([True, True]), np.array([1.0, 2.0])))
