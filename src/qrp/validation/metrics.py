"""Scoring primitives — **behind the Study door** (ADR-0009, enforced by import-linter).

These turn labels + scores into a number. They are deliberately isolated here and, by the
import-linter contract in ``pyproject.toml``, may be imported **only by**
:mod:`qrp.validation.study` — exactly like ``ib_async`` is confined to its adapter. The point is
that "``Study`` is the only path to a metric" is a *wall*, not a convention: no other production
module can compute an AUC that bypasses the purge/embargo, the trial counter, or the deflation.

(The wall governs the ``qrp`` package. Code outside it — a research notebook — is governed instead
by the exploration-surface discipline in ADR-0010 §5, since no import contract can analyse code that
is not part of the package.)
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.stats import rankdata

_F64 = npt.NDArray[np.float64]
_Bool = npt.NDArray[np.bool_]


def auc(actual_positive: _Bool, score: _F64) -> float:
    """Area under the ROC curve (Mann-Whitney), with average ranks for ties.

    ``0.5`` is chance regardless of class balance. Returns ``nan`` if a class is absent.
    """
    n_pos = int(actual_positive.sum())
    n_neg = int((~actual_positive).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(score)  # average ranks, 1-based
    return float((ranks[actual_positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def weighted_auc(actual_positive: _Bool, score: _F64, weight: _F64) -> float:
    """Sample-weighted AUC — the weighted Mann-Whitney statistic (CLAUDE.md §7).

    Equal to :func:`auc` when all weights are equal. Weighting downweights overlapping (redundant)
    labels so the score reflects the *effective* sample, not the row count. Ties split at 0.5.
    Returns ``nan`` if either class has zero total weight.
    """
    w_pos = float(weight[actual_positive].sum())
    w_neg = float(weight[~actual_positive].sum())
    if w_pos == 0.0 or w_neg == 0.0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    s, pos, w = score[order], actual_positive[order], weight[order]
    neg_w = w * ~pos
    _, inv = np.unique(s, return_inverse=True)
    grp_neg = np.zeros(int(inv.max()) + 1, dtype=np.float64)
    np.add.at(grp_neg, inv, neg_w)
    neg_below = np.concatenate([[0.0], np.cumsum(grp_neg)[:-1]])[inv]  # neg weight strictly below
    neg_tie = grp_neg[inv]  # neg weight at the same score
    contrib = (w * pos) * (neg_below + 0.5 * neg_tie)
    return float(contrib.sum() / (w_pos * w_neg))


def balanced_accuracy(actual_positive: _Bool, predicted_positive: _Bool) -> float:
    """Mean of per-class recall — 0.5 under chance regardless of class balance."""
    tp = int((predicted_positive & actual_positive).sum())
    fn = int((~predicted_positive & actual_positive).sum())
    tn = int((~predicted_positive & ~actual_positive).sum())
    fp = int((predicted_positive & ~actual_positive).sum())
    recall_pos = tp / (tp + fn) if (tp + fn) else float("nan")
    recall_neg = tn / (tn + fp) if (tn + fp) else float("nan")
    return float((recall_pos + recall_neg) / 2)
