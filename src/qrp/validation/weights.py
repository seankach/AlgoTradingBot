"""Sample-uniqueness weights from label concurrency (CLAUDE.md §7; López de Prado).

With ``H = 30`` consecutive labels' outcome windows overlap heavily, so row count wildly overstates
the effective sample size. The weight of a label is its **average uniqueness**: over the bars its
outcome window spans, the mean of ``1 / concurrency``, where concurrency at a bar is how many
labels' windows cover it. A label that never overlaps another weighs 1; one sharing every bar
with ``c`` others weighs ``~1/c``. Derived from the ``entry_ts``/``exit_ts`` lifespans the
framework already owns — never configured independently — so it cannot disagree with the purge.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

_F64 = npt.NDArray[np.float64]
_I64 = npt.NDArray[np.int64]


def uniqueness_weights(decision_us: _I64, entry_us: _I64, exit_us: _I64) -> _F64:
    """Average-uniqueness weight per label, normalised to mean 1 (CLAUDE.md §7).

    Args:
        decision_us: sorted-ascending decision timestamps (microseconds) — the bar grid.
        entry_us: label entry timestamps (start of each outcome window).
        exit_us: label exit timestamps (end of each outcome window).

    Returns:
        One weight per label. Bars are located on the ``decision_us`` grid (so gaps and session
        breaks are handled: a window spans only bars that exist), concurrency is a difference-array
        cumulative sum, and uniqueness integrates ``1/concurrency`` over each window via a prefix.
        A non-overlapping label weighs 1; ``sum(weights)`` is the **effective sample size** (< ``n``
        whenever labels overlap). Raw uniqueness is returned, not a normalised weight — only ratios
        matter downstream (both the fit loss and the weighted AUC are scale-free).
    """
    n = decision_us.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    # Each label covers the bars [start, end] on the decision grid (inclusive).
    start = np.clip(np.searchsorted(decision_us, entry_us, side="left"), 0, n - 1)
    end = np.clip(np.searchsorted(decision_us, exit_us, side="right") - 1, 0, n - 1)
    end = np.maximum(end, start)  # a window covers at least its own bar

    # Concurrency at each bar: +1 when a window starts, -1 just after it ends, then cumulative sum.
    diff = np.zeros(n + 1, dtype=np.float64)
    np.add.at(diff, start, 1.0)
    np.add.at(diff, end + 1, -1.0)
    concurrency = np.maximum(np.cumsum(diff[:-1]), 1.0)

    # Average of 1/concurrency over each window via a prefix sum of the per-bar inverse.
    inv = 1.0 / concurrency
    prefix = np.concatenate([[0.0], np.cumsum(inv)])
    span = (end - start + 1).astype(np.float64)
    weights: _F64 = (prefix[end + 1] - prefix[start]) / span
    return weights
