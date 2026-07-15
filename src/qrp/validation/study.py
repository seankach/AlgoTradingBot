"""Study — the only path to a metric (ADR-0009). Minimal scoring path (build step 2/3).

``Study.run`` turns ``(dataset, model)`` into a :class:`StudyResult` over the CPCV splits. The
**primary metric is AUC** — imbalance-robust and centred on 0.5 under chance — with balanced
accuracy alongside it; raw directional accuracy is kept only as a *diagnostic*, because under
class imbalance it rewards majority-class prediction rather than signal (review 2026-07-14).
When models emit calibrated probabilities (Phase 3/8), a proper scoring rule (log-loss / Brier)
becomes the number the deflated Sharpe is computed on; that is noted and deferred.

Multiclass scoring scheme (explicit — it affects every downstream number, incl. DSR):
    The label is three-class ``+1 / -1 / 0``. Scoring is **binary sign-AUC over the *resolved*
    (non-zero) labels**: the timeout class ``0`` is **held out** of the directional score, not
    treated as a discriminable third class (i.e. *not* macro one-vs-rest AUC). Rationale — the
    base strategy is directional (which barrier resolves first); a timeout is an *abstain* /
    "no clean move" outcome, and the trade-vs-no-trade decision is a separate meta-labelling
    problem (Phase 2), not part of the directional discrimination the barrier trades on.
    Consequence: ~21% of labels (the timeouts) do not enter the score; when meta-labelling
    lands, the timeout class gets its own gate rather than being folded into the AUC here.

The multiple-testing machinery (DSR/PBO), the lockbox, and the metric-module import boundary
are added in later build steps; this is the smallest substrate the leak canaries run through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import polars as pl

from qrp.validation.leakage import assert_features_are_not_outcomes
from qrp.validation.lockbox import Lockbox
from qrp.validation.metrics import balanced_accuracy, weighted_auc
from qrp.validation.splits import PurgedCPCV
from qrp.validation.trials import Trial, TrialSpec, TrialStore
from qrp.validation.weights import uniqueness_weights

_F64 = npt.NDArray[np.float64]
_I64 = npt.NDArray[np.int64]


@dataclass(frozen=True)
class StudyResult:
    """Out-of-fold scores aggregated across the CPCV paths."""

    auc: float  # primary: imbalance-robust, 0.5 = chance
    balanced_accuracy: float  # imbalance-robust
    accuracy: float  # DIAGNOSTIC ONLY — majority-class-biased under imbalance
    n_paths: int


@runtime_checkable
class Model(Protocol):
    """A weight-aware fit/predict model. Concrete trading models are Phase 3 (§10)."""

    def fit(self, x: _F64, y: _F64, sample_weight: _F64) -> Model:
        """Fit and return the fitted model (a new instance; no shared mutable state)."""
        ...

    def predict(self, x: _F64) -> _F64:
        """Return a real-valued score per row (higher = more likely the positive class)."""
        ...


@dataclass(frozen=True)
class CorrelationSignModel:
    """Reference baseline: score by the single most label-correlated feature.

    Minimal by design — enough to demonstrate a leak (a feature equal to the label is picked and
    scores perfectly) and to sit at chance otherwise. Not a trading model. Emits a *continuous*
    score (the signed feature value) so AUC is meaningful.
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
        """Score by the signed value of the selected feature (continuous)."""
        result: _F64 = (self.sign * np.nan_to_num(x, nan=0.0)[:, self.best]).astype(np.float64)
        return result


def _epoch_us(frame: pl.DataFrame, column: str) -> _I64:
    result: _I64 = frame.get_column(column).dt.epoch(time_unit="us").to_numpy().astype(np.int64)
    return result


class Study:
    """Runs a model over the CPCV splits and returns aggregated out-of-fold metrics.

    Sample-uniqueness weighting is ON (CLAUDE.md §7): overlapping labels are downweighted in both
    the fit and the AUC aggregation, so the effective sample — not the row count — drives it. If
    a ``trial_store`` is given, every ``run`` registers the trial it scores, so the count that
    deflates PBO / auc_deflation cannot silently miss a config that was tried (ADR-0010).
    """

    def __init__(self, splitter: PurgedCPCV, *, trial_store: TrialStore | None = None) -> None:
        self._splitter = splitter
        self._trial_store = trial_store

    def run(
        self,
        dataset: pl.DataFrame,
        model: Model,
        *,
        feature_columns: list[str],
        h_bars: int,
        label_column: str = "label",
        trial: TrialSpec | None = None,
    ) -> StudyResult:
        """Score ``model`` over every CPCV path and return the aggregated metrics.

        The dataset is sorted by ``decision_ts`` so split indices align with the arrays. Only
        non-zero labels are scored (the directional up/down question). This is the only place a
        number is produced (ADR-0009), so the label/outcome boundary guard (§7-b) fires here, and —
        if ``trial`` and a ``trial_store`` are set — the trial is registered against its OOS AUC.
        """
        assert_features_are_not_outcomes(feature_columns)
        ordered = dataset.sort("decision_ts")
        labels = ordered.select("decision_ts", "entry_ts", "exit_ts")
        x = ordered.select(feature_columns).to_numpy().astype(np.float64)
        y = ordered.get_column(label_column).to_numpy().astype(np.float64)
        weights = uniqueness_weights(
            _epoch_us(labels, "decision_ts"),
            _epoch_us(labels, "entry_ts"),
            _epoch_us(labels, "exit_ts"),
        )

        aucs: list[float] = []
        baccs: list[float] = []
        accs: list[float] = []
        for train_idx, test_idx in self._splitter.split(labels, h_bars=h_bars):
            if train_idx.size == 0 or test_idx.size == 0:
                continue
            fitted = model.fit(x[train_idx], y[train_idx], weights[train_idx])
            score = fitted.predict(x[test_idx])
            actual = y[test_idx]
            scored = actual != 0
            if scored.sum() < 2:
                continue
            positive = actual[scored] > 0
            fold_score = score[scored]
            fold_w = weights[test_idx][scored]
            fold_auc = weighted_auc(positive, fold_score, fold_w)
            if not math.isnan(fold_auc):
                aucs.append(fold_auc)
            baccs.append(balanced_accuracy(positive, fold_score > 0))
            accs.append(float(np.mean((fold_score > 0) == positive)))

        result = StudyResult(
            auc=float(np.mean(aucs)) if aucs else float("nan"),
            balanced_accuracy=float(np.mean(baccs)) if baccs else float("nan"),
            accuracy=float(np.mean(accs)) if accs else float("nan"),
            n_paths=len(accs),
        )
        if self._trial_store is not None and trial is not None:
            self._trial_store.register(
                Trial(
                    trial_hash=trial.hash(),
                    dataset_id=trial.dataset_id,
                    model_class=trial.model_class,
                    auc=result.auc,
                    registered_at=datetime.now(UTC),
                )
            )
        return result

    def block_aucs(
        self,
        dataset: pl.DataFrame,
        model: Model,
        *,
        feature_columns: list[str],
        h_bars: int,
        n_blocks: int,
        label_column: str = "label",
    ) -> _F64:
        """Per-block OOS AUC — one trial's PBO matrix row (ADR-0010 §1).

        Each of ``n_blocks`` contiguous time blocks is scored as a single purged test fold (reusing
        ``PurgedCPCV(n_blocks, 1)``, so the block seams are purged). Returns an ``n_blocks`` vector
        of AUCs (``nan`` where a block has no scorable both-class OOS labels).
        """
        assert_features_are_not_outcomes(feature_columns)
        ordered = dataset.sort("decision_ts")
        labels = ordered.select("decision_ts", "entry_ts", "exit_ts")
        x = ordered.select(feature_columns).to_numpy().astype(np.float64)
        y = ordered.get_column(label_column).to_numpy().astype(np.float64)
        weights = uniqueness_weights(
            _epoch_us(labels, "decision_ts"),
            _epoch_us(labels, "entry_ts"),
            _epoch_us(labels, "exit_ts"),
        )

        splitter = PurgedCPCV(n_groups=n_blocks, k_test_groups=1)
        out: list[float] = []
        for train_idx, test_idx in splitter.split(labels, h_bars=h_bars):
            if train_idx.size == 0 or test_idx.size == 0:
                out.append(float("nan"))
                continue
            fitted = model.fit(x[train_idx], y[train_idx], weights[train_idx])
            score = fitted.predict(x[test_idx])
            actual = y[test_idx]
            scored = actual != 0
            if scored.sum() < 2:
                out.append(float("nan"))
                continue
            out.append(weighted_auc(actual[scored] > 0, score[scored], weights[test_idx][scored]))
        return np.asarray(out, dtype=np.float64)

    def evaluate_lockbox(
        self,
        dataset: pl.DataFrame,
        model: Model,
        *,
        lockbox: Lockbox,
        justification: str,
        feature_columns: list[str],
        h_bars: int,
        label_column: str = "label",
    ) -> StudyResult:
        """Score the lockbox out-of-sample range — the **only** path that may touch it (I5).

        Records the touch *before* scoring, so a look costs a touch whether or not the evaluation
        then succeeds. Raises (without scoring) if the lockbox is burned or the justification is
        blank; see :meth:`qrp.validation.lockbox.Lockbox.touch`.
        """
        lockbox.touch(justification)
        return self.run(
            dataset,
            model,
            feature_columns=feature_columns,
            h_bars=h_bars,
            label_column=label_column,
        )
