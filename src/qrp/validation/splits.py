"""Purged, embargoed combinatorial cross-validation (CPCV) — ADR-0009, build step 1.

Train/test index sets derived from the **label lifespans** (``entry_ts``/``exit_ts``), never
from a separate config, so purge/embargo cannot disagree with the labels (§7):

* **Purge** removes any train sample whose lifespan overlaps a test fold's lifespan span.
* **Embargo** additionally removes the ``embargo`` train samples immediately following a test
  fold, where ``embargo = max(H, ceil(embargo_pct * n))`` (H is the LabelSpec vertical barrier).

The splitter assumes the input labels are sorted ascending by ``decision_ts`` (the ``Study``
sorts before splitting), so contiguous index blocks are contiguous in time.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import numpy.typing as npt
import polars as pl

_I64 = npt.NDArray[np.int64]
_Bool = npt.NDArray[np.bool_]


def group_bounds(n: int, n_groups: int) -> list[int]:
    """Return the ``n_groups + 1`` index boundaries of contiguous, near-equal groups."""
    return [(g * n) // n_groups for g in range(n_groups + 1)]


def _contiguous_runs(sorted_groups: Sequence[int], bounds: Sequence[int]) -> list[tuple[int, int]]:
    """Merge adjacent test groups into contiguous ``[lo, hi)`` index runs."""
    runs: list[tuple[int, int]] = []
    for g in sorted_groups:
        lo, hi = bounds[g], bounds[g + 1]
        if runs and runs[-1][1] == lo:
            runs[-1] = (runs[-1][0], hi)
        else:
            runs.append((lo, hi))
    return runs


def purged_train_mask(
    entry_us: _I64,
    exit_us: _I64,
    test_group_ids: Sequence[int],
    bounds: Sequence[int],
    *,
    embargo: int,
) -> _Bool:
    """Return the boolean train mask after removing test, purged, and embargoed samples.

    A train sample is purged if its ``[entry_us, exit_us]`` overlaps a test run's span
    ``[min entry, max exit]`` (closed intervals: a lifespan ending exactly at the test span's
    start is purged; ending one bar before is kept). Embargo drops the ``embargo`` samples
    immediately after each test run.
    """
    n = entry_us.shape[0]
    test_mask = np.zeros(n, dtype=bool)
    for g in test_group_ids:
        test_mask[bounds[g] : bounds[g + 1]] = True
    train_mask = ~test_mask

    for run_lo, run_hi in _contiguous_runs(sorted(test_group_ids), bounds):
        span_entry = int(entry_us[run_lo:run_hi].min())
        span_exit = int(exit_us[run_lo:run_hi].max())
        overlaps = (entry_us <= span_exit) & (exit_us >= span_entry)
        train_mask &= ~overlaps
        train_mask[run_hi : min(run_hi + embargo, n)] = False
    return train_mask


@dataclass(frozen=True)
class PurgedCPCV:
    """Combinatorial purged CV: ``C(n_groups, k_test_groups)`` splits (ADR-0009)."""

    n_groups: int
    k_test_groups: int
    embargo_pct: float = 0.01

    def split(self, labels: pl.DataFrame, *, h_bars: int) -> Iterator[tuple[_I64, _I64]]:
        """Yield ``(train_idx, test_idx)`` index arrays for each test-group combination.

        Args:
            labels: Sorted-by-``decision_ts`` frame with ``entry_ts`` and ``exit_ts``.
            h_bars: The LabelSpec vertical-barrier horizon (feeds the embargo).
        """
        n = labels.height
        entry = labels.get_column("entry_ts").dt.epoch(time_unit="us").to_numpy().astype(np.int64)
        exit_ = labels.get_column("exit_ts").dt.epoch(time_unit="us").to_numpy().astype(np.int64)
        bounds = group_bounds(n, self.n_groups)
        embargo = max(h_bars, math.ceil(self.embargo_pct * n))

        for test_groups in combinations(range(self.n_groups), self.k_test_groups):
            train_mask = purged_train_mask(entry, exit_, test_groups, bounds, embargo=embargo)
            test_mask = np.zeros(n, dtype=bool)
            for g in test_groups:
                test_mask[bounds[g] : bounds[g + 1]] = True
            yield np.nonzero(train_mask)[0], np.nonzero(test_mask)[0]
