"""Multiple-testing control (ADR-0010, build step 6): PBO now, DSR deferred, AUC-deflation harness.

Two guards, split by dependency (ADR-0010):

* :func:`pbo` — probability of backtest overfitting via CSCV. Rank-based and distribution-free, so
  it works on the AUC we already have; no returns series (hence no backtester) required. It asks
  *how often the configuration that looks best in-sample lands below the median out-of-sample*.
* :func:`auc_deflation` — a multiple-testing deflation whose null is **measured, not assumed**:
  :func:`permutation_null` permutes labels through the *same* purged/embargoed splitter and
  recomputes AUC ``B`` times, so overlap, class balance, and purging are baked into the null by
  construction and there is no effective-``n`` to estimate. Named ``auc_deflation``, never DSR — the
  true returns-series DSR (Phase 5/6) is a different statistic on a different null and must never
  share an axis with this.

The returns-series DSR is intentionally absent: it needs a costed P&L series, i.e. the backtester,
which is Phase 5/6, not Module 5 (ADR-0010 rejects building an ad-hoc slice of it here).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from scipy.stats import rankdata

if TYPE_CHECKING:
    import polars as pl

    from qrp.validation.study import Model, Study

_F64 = npt.NDArray[np.float64]

# S: literature-comparable default (ADR-0010). Report S-sensitivity at {8, 16, 24} on real trials.
DEFAULT_PBO_BLOCKS = 16


def pbo(block_matrix: _F64, *, max_splits: int = 20_000, seed: int = 0) -> float:
    """Probability of backtest overfitting via CSCV (ADR-0010 §1).

    Args:
        block_matrix: shape ``(N_trials, S_blocks)`` of the OOS metric (higher is better), each
            row a trial, each column a purged time block. ``S`` even and ``N_trials >= 2``.
        max_splits: cap on the number of IS/OOS recombinations. ``C(S, S/2)`` explodes (S=16 →
            12,870 but S=24 → 2.7M), so when the full count exceeds this we **Monte-Carlo sample**
            ``max_splits`` recombinations instead of enumerating — the standard large-S CSCV move.
        seed: seed for the Monte-Carlo sampling (only used when sampling).

    Returns:
        The fraction of recombinations in which the in-sample-best trial lands at or below the
        out-of-sample median (logit ``lambda <= 0``). ``nan`` if fewer than two trials (no selection
        to overfit) or ``S`` is odd.
    """
    m = np.asarray(block_matrix, dtype=np.float64)
    n_trials, s_blocks = m.shape
    if n_trials < 2 or s_blocks < 2 or s_blocks % 2 != 0:
        return float("nan")

    half = s_blocks // 2
    if math.comb(s_blocks, half) <= max_splits:
        splits: Iterable[tuple[int, ...]] = combinations(range(s_blocks), half)
    else:
        rng = np.random.default_rng(seed)
        splits = (
            tuple(int(b) for b in rng.choice(s_blocks, half, replace=False))
            for _ in range(max_splits)
        )

    below = 0
    total = 0
    for is_blocks in splits:
        is_mask = np.zeros(s_blocks, dtype=bool)
        is_mask[list(is_blocks)] = True
        is_perf = m[:, is_mask].mean(axis=1)
        oos_perf = m[:, ~is_mask].mean(axis=1)
        best_is = int(np.argmax(is_perf))
        # Relative OOS rank of the IS-best trial (1..N); average ranks break ties.
        omega = rankdata(oos_perf)[best_is] / (n_trials + 1)
        below += int(math.log(omega / (1.0 - omega)) <= 0.0)
        total += 1
    return below / total if total else float("nan")


def deflated_probability(observed: float, null: _F64, n_trials: int) -> float:
    """``F(observed)**n_trials`` — probability ``observed`` beats the best of ``n_trials`` draws.

    ``F`` is the empirical CDF of the single-trial null. Near 1 ⇒ the observed metric exceeds what
    ``n_trials`` null trials would produce by luck; low ⇒ indistinguishable from best-of-``K``
    noise. ``nan`` if the null is empty.
    """
    arr = np.asarray(null, dtype=np.float64)
    if arr.size == 0:
        return float("nan")
    f = float(np.mean(arr <= observed))
    return f**n_trials


def permutation_null(
    study: Study,
    dataset: pl.DataFrame,
    model: Model,
    *,
    feature_columns: list[str],
    h_bars: int,
    n_permutations: int,
    label_column: str = "label",
    seed: int = 0,
) -> _F64:
    """The single-trial AUC null: permute labels through the real splitter and rescore ``B`` times.

    Because the *same* ``PurgedCPCV`` + ``Study`` path that scores the model also generates the
    null, the null carries overlap, class balance, and purging by construction — nothing is
    modelled or mis-specified, and there is no effective-``n`` to estimate (ADR-0010 §3).
    """
    from qrp.validation.leakage import shuffle_labels

    nulls: list[float] = []
    for b in range(n_permutations):
        shuffled = shuffle_labels(dataset, seed=seed * 1_000_003 + b, label_column=label_column)
        result = study.run(
            shuffled,
            model,
            feature_columns=feature_columns,
            h_bars=h_bars,
            label_column=label_column,
        )
        if not math.isnan(result.auc):
            nulls.append(result.auc)
    return np.asarray(nulls, dtype=np.float64)


def block_bars_for_horizon(h_bars: int, *, multiple: int = 10) -> int:
    """Block length for the block-shuffle null, stated as a function of ``H`` (review 2026-07-15).

    The block must be **longer than the label autocorrelation decay** — which is on the order of the
    horizon ``H`` — or short blocks destroy the very structure they exist to preserve and the block
    shuffle degrades into a full shuffle in disguise (measured: at block ``= H`` the temporal
    adversary is *not* rejected, at ``10*H`` it is). Ten horizons is the validated default.
    """
    return multiple * h_bars


def permutation_null_block(
    study: Study,
    dataset: pl.DataFrame,
    model: Model,
    *,
    feature_columns: list[str],
    h_bars: int,
    n_permutations: int,
    block_bars: int,
    label_column: str = "label",
    seed: int = 0,
) -> _F64:
    """The AUC null under a **block** label shuffle — preserves within-block autocorrelation.

    Tested-but-**dormant** (ADR-0009 block-shuffle filing; ADR-0010). Unlike the full shuffle, this
    keeps the label autocorrelation *inside* each block of ``block_bars`` while breaking it across
    blocks, so a model that rides label temporal structure still scores high on the null (→
    rejected) while a genuine cross-sectional edge collapses on the null (→ passed). It has **no
    effect on a cross-sectional model** — any label shuffle breaks that model's feature→label tie —
    which is why it is inert for every Phase-3 model and only bites a sequence model. ``block_bars``
    must exceed the autocorrelation decay (see :func:`block_bars_for_horizon`).
    """
    from qrp.validation.leakage import shuffle_labels_block

    nulls: list[float] = []
    for b in range(n_permutations):
        shuffled = shuffle_labels_block(
            dataset, seed=seed * 1_000_003 + b, block_size=block_bars, label_column=label_column
        )
        result = study.run(
            shuffled,
            model,
            feature_columns=feature_columns,
            h_bars=h_bars,
            label_column=label_column,
        )
        if not math.isnan(result.auc):
            nulls.append(result.auc)
    return np.asarray(nulls, dtype=np.float64)


def auc_deflation(
    study: Study,
    dataset: pl.DataFrame,
    model: Model,
    *,
    observed_auc: float,
    n_trials: int,
    feature_columns: list[str],
    h_bars: int,
    n_permutations: int = 200,
    block_bars: int | None = None,
    label_column: str = "label",
    seed: int = 0,
) -> float:
    """Deflate ``observed_auc`` against a permutation null over ``n_trials`` trials (ADR-0010 §3).

    With ``block_bars=None`` (default) the null is the **full** label shuffle
    (:func:`permutation_null`) — the correct and complete guard for the cross-sectional models of
    Phase 3. Passing ``block_bars`` switches to the **block** shuffle
    (:func:`permutation_null_block`), the tested-but-dormant guard that only bites a model reading
    label temporal order (a sequence model); it is a no-op for cross-sectional models. Returns
    :func:`deflated_probability`. This is **not** a DSR — it is a deflation on the AUC statistic
    against its own measured null, not comparable to a Phase-5 returns-series DSR.
    """
    if block_bars is None:
        null = permutation_null(
            study,
            dataset,
            model,
            feature_columns=feature_columns,
            h_bars=h_bars,
            n_permutations=n_permutations,
            label_column=label_column,
            seed=seed,
        )
    else:
        null = permutation_null_block(
            study,
            dataset,
            model,
            feature_columns=feature_columns,
            h_bars=h_bars,
            n_permutations=n_permutations,
            block_bars=block_bars,
            label_column=label_column,
            seed=seed,
        )
    return deflated_probability(observed_auc, null, n_trials)
