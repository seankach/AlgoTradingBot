"""End-to-end: the framework must KILL a model overfit on purpose (ADR-0009/0010 verification).

Every other test validates a piece in isolation. This one proves they *compose* into the thing the
framework was built to be: a maximally-overfit model (a 1-NN memoriser — infinite capacity, zero
regularisation) is run through the real ``Study``, and the framework rejects it —

    high in-sample AUC (it memorised)  ->  out-of-sample AUC at chance  ->  deflation near zero,

and, for the *selection* pathology, PBO near 1 when the best of many block-overfit trials is picked.
These are two distinct overfitting modes and two distinct guards; the memoriser exercises the first,
the block-localised trials the second. If an overfit model got a clean bill, we want to know here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import polars as pl

from qrp.validation.metrics import auc
from qrp.validation.overfitting import auc_deflation, pbo
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import CorrelationSignModel, Study

_F64 = npt.NDArray[np.float64]


@dataclass(frozen=True)
class MemorizingModel:
    """1-nearest-neighbour: infinite capacity, no regularisation — memorises train, chance OOS.

    A test fixture, not a production model (§10 keeps models to Phase 3). It is exactly the "trained
    to memorise" adversary the framework must reject: on the training set every point is its own
    nearest neighbour (perfect recall), while on unseen rows the nearest neighbour's label is noise.
    """

    x_train: _F64 | None = None
    y_train: _F64 | None = None

    def fit(self, x: _F64, y: _F64, sample_weight: _F64) -> MemorizingModel:
        """Memorise the training rows (a new instance; no shared mutable state)."""
        return MemorizingModel(x_train=np.nan_to_num(x).copy(), y_train=y.copy())

    def predict(self, x: _F64) -> _F64:
        """Score each row by its nearest training row's label (squared-Euclidean 1-NN)."""
        assert self.x_train is not None and self.y_train is not None
        xt, xq = self.x_train, np.nan_to_num(x)
        d2 = (xq**2).sum(1)[:, None] - 2 * xq @ xt.T + (xt**2).sum(1)[None, :]
        result: _F64 = self.y_train[d2.argmin(axis=1)].astype(np.float64)
        return result


def _noise_dataset(n: int, n_features: int, seed: int) -> pl.DataFrame:
    # Real-shaped frame (decision/entry/exit lifespans, balanced labels) with PURE-NOISE features:
    # there is genuinely nothing to learn, so anything above chance OOS would be leakage/overfit.
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cols: dict[str, object] = {
        "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
        "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
        "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],
        "label": rng.choice([-1.0, 1.0], n),
    }
    for j in range(n_features):
        cols[f"f{j}"] = rng.standard_normal(n)
    return pl.DataFrame(cols)


def test_memorising_model_is_rejected_end_to_end() -> None:
    # Scope: NO-SIGNAL data (iid labels, pure-noise features) — the clean kill. On the real lake,
    # where labels are strongly autocorrelated (lag-1 ~ 0.64), the same memoriser's OOS settles at
    # ~0.514 (real regime autocorrelation, not memorisation) and the FULL-shuffle deflation
    # certifies it — the block-shuffle crossover (ADR-0009). That case is the block shuffle's job,
    # not this test's; here labels are iid, so autocorrelation is absent and the kill is clean.
    features = [f"f{j}" for j in range(6)]
    data = _noise_dataset(1400, n_features=6, seed=0)
    x = data.select(features).to_numpy().astype(np.float64)
    y = data.get_column("label").to_numpy().astype(np.float64)
    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))

    # 1. In-sample: the memoriser recalls its training labels almost perfectly.
    fitted = MemorizingModel().fit(x, y, np.ones(len(y)))
    is_auc = auc(y > 0, fitted.predict(x))
    assert is_auc > 0.95  # memorised

    # 2. Out-of-sample through the real Study: the memorisation evaporates to chance.
    oos = study.run(data, MemorizingModel(), feature_columns=features, h_bars=5)
    assert 0.45 < oos.auc < 0.55  # no genuine signal survives the purged split

    # 3. Deflation against the permutation null: the OOS ~0.5 is not skill, and best-of-K only
    #    makes that verdict stronger.
    deflation = auc_deflation(
        study,
        data,
        MemorizingModel(),
        observed_auc=oos.auc,
        n_trials=20,
        feature_columns=features,
        h_bars=5,
        n_permutations=40,
        seed=1,
    )
    assert deflation < 0.2  # the framework does not certify the memoriser as skill


def test_selection_overfitting_drives_pbo_high() -> None:
    # The other overfitting mode: try many configs, keep the winner. Each trial's feature is a
    # spurious signal localised to ONE time block; picking the in-sample-best systematically selects
    # a config that is chance out-of-sample -> PBO must climb toward 1.
    rng = np.random.default_rng(3)
    n, s_blocks = 2400, 8
    block = n // s_blocks
    y = rng.choice([-1.0, 1.0], n)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "decision_ts": [start + timedelta(minutes=i) for i in range(n)],
            "entry_ts": [start + timedelta(minutes=i + 1) for i in range(n)],
            "exit_ts": [start + timedelta(minutes=i + 6) for i in range(n)],
            "label": y,
        }
    )
    # Feature j spikes hard inside block j; a small global anchor (0.2*y) only stabilises the
    # reference model's learned SIGN (otherwise it is a coin-flip learned from noise) — the spike is
    # what each config overfits, and it lives in a different block for each config.
    for j in range(s_blocks):
        f = 0.2 * y + rng.standard_normal(n)
        lo, hi = j * block, (j + 1) * block
        f[lo:hi] += 1.2 * y[lo:hi]
        frame = frame.with_columns(pl.Series(f"f{j}", f))

    study = Study(PurgedCPCV(n_groups=6, k_test_groups=2))
    matrix = np.vstack(
        [
            study.block_aucs(
                frame,
                CorrelationSignModel(),
                feature_columns=[f"f{j}"],
                h_bars=5,
                n_blocks=s_blocks,
            )
            for j in range(s_blocks)
        ]
    )
    matrix = np.nan_to_num(matrix, nan=0.5)  # empty blocks -> chance, not a crash
    # Picking the in-sample-best block-overfit config lands it below the OOS median every time.
    assert pbo(matrix) > 0.85
