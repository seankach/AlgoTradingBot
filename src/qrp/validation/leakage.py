"""Leakage-suite primitives (ADR-0009, build step 4): structural guards + shuffle operations.

These are *code, not vigilance* (§7). Each is placed at the layer its target leak enters (the
layering principle in ADR-0009): a leak is detectable only by a test operating at or above the
layer where it enters, so we do not chase an upstream leak with a downstream test.

* :func:`assert_features_are_not_outcomes` — the label/outcome boundary guard (§7-b). An outcome
  column is realised only at ``exit_ts`` (after the decision), so using one as a feature is a
  point-in-time violation by construction. Wired into ``Study.run`` so it fires at the choke point.
* :func:`shuffle_labels` — a **full** random permutation of the label column (§7-d). Breaks every
  X↔y correspondence, so a model's out-of-fold AUC must return to ~0.5. A full permutation (not a
  block/structure-preserving one) is required: it collapses even a *frozen* look-ahead leak on
  autocorrelated labels to chance, because decoupling the label from the frozen feature destroys
  the correlation regardless of the label's own autocorrelation.
* :func:`shuffle_time_order` — reassigns the temporal coordinates to rows, keeping each X↔y pair
  intact (§7-d, the **dormant tripwire**). A no-op for AUC while the stack is frozen-feature +
  memoryless (any row permutation preserves the (Xᵢ, yᵢ) multiset); a *non-null* result is the
  alarm that a cross-sample dependency has entered the model class (Phase 3+).
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import polars as pl

# Columns realised at/after the label's exit (I3): known only after the decision, never features.
OUTCOME_COLUMNS: frozenset[str] = frozenset(
    {"label", "gross_return", "touched", "exit_ts", "exit_price", "entry_ts", "entry_price"}
)

_TS_COLUMNS = ("decision_ts", "entry_ts", "exit_ts")


class LeakageError(ValueError):
    """Raised when a structural leakage guard is violated."""


def assert_features_are_not_outcomes(
    feature_columns: Iterable[str],
    *,
    outcome_columns: frozenset[str] = OUTCOME_COLUMNS,
) -> None:
    """Raise if any requested feature column is a label/outcome column (§7-b).

    An outcome is only observable at ``exit_ts`` (after ``decision_ts``), so scoring it as a
    feature is look-ahead by construction. This is a *structural* check on names, not a
    performance one — magnitude cannot distinguish a leaked outcome from a real edge (ADR-0009).
    """
    leaked = sorted(set(feature_columns) & outcome_columns)
    if leaked:
        raise LeakageError(
            f"outcome columns used as features (realised only at exit, I3): {leaked}"
        )


def shuffle_labels(
    dataset: pl.DataFrame, *, seed: int, label_column: str = "label"
) -> pl.DataFrame:
    """Return ``dataset`` with the label column fully randomly permuted (§7-d label shuffle)."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(dataset.height)
    return dataset.with_columns(dataset.get_column(label_column)[perm].alias(label_column))


def shuffle_time_order(dataset: pl.DataFrame, *, seed: int) -> pl.DataFrame:
    """Return ``dataset`` with temporal coordinates reassigned to rows (§7-d time-order shuffle).

    Each row keeps its features and label; only the ``decision_ts``/``entry_ts``/``exit_ts`` triple
    is permuted across rows, scrambling the sequence while preserving every X↔y pair. Dormant
    tripwire — see the module docstring and ADR-0009.
    """
    rng = np.random.default_rng(seed)
    perm = rng.permutation(dataset.height)
    ts_perm = dataset.select(_TS_COLUMNS)[perm]
    return dataset.with_columns(ts_perm.get_column(c) for c in _TS_COLUMNS)
