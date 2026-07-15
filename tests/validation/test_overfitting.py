"""PBO + auc_deflation tests (ADR-0010, build step 6).

CI contracts (ADR-0010):
* PBO reads HIGH on a known-overfit set (spiky trials that win in-sample, lose out-of-sample) and
  LOW on persistent genuine skill; it is undefined with < 2 trials.
* auc_deflation certifies a genuine edge and does NOT certify best-of-K noise (its null is measured
  by permutation through the real splitter).
* the S-sensitivity {8,16,24} is exercised so a block-choice artefact would surface.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.validation.overfitting import auc_deflation, deflated_probability, pbo
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study

# --------------------------------------------------------------------------------------------
# PBO
# --------------------------------------------------------------------------------------------


def _overfit_matrix(n_trials: int, s_blocks: int, seed: int = 0) -> np.ndarray:
    # Each trial spikes on ONE random block and is flat elsewhere: it wins in-sample when its spike
    # is in the IS half, then collapses out-of-sample -> the overfit signature PBO must catch.
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0, 0.01, size=(n_trials, s_blocks))
    for i in range(n_trials):
        m[i, rng.integers(s_blocks)] += 5.0
    return m


def _skill_matrix(n_trials: int, s_blocks: int, seed: int = 0) -> np.ndarray:
    # Persistent skill gradient: trial i is better everywhere. IS-best is consistently OOS-best.
    rng = np.random.default_rng(seed)
    skill = np.linspace(0.0, 1.0, n_trials).reshape(-1, 1)
    return skill + rng.normal(0.0, 0.01, size=(n_trials, s_blocks))


def test_pbo_high_for_overfit_low_for_persistent_skill() -> None:
    overfit = pbo(_overfit_matrix(20, 8))
    skill = pbo(_skill_matrix(20, 8))
    assert overfit > 0.5  # IS-best routinely lands below the OOS median
    assert skill < 0.15  # persistent skill is not overfitting
    assert overfit > skill


def test_pbo_undefined_below_two_trials_or_odd_blocks() -> None:
    assert math.isnan(pbo(np.zeros((1, 8))))  # one trial: no selection to overfit
    assert math.isnan(pbo(np.zeros((5, 7))))  # odd S: no symmetric split


def test_pbo_s_sensitivity_is_reportable() -> None:
    # ADR-0010 requires reporting PBO at S in {8,16,24}. Here we just exercise it and confirm the
    # overfit signature persists across S (if it swung wildly, that swing is the thing to surface).
    # max_splits is small so S=24 (C(24,12)=2.7M) exercises the Monte-Carlo path cheaply.
    values = {s: pbo(_overfit_matrix(20, s, seed=1), max_splits=3000) for s in (8, 16, 24)}
    assert all(v > 0.5 for v in values.values())


# --------------------------------------------------------------------------------------------
# deflated_probability (pure statistic)
# --------------------------------------------------------------------------------------------


def test_deflated_probability_math() -> None:
    null = np.linspace(0.40, 0.60, 1001)  # uniform-ish null around 0.5
    # An observed value at the top of the null: F ~ 1 -> survives many trials.
    assert deflated_probability(0.60, null, n_trials=50) > 0.9
    # An observed value at the null median: F ~ 0.5 -> collapses under many trials.
    assert deflated_probability(0.50, null, n_trials=20) < 0.05
    assert math.isnan(deflated_probability(0.5, np.array([]), n_trials=1))


# --------------------------------------------------------------------------------------------
# auc_deflation through the real permutation harness + block_aucs
# --------------------------------------------------------------------------------------------


def _frame(n: int, seed: int, *, edge: float) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    y = rng.choice([-1.0, 1.0], n)
    feat = edge * y + math.sqrt(1 - edge**2) * rng.standard_normal(n)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],
            "label": y,
            "feat": feat,
        }
    )


def test_auc_deflation_certifies_edge_and_rejects_noise() -> None:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    model = CorrelationSignModel()

    edge = _frame(1500, seed=0, edge=0.2)
    observed = study.run(edge, model, feature_columns=["feat"], h_bars=5).auc
    assert observed > 0.55  # a real edge

    # A genuine edge survives even a large trial count.
    d_edge = auc_deflation(
        study,
        edge,
        model,
        observed_auc=observed,
        n_trials=50,
        feature_columns=["feat"],
        h_bars=5,
        n_permutations=120,
        seed=1,
    )
    assert d_edge > 0.9

    # A noise feature: observed ~ 0.5, and best-of-K noise must NOT be certified as skill.
    noise = _frame(1500, seed=2, edge=0.0)
    obs_noise = study.run(noise, model, feature_columns=["feat"], h_bars=5).auc
    d_noise = auc_deflation(
        study,
        noise,
        model,
        observed_auc=obs_noise,
        n_trials=20,
        feature_columns=["feat"],
        h_bars=5,
        n_permutations=120,
        seed=3,
    )
    assert d_noise < 0.5  # not skill


def test_block_aucs_returns_per_block_vector() -> None:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    edge = _frame(2000, seed=0, edge=0.25)
    blocks = study.block_aucs(
        edge, CorrelationSignModel(), feature_columns=["feat"], h_bars=5, n_blocks=8
    )
    assert blocks.shape == (8,)
    finite = blocks[~np.isnan(blocks)]
    assert finite.size >= 6
    assert float(finite.mean()) > 0.55  # a real edge shows up in most blocks
