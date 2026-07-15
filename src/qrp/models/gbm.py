"""LightGBM adapter — the first Phase-3 model (ADR-0011).

Implements the ``Model`` protocol so it runs through the closed ``Study`` and nothing else. Two
decisions from ADR-0011 are baked in here:

* **Binary on resolved rows** — the timeout (``0``) labels are dropped from ``fit`` and the target
  is ``P(+1)``, aligning training with the binary sign-AUC that is actually scored (§7). Timeout-as-
  abstain is meta-labelling, deferred to Phase 8.
* **Early stopping on the Study-owned inner fold** — the model consumes the already-purged
  ``validation`` fold Study hands it; it never carves a split or sees a timestamp, so purge
  correctness stays inside the framework. Without a ``validation`` fold it trains to n_estimators.

Determinism is pinned (fixed seed, single thread) so results reproduce bit-for-bit (I6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from qrp.validation.study import FitValidation

_F64 = npt.NDArray[np.float64]

# Fixed for reproducibility (I6); hyperparameters that vary go through ``params`` (each a trial).
# Native LightGBM param names (the sklearn wrapper needs scikit-learn, which we do not depend on).
_DEFAULTS: dict[str, Any] = {
    "objective": "binary",
    "num_threads": 1,
    "seed": 0,
    "deterministic": True,
    "verbosity": -1,
}


@dataclass(frozen=True)
class LightGBMModel:
    """A weight-aware LightGBM booster behind the ``Model`` protocol (ADR-0011)."""

    params: Mapping[str, object] = field(default_factory=dict)
    num_boost_round: int = 2000
    early_stopping_rounds: int = 50
    _booster: lgb.Booster | None = None

    def fit(
        self,
        x: _F64,
        y: _F64,
        sample_weight: _F64,
        *,
        validation: FitValidation | None = None,
    ) -> LightGBMModel:
        """Train on resolved rows (``y != 0``); early-stop on the Study inner fold if given."""
        resolved = y != 0
        params: dict[str, Any] = {**_DEFAULTS, **dict(self.params)}
        train_set = lgb.Dataset(
            x[resolved], label=(y[resolved] > 0).astype(int), weight=sample_weight[resolved]
        )
        valid_sets: list[lgb.Dataset] | None = None
        callbacks: list[Any] | None = None
        if validation is not None:
            v = validation.y != 0
            valid_sets = [
                lgb.Dataset(
                    validation.x[v],
                    label=(validation.y[v] > 0).astype(int),
                    weight=validation.sample_weight[v],
                    reference=train_set,
                )
            ]
            callbacks = [lgb.early_stopping(self.early_stopping_rounds, verbose=False)]
        booster = lgb.train(
            params,
            train_set,
            num_boost_round=self.num_boost_round,
            valid_sets=valid_sets,
            callbacks=callbacks,
        )
        return replace(self, _booster=booster)

    def predict(self, x: _F64) -> _F64:
        """Return ``P(+1)`` per row (higher = more likely the up barrier resolves first)."""
        if self._booster is None:
            raise RuntimeError("LightGBMModel.predict called before fit")
        proba: _F64 = np.asarray(self._booster.predict(x), dtype=np.float64)
        return proba
