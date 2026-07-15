"""The planted-leak canaries (ADR-0009, step 3; review 2026-07-14).

Prove the two-component pipeline (PurgedCPCV + minimal Study) *catches* leaks before anything
is built on top, using the imbalance-robust AUC:

* the screaming case (copy-of-label) must hit AUC ~ 1.0 while noise sits at ~ 0.5;
* a **graded** canary (a feature at a *known* Pearson correlation to the label) must degrade
  gracefully down through the real-edge band (rho ~ 0.05-0.20), so we can read the framework's
  resolution limit — the smallest rho whose AUC is still distinguishable from the noise band.

The leak is built at an exact target correlation ``rho`` via ``leak = rho*y + sqrt(1-rho^2)*z``
(``y`` is +/-1 with unit variance, ``z`` independent standard normal), so the rungs are labelled
in the same rho units the review used. Under this construction the *population* AUC is
``Phi(rho*sqrt(2)/sqrt(1-rho^2))`` — e.g. rho=0.05 -> 0.528, 0.10 -> 0.556, 0.20 -> 0.614 —
which is what the crossover table below is compared against.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study


def _leak_at_corr(y: np.ndarray, rho: float, rng: np.random.Generator) -> np.ndarray:
    """A feature with exact Pearson correlation ``rho`` to the +/-1 label ``y``."""
    z = rng.standard_normal(len(y))
    return rho * y + math.sqrt(1.0 - rho**2) * z


def _base(n: int, seed: int) -> tuple[pl.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    y = rng.choice([-1.0, 1.0], n)
    frame = pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],  # H=5 lifespan
            "label": y,
            "f0": rng.standard_normal(n),  # noise
            "f1": rng.standard_normal(n),  # noise
        }
    )
    return frame, y


def _auc(frame: pl.DataFrame, columns: list[str]) -> float:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    return study.run(frame, CorrelationSignModel(), feature_columns=columns, h_bars=5).auc


def test_noise_baseline_is_centered_on_chance() -> None:
    # Averaged over seeds, pure-noise features must sit at AUC ~ 0.5 (not biased above it).
    aucs = [_auc(_base(1200, s)[0], ["f0", "f1"]) for s in range(12)]
    assert abs(float(np.mean(aucs)) - 0.5) < 0.02  # centered on chance


def test_screaming_leak_canary_is_caught() -> None:
    frame, y = _base(600, seed=0)
    leaked = frame.with_columns(pl.Series("leak", y))  # copy of the label

    clean_auc = _auc(frame, ["f0", "f1"])
    leaked_auc = _auc(leaked, ["f0", "f1", "leak"])

    assert abs(clean_auc - 0.5) < 0.05
    assert leaked_auc > 0.99  # the leak is exploited -> AUC spikes (caught)


def test_graded_canary_degrades_gracefully() -> None:
    # A feature at a KNOWN correlation to the label; AUC must fall monotonically as rho shrinks,
    # down through the real-edge band (rho 0.20 -> 0.05) toward chance. The 0.05/0.10 rungs are
    # where a real intraday edge lives, so this is the resolution the framework must show.
    rng = np.random.default_rng(7)
    frame, y = _base(8000, seed=1)
    rungs = (1.0, 0.5, 0.2, 0.15, 0.1, 0.05)
    aucs = []
    for rho in rungs:
        leak = _leak_at_corr(y, rho, rng)
        graded = frame.with_columns(pl.Series("leak", leak))
        aucs.append(_auc(graded, ["leak"]))
    # Monotone non-increasing as the leak weakens, from perfect toward chance.
    assert aucs[0] > 0.99
    assert all(aucs[i] >= aucs[i + 1] - 0.02 for i in range(len(aucs) - 1))
    # rho=0.20 (top of the real-edge band) is comfortably resolved above the noise band...
    assert aucs[2] > 0.58
    # ...while rho=0.05 (the bottom of it) has collapsed to just above chance: the resolution
    # limit. The population AUC there is ~0.528, so at this sample size it is barely a signal.
    assert aucs[-1] < 0.56
