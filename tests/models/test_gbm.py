"""LightGBM adapter tests (ADR-0011) — it runs through the closed Study and learns a real edge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.models.gbm import LightGBMModel
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import Study
from qrp.validation.trials import InMemoryTrialStore, TrialSpec

_H = 20


def _dataset(n: int, seed: int) -> pl.DataFrame:
    # f0 carries a genuine directional edge; ~20% timeouts (label 0) are dropped from fit.
    rng = np.random.default_rng(seed)
    f0 = rng.standard_normal(n)
    latent = f0 + rng.standard_normal(n)
    label = np.where(latent > 0.6, 1.0, np.where(latent < -0.6, -1.0, 0.0))
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + _H + 1) for i in range(n)],
            "label": label,
            "f0": f0,
            "f1": rng.standard_normal(n),  # a noise feature
        }
    )


def test_lightgbm_learns_edge_through_study_with_inner_fold() -> None:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2), inner_val_frac=0.2)
    model = LightGBMModel(params={"num_leaves": 15, "learning_rate": 0.05})
    result = study.run(_dataset(4000, 0), model, feature_columns=["f0", "f1"], h_bars=_H)
    assert result.auc > 0.6  # recovers the directional edge out-of-sample
    assert result.n_paths > 0


def test_lightgbm_run_registers_a_trial() -> None:
    store = InMemoryTrialStore()
    study = Study(
        PurgedCPCV(n_groups=6, k_test_groups=2), trial_store=store, inner_val_frac=0.2
    )
    spec = TrialSpec(
        dataset_id="ds",
        model_class="LightGBMModel",
        hyperparameters={"num_leaves": 15},
        feature_spec_version="v1",
        label_spec_version="v1",
    )
    study.run(
        _dataset(2000, 1),
        LightGBMModel(params={"num_leaves": 15}),
        feature_columns=["f0", "f1"],
        h_bars=_H,
        trial=spec,
    )
    assert store.count("ds") == 1
