"""Study registers every trial it scores (ADR-0010) — the count that deflates PBO/auc_deflation.

The failure this guards: tuning GBM hyperparameters against Study with the registry dormant, so a
promising config gets a deflation computed as if it were the only bet ever made — data-snooping
through the front door on turn one of Phase 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study
from qrp.validation.trials import InMemoryTrialStore, TrialSpec

_DID = "dataset-phase3"


def _dataset(n: int = 600, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],
            "label": rng.choice([-1.0, 1.0], n),
            "f0": rng.standard_normal(n),
        }
    )


def _spec(depth: int) -> TrialSpec:
    return TrialSpec(
        dataset_id=_DID,
        model_class="CorrelationSignModel",
        hyperparameters={"depth": depth},
        feature_spec_version="v1",
        label_spec_version="v1",
    )


def test_multi_config_session_increments_but_reruns_do_not() -> None:
    store = InMemoryTrialStore()
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2), trial_store=store)
    data = _dataset()

    # Three distinct configs -> three trials.
    for depth in (3, 4, 5):
        study.run(
            data, CorrelationSignModel(), feature_columns=["f0"], h_bars=5, trial=_spec(depth)
        )
    assert store.count(_DID) == 3

    # Re-running an identical config (a reproduction, I6) does NOT increment.
    study.run(data, CorrelationSignModel(), feature_columns=["f0"], h_bars=5, trial=_spec(3))
    assert store.count(_DID) == 3

    # The registered score is the OOS AUC, not nan.
    assert all(not np.isnan(t.auc) for t in store.trials(_DID))


def test_run_without_trial_or_store_registers_nothing() -> None:
    store = InMemoryTrialStore()
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2), trial_store=store)
    data = _dataset()
    # No trial spec passed -> nothing registered (backward-compatible default).
    study.run(data, CorrelationSignModel(), feature_columns=["f0"], h_bars=5)
    assert store.count(_DID) == 0
