"""Lockbox enforcement tests (ADR-0009, build step 5) — the I5 machine guarantee.

Exercised against the in-memory fixture registry (no live server, per ADR-0009). The load-bearing
assertions are the ones that rot silently if removed: the THIRD touch must RAISE (not merely that
two appends succeed), a blank justification is rejected, and the counter is the append-only row
count so a touch cannot be un-counted.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from qrp.validation.lockbox import (
    InMemoryLockboxStore,
    Lockbox,
    LockboxBurnedError,
    LockboxError,
    LockboxTouch,
    PostgresLockboxStore,
)
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study

_DID = "dataset-abc123"
_SHA = "deadbeef"


def _lockbox(max_touches: int = 2) -> Lockbox:
    return Lockbox(InMemoryLockboxStore(), dataset_id=_DID, git_sha=_SHA, max_touches=max_touches)


# --------------------------------------------------------------------------------------------
# the third touch RAISES, and the raise does not itself increment (count stays at the limit)
# --------------------------------------------------------------------------------------------


def test_third_touch_raises_and_does_not_increment() -> None:
    box = _lockbox(max_touches=2)

    assert box.touch("first look: baseline GBM on the held-out year") == 1
    assert box.touch("second look: after the meta-labelling change") == 2
    assert box.count() == 2
    assert box.remaining() == 0

    with pytest.raises(LockboxBurnedError, match="burned"):
        box.touch("third look — should be refused")

    # The raise must NOT have appended a row: the count is still exactly the limit.
    assert box.count() == 2

    # A fourth attempt still raises and still does not increment (no off-by-one drift).
    with pytest.raises(LockboxBurnedError):
        box.touch("fourth look")
    assert box.count() == 2


# --------------------------------------------------------------------------------------------
# a blank/missing justification is rejected (the justification IS the audit trail)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_blank_justification_is_rejected(bad: str) -> None:
    box = _lockbox()
    with pytest.raises(LockboxError, match="justification"):
        box.touch(bad)
    # Rejecting a blank justification must not consume a touch.
    assert box.count() == 0


# --------------------------------------------------------------------------------------------
# tamper-evidence: the counter IS the row count; there is no un-count path
# --------------------------------------------------------------------------------------------


def test_counter_is_the_append_only_row_count() -> None:
    store = InMemoryLockboxStore()
    box = Lockbox(store, dataset_id=_DID, git_sha=_SHA)

    box.touch("only look")
    # The count equals the number of appended rows for this dataset_id, nothing else.
    assert box.count() == 1
    assert box.count() == len(store.touches(_DID))
    # The store exposes no update/delete — appends and counts only (append-only by construction).
    assert not hasattr(store, "delete")
    assert not hasattr(store, "update")

    # A second dataset_id has its own independent count (touches are scoped, not global rows).
    other = Lockbox(store, dataset_id="dataset-other", git_sha=_SHA)
    assert other.count() == 0


# --------------------------------------------------------------------------------------------
# Study.evaluate_lockbox is the ONLY path: it touches (before scoring), then evaluates
# --------------------------------------------------------------------------------------------


def _dataset(n: int = 400) -> pl.DataFrame:
    rng = np.random.default_rng(0)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],  # H=5 lifespan
            "label": rng.choice([-1.0, 1.0], n),
            "feat": rng.standard_normal(n),
        }
    )


def test_evaluate_lockbox_touches_then_scores_and_stops_when_burned() -> None:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    box = _lockbox(max_touches=2)
    data = _dataset()

    for i in range(2):
        result = study.evaluate_lockbox(
            data,
            CorrelationSignModel(),
            lockbox=box,
            justification=f"lockbox evaluation {i}",
            feature_columns=["feat"],
            h_bars=5,
        )
        assert not np.isnan(result.auc)
    assert box.count() == 2

    # The third evaluation is refused by the lockbox before any scoring happens.
    with pytest.raises(LockboxBurnedError):
        study.evaluate_lockbox(
            data,
            CorrelationSignModel(),
            lockbox=box,
            justification="one look too many",
            feature_columns=["feat"],
            h_bars=5,
        )
    assert box.count() == 2  # the refused look did not cost a touch increment


def test_evaluate_lockbox_blank_justification_is_refused_before_scoring() -> None:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    box = _lockbox()
    with pytest.raises(LockboxError, match="justification"):
        study.evaluate_lockbox(
            _dataset(),
            CorrelationSignModel(),
            lockbox=box,
            justification="   ",
            feature_columns=["feat"],
            h_bars=5,
        )
    assert box.count() == 0  # nothing recorded, nothing scored


# --------------------------------------------------------------------------------------------
# Postgres-backed store: same contract, skipped unless a disposable registry DSN is provided
# --------------------------------------------------------------------------------------------


@pytest.mark.skipif(
    "QRP_LOCKBOX_TEST_DSN" not in os.environ,
    reason="set QRP_LOCKBOX_TEST_DSN to a DISPOSABLE Postgres to run the lockbox integration test",
)
def test_postgres_store_roundtrip_and_row_count() -> None:
    store = PostgresLockboxStore(os.environ["QRP_LOCKBOX_TEST_DSN"])
    store.ensure_schema()
    did = f"it-{datetime.now(UTC).timestamp()}"
    box = Lockbox(store, dataset_id=did, git_sha=_SHA, max_touches=2)

    assert box.touch("first") == 1
    assert box.touch("second") == 2
    with pytest.raises(LockboxBurnedError):
        box.touch("third")
    assert box.count() == 2
    assert store.count(did) == len(store.touches(did)) == 2


def test_lockbox_touch_is_immutable() -> None:
    touch = LockboxTouch(datetime.now(UTC), _DID, _SHA, "why")
    with pytest.raises((AttributeError, TypeError)):
        touch.justification = "rewritten"  # type: ignore[misc]
