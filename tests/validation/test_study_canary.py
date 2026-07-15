"""The planted-leak canary (ADR-0009, step 3).

Prove the two-component pipeline (PurgedCPCV + minimal Study) *catches* a known leak before
anything is built on top: a feature that is a copy of the label must make the score spike,
while random features sit at chance. A framework that cannot catch a planted leak cannot be
trusted to clear an unplanted one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study


def _dataset(n: int, seed: int) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    y = rng.choice([-1.0, 1.0], n)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],  # H=5 lifespan
            "label": y,
            "f0": rng.standard_normal(n),  # noise
            "f1": rng.standard_normal(n),  # noise
            "leak": y.copy(),  # the planted leak: a copy of the label
        }
    )


def test_planted_leak_canary_is_caught() -> None:
    dataset = _dataset(600, seed=0)
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))

    clean = study.run(dataset, CorrelationSignModel(), feature_columns=["f0", "f1"], h_bars=5)
    leaked = study.run(
        dataset, CorrelationSignModel(), feature_columns=["f0", "f1", "leak"], h_bars=5
    )

    assert clean < 0.60  # random features -> ~chance
    assert leaked > 0.95  # the leak is exploited -> the score spikes (the canary is caught)
    assert leaked - clean > 0.30  # the spike is unmistakable, not marginal
