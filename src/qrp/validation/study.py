"""Study — the only path to a metric (ADR-0009). Minimal scoring path (build step 2).

At this stage ``Study.run`` turns ``(dataset, model)`` into a single out-of-fold score over the
CPCV splits. The multiple-testing machinery (deflated Sharpe, PBO), the lockbox, and the
metric-module import boundary are added in later build steps; this is deliberately the smallest
substrate the planted-leak canary (step 3) can run through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import polars as pl

from qrp.validation.splits import PurgedCPCV

_F64 = npt.NDArray[np.float64]


@runtime_checkable
class Model(Protocol):
    """A weight-aware fit/predict model. Concrete trading models are Phase 3 (§10)."""

    def fit(self, x: _F64, y: _F64, sample_weight: _F64) -> Model:
        """Fit and return the fitted model (a new instance; no shared mutable state)."""
        ...

    def predict(self, x: _F64) -> _F64:
        """Return a real-valued prediction per row (sign gives the direction)."""
        ...


@dataclass(frozen=True)
class CorrelationSignModel:
    """Reference baseline: predict the sign of the single most label-correlated feature.

    Minimal by design — enough to demonstrate a leak (a feature equal to the label is picked and
    predicted perfectly) and to sit at chance otherwise. Not a trading model.
    """

    best: int = -1
    sign: float = 1.0

    def fit(self, x: _F64, y: _F64, sample_weight: _F64) -> CorrelationSignModel:
        """Pick the feature with the highest absolute Pearson correlation to ``y``."""
        xf = np.nan_to_num(x, nan=0.0)
        y_centered = y - y.mean()
        best, best_abs, best_sign = -1, -1.0, 1.0
        for j in range(xf.shape[1]):
            xj = xf[:, j] - xf[:, j].mean()
            denom = math.sqrt(float((xj**2).sum()) * float((y_centered**2).sum()))
            corr = float((xj * y_centered).sum() / denom) if denom > 0 else 0.0
            if abs(corr) > best_abs:
                best, best_abs, best_sign = j, abs(corr), (1.0 if corr >= 0 else -1.0)
        return CorrelationSignModel(best=best, sign=best_sign)

    def predict(self, x: _F64) -> _F64:
        """Predict the (signed) direction from the selected feature."""
        column = np.nan_to_num(x, nan=0.0)[:, self.best]
        result: _F64 = (self.sign * np.sign(column)).astype(np.float64)
        return result


class Study:
    """Runs a model over the CPCV splits and returns a single out-of-fold score."""

    def __init__(self, splitter: PurgedCPCV) -> None:
        self._splitter = splitter

    def run(
        self,
        dataset: pl.DataFrame,
        model: Model,
        *,
        feature_columns: list[str],
        h_bars: int,
        label_column: str = "label",
    ) -> float:
        """Return the mean per-split directional accuracy on non-zero labels.

        The dataset is sorted by ``decision_ts`` so the split indices align with the feature and
        label arrays. This is the only place a number is produced (ADR-0009).
        """
        ordered = dataset.sort("decision_ts")
        labels = ordered.select("decision_ts", "entry_ts", "exit_ts")
        x = ordered.select(feature_columns).to_numpy().astype(np.float64)
        y = ordered.get_column(label_column).to_numpy().astype(np.float64)

        scores: list[float] = []
        for train_idx, test_idx in self._splitter.split(labels, h_bars=h_bars):
            if train_idx.size == 0 or test_idx.size == 0:
                continue
            fitted = model.fit(x[train_idx], y[train_idx], np.ones(train_idx.size))
            prediction = np.sign(fitted.predict(x[test_idx]))
            actual = np.sign(y[test_idx])
            scored = actual != 0
            if not scored.any():
                continue
            scores.append(float(np.mean(prediction[scored] == actual[scored])))
        return float(np.mean(scores)) if scores else float("nan")
