"""Acceptance test for the block-shuffle null — the block shuffle's ONLY reason to exist.

The block-shuffle deflation is tested-but-**dormant**: no Phase-3 model can trip it, because a
cross-sectional model's edge is broken by *any* label shuffle (measured, 2026-07-15: on the real
lake the memoriser's block-shuffle null equals its full-shuffle null at every block length). It
bites only a model that reads label *temporal order* — a sequence model, which the ``Model``
protocol cannot yet express. So this test builds a temporal adversary (predicts a test label from
the temporally-nearest training label) on long-range-autocorrelated labels and pins the separation:

* the **full** shuffle CERTIFIES the adversary (destroys the autocorrelation it rides → null at
  chance → deflation ~ 1) — the exact blind spot that motivated the block shuffle;
* the **block** shuffle REJECTS it (preserves within-block autocorrelation → null ~ observed →
  deflation ~ 0), while a genuine cross-sectional edge at similar magnitude still PASSES;
* the block length must exceed the autocorrelation decay (~H): at block ``= H`` the adversary is
  NOT rejected (degrades to a full shuffle), at ``10*H`` it is.

This keeps the machinery from rotting until a real sequence model arrives, without pretending it
guards today's models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import polars as pl

from qrp.validation.overfitting import (
    auc_deflation,
    block_bars_for_horizon,
)
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study

_F64 = npt.NDArray[np.float64]
_H = 30
_N = 8000


@dataclass(frozen=True)
class LaggedLabelAdversary:
    """TEMPORAL adversary: predicts a test label from the temporally-nearest TRAINING label.

    Reads label order via a time-position feature (the last column) — a sequence-style dependency
    the cross-sectional protocol would not normally permit. This is the *only* kind of model the
    block shuffle can catch; it exists solely to exercise that guard.
    """

    train_pos: _F64 | None = None
    train_y: _F64 | None = None

    def fit(self, x: _F64, y: _F64, sample_weight: _F64) -> LaggedLabelAdversary:
        """Store the training positions and labels (a new instance)."""
        return LaggedLabelAdversary(train_pos=x[:, -1].copy(), train_y=y.copy())

    def predict(self, x: _F64) -> _F64:
        """Return, per row, the label of the nearest training row in time (searchsorted)."""
        assert self.train_pos is not None and self.train_y is not None
        pos = x[:, -1]
        order = np.argsort(self.train_pos)
        tps = self.train_pos[order]
        ins = np.clip(np.searchsorted(tps, pos), 1, len(tps) - 1)
        nearer_left = (pos - tps[ins - 1]) <= (tps[ins] - pos)
        nn = order[np.where(nearer_left, ins - 1, ins)]
        result: _F64 = self.train_y[nn].astype(np.float64)
        return result


def _ar_labels(n: int, phi: float, rng: np.random.Generator) -> _F64:
    """+/-1 labels from the sign of a persistent AR(1) latent — autocorrelation well beyond H."""
    z = np.zeros(n)
    for t in range(1, n):
        z[t] = phi * z[t - 1] + rng.standard_normal()
    y = np.sign(z)
    y[y == 0] = 1.0
    return y.astype(np.float64)


def _lifespan_frame(n: int) -> dict[str, list[datetime]]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
        "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
        "exit_ts": [start + timedelta(minutes=i + _H + 1) for i in range(n)],
    }


def _study() -> Study:
    # Many small test folds so each test row has a training neighbour just past the purge — that is
    # where the autocorrelation the adversary rides actually lives.
    return Study(PurgedCPCV(n_groups=40, k_test_groups=1))


def test_block_shuffle_rejects_temporal_artifact_but_passes_cross_sectional_edge() -> None:
    rng = np.random.default_rng(1)
    y = _ar_labels(_N, 0.99, rng)
    adv_df = pl.DataFrame({**_lifespan_frame(_N), "label": y, "pos": np.arange(_N, dtype=float)})
    study = _study()
    block = block_bars_for_horizon(_H)  # 10*H

    observed = study.run(adv_df, LaggedLabelAdversary(), feature_columns=["pos"], h_bars=_H).auc
    assert observed > 0.53  # the adversary rides the autocorrelation to a real OOS lift

    full = auc_deflation(
        study,
        adv_df,
        LaggedLabelAdversary(),
        observed_auc=observed,
        n_trials=5,
        feature_columns=["pos"],
        h_bars=_H,
        n_permutations=50,
        seed=0,
    )
    blocked = auc_deflation(
        study,
        adv_df,
        LaggedLabelAdversary(),
        observed_auc=observed,
        n_trials=5,
        feature_columns=["pos"],
        h_bars=_H,
        n_permutations=50,
        block_bars=block,
        seed=0,
    )
    assert full > 0.9  # FULL shuffle certifies the artifact as skill — the blind spot
    assert blocked < 0.2  # BLOCK shuffle rejects it — autocorrelation-riding, correctly caught

    # A genuine cross-sectional edge at similar magnitude must survive the same block shuffle.
    rng2 = np.random.default_rng(2)
    yb = rng2.choice([-1.0, 1.0], _N)
    edge = 0.30 * yb + np.sqrt(1 - 0.30**2) * rng2.standard_normal(_N)
    edge_df = pl.DataFrame({**_lifespan_frame(_N), "label": yb, "edge": edge})
    edge_obs = study.run(edge_df, CorrelationSignModel(), feature_columns=["edge"], h_bars=_H).auc
    edge_blocked = auc_deflation(
        study,
        edge_df,
        CorrelationSignModel(),
        observed_auc=edge_obs,
        n_trials=5,
        feature_columns=["edge"],
        h_bars=_H,
        n_permutations=50,
        block_bars=block,
        seed=0,
    )
    assert edge_blocked > 0.9  # cross-sectional edge passes — separation at equal magnitude


def test_block_length_must_exceed_autocorrelation_decay() -> None:
    # The block must be longer than the autocorrelation decay (~H). At block = H the structure is
    # destroyed and the block shuffle degrades to a full shuffle — failing to reject the artifact.
    rng = np.random.default_rng(1)
    y = _ar_labels(_N, 0.99, rng)
    adv_df = pl.DataFrame({**_lifespan_frame(_N), "label": y, "pos": np.arange(_N, dtype=float)})
    study = _study()
    observed = study.run(adv_df, LaggedLabelAdversary(), feature_columns=["pos"], h_bars=_H).auc

    too_short = auc_deflation(
        study,
        adv_df,
        LaggedLabelAdversary(),
        observed_auc=observed,
        n_trials=5,
        feature_columns=["pos"],
        h_bars=_H,
        n_permutations=50,
        block_bars=_H,
        seed=0,
    )
    long_enough = auc_deflation(
        study,
        adv_df,
        LaggedLabelAdversary(),
        observed_auc=observed,
        n_trials=5,
        feature_columns=["pos"],
        h_bars=_H,
        n_permutations=50,
        block_bars=block_bars_for_horizon(_H),
        seed=0,
    )
    assert too_short > 0.9  # block = H fails to reject (degraded to a full shuffle)
    assert long_enough < 0.2  # block = 10*H rejects — the constraint, pinned
