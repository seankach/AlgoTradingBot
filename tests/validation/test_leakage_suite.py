"""The §7 leakage suite (ADR-0009, build step 4).

Four tests, each at the layer its target leak enters (the layering principle):

* (a) no feature reads >= t  -- the close_t PIT property survives the dataset ASSEMBLY join;
* (b) no label leaks into features -- the outcome-boundary guard fires at the Study choke point;
* (c) purge/embargo boundary correctness -- full acceptance over a real CPCV split;
* (d) label shuffle at full strength (collapses even a frozen look-ahead leak to chance) and the
      time-order shuffle as the documented DORMANT tripwire (a no-op now, an alarm in Phase 3+).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from qrp.dataset.store import assemble_dataset
from qrp.validation.leakage import (
    LeakageError,
    assert_features_are_not_outcomes,
    shuffle_labels,
    shuffle_labels_block,
    shuffle_time_order,
)
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study

# --------------------------------------------------------------------------------------------
# shared fixtures
# --------------------------------------------------------------------------------------------


def _frame(y: np.ndarray) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    n = len(y)
    return pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],  # H=5 lifespan
            "label": y,
        }
    )


def _autocorr_labels(n: int, rng: np.random.Generator, flip_p: float = 0.02) -> np.ndarray:
    """Persistent +/-1 labels (blocks of same sign) -> the y_{i+1} look-ahead is a REAL signal."""
    y = np.empty(n)
    y[0] = rng.choice([-1.0, 1.0])
    for i in range(1, n):
        y[i] = -y[i - 1] if rng.random() < flip_p else y[i - 1]
    return y


def _auc(frame: pl.DataFrame, columns: list[str]) -> float:
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    return study.run(frame, CorrelationSignModel(), feature_columns=columns, h_bars=5).auc


# --------------------------------------------------------------------------------------------
# (a) no feature reads >= t -- the close_t PIT property survives the dataset ASSEMBLY join
# --------------------------------------------------------------------------------------------


def test_assembly_join_preserves_point_in_time() -> None:
    # Feature store output is already lagged: close_feature(t) = close_{t-1} (the close_t arbiter,
    # feature layer). This test guards the ASSEMBLY layer -- assemble_dataset joins on decision_ts,
    # and a wrong join key (e.g. entry_ts) would realign the feature onto close_t. Assert it does
    # not: on each decision bar the feature still carries the PREVIOUS close, never the current.
    start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
    closes = [10.0, 11.0, 13.0, 16.0, 20.0]
    features = pl.DataFrame(
        {
            "ts_utc": [start + timedelta(minutes=i) for i in range(len(closes))],
            "close_feature": [None, *closes[:-1]],  # already lagged: row t holds close_{t-1}
        }
    )
    labels = pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(len(closes))],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(len(closes))],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(len(closes))],
            "label": [1.0, -1.0, 1.0, -1.0, 1.0],
        }
    )

    joined = assemble_dataset(features, labels).sort("decision_ts")
    got = joined.get_column("close_feature").to_list()

    assert got[0] is None
    for t in range(1, len(closes)):
        assert got[t] == closes[t - 1]  # previous close, aligned to the decision bar
        assert got[t] != closes[t]  # never the current bar's close (I1)


# --------------------------------------------------------------------------------------------
# (b) no label leaks into features -- the outcome-boundary guard at the Study choke point
# --------------------------------------------------------------------------------------------


def test_outcome_column_as_feature_is_rejected() -> None:
    frame = _frame(np.random.default_rng(0).choice([-1.0, 1.0], 200))
    frame = frame.with_columns(f0=pl.lit(0.0), gross_return=pl.lit(0.01))

    # Scoring an outcome column as a feature must raise at the choke point, not silently succeed.
    for outcome in ("label", "gross_return", "exit_ts"):
        with pytest.raises(LeakageError, match="outcome columns used as features"):
            _auc(frame, ["f0", outcome])

    # A legitimate feature column passes the guard.
    assert_features_are_not_outcomes(["f0", "f1"])


# --------------------------------------------------------------------------------------------
# (c) purge/embargo boundary correctness -- full acceptance over a real CPCV split
# --------------------------------------------------------------------------------------------


def _contiguous_runs(sorted_idx: list[int]) -> list[tuple[int, int]]:
    """Merge a sorted index list into contiguous ``[lo, hi)`` runs."""
    runs: list[tuple[int, int]] = []
    for i in sorted_idx:
        if runs and runs[-1][1] == i:
            runs[-1] = (runs[-1][0], i + 1)
        else:
            runs.append((i, i + 1))
    return runs


def test_purge_embargo_full_acceptance() -> None:
    n, n_groups, k, h = 300, 6, 2, 5
    labels = _frame(np.ones(n)).drop("label")
    cv = PurgedCPCV(n_groups=n_groups, k_test_groups=k)
    entry = labels.get_column("entry_ts").dt.epoch("us").to_numpy()
    exit_ = labels.get_column("exit_ts").dt.epoch("us").to_numpy()
    embargo = max(h, int(np.ceil(0.01 * n)))  # PurgedCPCV.embargo_pct default 0.01

    for train_idx, test_idx in cv.split(labels, h_bars=h):
        train, test = set(train_idx.tolist()), set(test_idx.tolist())
        assert train.isdisjoint(test)
        # Purge/embargo act per CONTIGUOUS test run (two groups may be non-adjacent, e.g. {0,3}),
        # so check each run's own span -- never a global min/max across the gap between runs.
        for run_lo, run_hi in _contiguous_runs(sorted(test)):
            span_entry = entry[run_lo:run_hi].min()
            span_exit = exit_[run_lo:run_hi].max()
            for i in train_idx:  # no train lifespan overlaps this run's span (closed intervals)
                assert not (entry[i] <= span_exit and exit_[i] >= span_entry)
            embargoed = set(range(run_hi, min(run_hi + embargo, n)))  # trailing embargo is clean
            assert train.isdisjoint(embargoed)


# --------------------------------------------------------------------------------------------
# (d) label shuffle at full strength -- collapses even a FROZEN look-ahead leak to chance
# --------------------------------------------------------------------------------------------


def test_label_shuffle_collapses_edge_and_frozen_leak() -> None:
    rng = np.random.default_rng(0)
    # genuine cross-sectional edge (rho ~ 0.2 to its own label)
    y = rng.choice([-1.0, 1.0], 8000)
    edge = _frame(y).with_columns(
        pl.Series("feat", 0.2 * y + np.sqrt(1 - 0.2**2) * rng.standard_normal(len(y)))
    )
    # frozen one-bar look-ahead leak on AUTOCORRELATED labels -- a real predictive relationship,
    # not memorised noise, so a naive/structure-preserving shuffle could fail to break it.
    ya = _autocorr_labels(8000, np.random.default_rng(1))
    leak = _frame(ya).with_columns(pl.Series("feat", np.roll(ya, -1)))

    assert _auc(edge, ["feat"]) > 0.58  # edge is real pre-shuffle
    assert _auc(leak, ["feat"]) > 0.95  # leak screams pre-shuffle

    # A FULL random permutation must send BOTH to chance -- the leak too, not just the edge.
    assert abs(_auc(shuffle_labels(edge, seed=0), ["feat"]) - 0.5) < 0.03
    assert abs(_auc(shuffle_labels(leak, seed=0), ["feat"]) - 0.5) < 0.03


# --------------------------------------------------------------------------------------------
# (d) time-order shuffle -- the DORMANT tripwire: a no-op today, an alarm in Phase 3+
# --------------------------------------------------------------------------------------------


def test_time_order_shuffle_is_dormant_by_design() -> None:
    # Frozen-feature + memoryless model: AUC depends only on the (X_i, y_i) multiset, which a row
    # permutation preserves. So BOTH a genuine edge and a frozen look-ahead leak are UNCHANGED --
    # the shuffle is a no-op now. A future NON-null delta is the alarm (cross-sample dependency).
    rng = np.random.default_rng(0)
    y = rng.choice([-1.0, 1.0], 8000)
    edge = _frame(y).with_columns(
        pl.Series("feat", 0.2 * y + np.sqrt(1 - 0.2**2) * rng.standard_normal(len(y)))
    )
    ya = _autocorr_labels(8000, np.random.default_rng(1))
    leak = _frame(ya).with_columns(pl.Series("feat", np.roll(ya, -1)))

    for frame in (edge, leak):
        base = _auc(frame, ["feat"])
        shuffled = _auc(shuffle_time_order(frame, seed=3), ["feat"])
        assert abs(shuffled - base) < 0.01  # invariant today, by design


@pytest.mark.skip(
    reason="Block-shuffle discrimination is DORMANT until a sequence model exists (Phase 3+). "
    "Filed so the crossover reasoning is not rediscovered from scratch."
)
def test_block_shuffle_discriminates_sequence_edge_from_leak() -> None:
    """Second dormant tripwire — the mirror of the full-vs-frozen crossover (review 2026-07-15).

    Today the FULL label shuffle is the guard: it collapses even a frozen look-ahead leak to 0.5.
    But a full permutation also destroys the label AUTOCORRELATION itself. Once a sequence model
    (Phase 3+) can legitimately use temporal structure, "collapse to 0.5 under a full shuffle" no
    longer means "leak" — it also fires for a genuine sequence edge, the opposite overclaim.

    At that point the BLOCK shuffle takes over the discrimination duty: reordering contiguous label
    blocks preserves within-block autocorrelation (a genuine sequence edge survives) while breaking
    the X↔y tie across blocks (a spurious per-sample leak collapses). The full shuffle degrades to a
    memorisation check only.

    When armed (a real sequence model + block_size > its receptive field), this test asserts:
        * genuine sequence edge:  block-shuffled AUC stays elevated (autocorrelation preserved);
        * spurious per-sample leak: block-shuffled AUC collapses to ~0.5 (X↔y tie broken).
    The memoryless CorrelationSignModel cannot express the distinction, so the stub is skipped.
    """
    # Placeholder wiring so the helper stays covered/imported until the model class arrives.
    rng = np.random.default_rng(0)
    ya = _autocorr_labels(2000, rng)
    frame = _frame(ya).with_columns(pl.Series("feat", np.roll(ya, -1)))
    _ = shuffle_labels_block(frame, seed=0, block_size=200)
