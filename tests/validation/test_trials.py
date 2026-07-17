"""Trial-registry tests (ADR-0010, build step 5/6) — the count that deflates every result.

Load-bearing: a new configuration increments; an idempotent re-run of the same hash does NOT; the
count is distinct-hash and scoped per dataset_id. If these rot, both PBO and auc_deflation silently
lose meaning.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from qrp.validation.trials import (
    InMemoryTrialStore,
    PostgresTrialStore,
    Trial,
    trial_hash,
)

_DID = "dataset-xyz"


def _trial(h: str, *, dataset_id: str = _DID, auc: float = 0.6) -> Trial:
    return Trial(h, dataset_id, "CorrelationSignModel", auc, datetime.now(UTC))


def test_trial_hash_is_stable_and_config_sensitive() -> None:
    def h(
        model_class: str = "GBM",
        hp: dict[str, object] | None = None,
        feats: list[str] | None = None,
    ) -> str:
        return trial_hash(
            dataset_id=_DID,
            model_class=model_class,
            hyperparameters={"depth": 3, "seed": 1} if hp is None else hp,
            feature_columns=["f0", "f1"] if feats is None else feats,
            feature_spec_version="2026.07.14-eventbar",
            label_spec_version="2026.07.14-eventbar",
        )

    assert h() == h()  # deterministic
    # Any fit-affecting field change -> different hash (a new bet).
    assert h() != h(hp={"depth": 4, "seed": 1})
    assert h() != h(hp={"depth": 3, "seed": 2})  # seed counts
    assert h() != h(model_class="RandomForest")
    assert h() == h(hp={"seed": 1, "depth": 3})  # key order in the dict must not matter
    # ADR-0010 amendment: a feature ABLATION is a distinct bet even with identical hyperparameters.
    assert h() != h(feats=["f0"])  # dropping a feature -> new trial
    assert h() != h(feats=["f0", "f1", "f2"])  # adding one -> new trial
    assert h() == h(feats=["f1", "f0"])  # column ORDER must not matter (it's a set)


def test_new_config_increments_but_rerun_is_idempotent() -> None:
    store = InMemoryTrialStore()
    a, b = _trial("aaa"), _trial("bbb")

    store.register(a)
    store.register(b)
    assert store.count(_DID) == 2

    # Re-running an identical hash (a reproduction, I6) must NOT increment.
    store.register(_trial("aaa", auc=0.61))  # same hash, different score -> still no increment
    assert store.count(_DID) == 2
    assert len(store.trials(_DID)) == 2


def test_count_is_scoped_per_dataset_id() -> None:
    store = InMemoryTrialStore()
    store.register(_trial("aaa", dataset_id="ds-1"))
    store.register(_trial("bbb", dataset_id="ds-1"))
    store.register(_trial("aaa", dataset_id="ds-2"))
    assert store.count("ds-1") == 2
    assert store.count("ds-2") == 1
    assert store.count("ds-3") == 0


@pytest.mark.skipif(
    "QRP_LOCKBOX_TEST_DSN" not in os.environ,
    reason="set QRP_LOCKBOX_TEST_DSN to a DISPOSABLE Postgres to run the trials integration test",
)
def test_postgres_trials_distinct_count() -> None:
    store = PostgresTrialStore(os.environ["QRP_LOCKBOX_TEST_DSN"])
    store.ensure_schema()
    did = f"it-{datetime.now(UTC).timestamp()}"
    store.register(_trial("aaa", dataset_id=did))
    store.register(_trial("bbb", dataset_id=did))
    store.register(_trial("aaa", dataset_id=did, auc=0.9))  # ON CONFLICT DO NOTHING
    assert store.count(did) == 2
    assert len(store.trials(did)) == 2
