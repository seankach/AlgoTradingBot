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

import math

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


def conditional_weighted_auc(
    actual_positive: _Bool, score: _F64, weight: _F64, bucket: _F64
) -> float:
    """Within-bucket weighted AUC — only same-bucket positive/negative pairs count (EXP-003).

    Answers "can the model rank an up-move above a down-move *that happened in the same bucket*".
    Because the base rate is constant inside a bucket, it can contribute nothing to the ranking, so
    a purely base-rate (calendar) edge scores 0.5 here while genuine conditional timing survives.

    Crucially this **fits no base rate**, so removing the calendar cannot itself leak: there is no
    estimated quantity to contaminate with test-period information. De-meaning the target would
    not work — for binary ``y`` and ``b = E[y|bucket]``, ``sign(y - b) == sign(y)`` always, so a
    residual target leaves a rank statistic untouched; the calendar pays via *between-bucket class
    balance*, which only a between-bucket operation can remove.

    Pooled over buckets by pair mass: ``sum_b(AUC_b * Wpos_b * Wneg_b) / sum_b(Wpos_b * Wneg_b)``.
    Equals :func:`weighted_auc` when there is a single bucket. Buckets lacking either class are
    skipped. Returns ``nan`` if no bucket contributes.
    """
    num = 0.0
    den = 0.0
    for b in np.unique(bucket):
        m = bucket == b
        pos_m, score_m, w_m = actual_positive[m], score[m], weight[m]
        w_pos = float(w_m[pos_m].sum())
        w_neg = float(w_m[~pos_m].sum())
        if w_pos == 0.0 or w_neg == 0.0:
            continue
        a = weighted_auc(pos_m, score_m, w_m)
        if math.isnan(a):
            continue
        num += a * w_pos * w_neg
        den += w_pos * w_neg
    return num / den if den > 0 else float("nan")


def balanced_accuracy(actual_positive: _Bool, predicted_positive: _Bool) -> float:
    """Mean of per-class recall — 0.5 under chance regardless of class balance."""
    tp = int((predicted_positive & actual_positive).sum())
    fn = int((~predicted_positive & actual_positive).sum())
    tn = int((~predicted_positive & ~actual_positive).sum())
    fp = int((predicted_positive & ~actual_positive).sum())
    recall_pos = tp / (tp + fn) if (tp + fn) else float("nan")
    recall_neg = tn / (tn + fp) if (tn + fp) else float("nan")
    return float((recall_pos + recall_neg) / 2)
