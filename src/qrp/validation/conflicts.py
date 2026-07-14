"""Cross-snapshot conflict detection (§5, ADR-0003; invariant I2).

IBKR retroactively rewrites `TRADES` history after each split. Because snapshots are
immutable and content-addressed, a re-adjusted pull is stored as a *new* snapshot rather
than overwriting the old one. This module compares overlapping timestamps across snapshots
of the same symbol/series and surfaces disagreements — so a silent retroactive rewrite
becomes a loud, inspectable event rather than corrupting research.

Recent bars near the ingestion frontier legitimately change between fetches while they are
still settling (late prints/quotes in thin sessions; the incomplete last bar, §5). Those
are **not** re-adjustments, so callers pass ``settled_before`` to restrict the check to
bars old enough to be final (ADR-0005).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import polars as pl

_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "bar_count", "wap")


class SnapshotConflictError(Exception):
    """Raised when two snapshots disagree on the values of an overlapping bar."""


def find_conflicts(
    frames: Sequence[pl.DataFrame], *, settled_before: datetime | None = None
) -> pl.DataFrame:
    """Return the rows where snapshots disagree on an overlapping timestamp.

    Args:
        frames: Snapshot frames for the **same** symbol and series, each carrying at least
            ``ts_utc`` and the value columns.
        settled_before: If given, only bars with ``ts_utc < settled_before`` are compared,
            so still-settling frontier bars are excluded from re-adjustment detection.

    Returns:
        A frame with one row per conflicting ``ts_utc`` and, for each value column, the
        count of distinct values observed (``> 1`` means disagreement). Empty if the
        snapshots are mutually consistent on their (settled) overlap.
    """
    if len(frames) < 2:
        return pl.DataFrame({"ts_utc": []}, schema={"ts_utc": pl.Datetime("us", "UTC")})

    combined = pl.concat([frame.select("ts_utc", *_VALUE_COLUMNS) for frame in frames])
    if settled_before is not None:
        combined = combined.filter(pl.col("ts_utc") < settled_before)
    distinct_counts = combined.group_by("ts_utc").agg(
        pl.col(column).n_unique().alias(column) for column in _VALUE_COLUMNS
    )
    conflict_mask = pl.any_horizontal(pl.col(column) > 1 for column in _VALUE_COLUMNS)
    return distinct_counts.filter(conflict_mask).sort("ts_utc")


def assert_no_conflicts(
    frames: Sequence[pl.DataFrame], *, settled_before: datetime | None = None
) -> None:
    """Raise :class:`SnapshotConflictError` if any settled overlapping bars disagree.

    Raises:
        SnapshotConflictError: With the count and first few conflicting timestamps.
    """
    conflicts = find_conflicts(frames, settled_before=settled_before)
    if conflicts.height == 0:
        return
    sample = conflicts.get_column("ts_utc").to_list()[:5]
    raise SnapshotConflictError(
        f"{conflicts.height} overlapping timestamps disagree across snapshots "
        f"(retroactive re-adjustment?); first: {sample}"
    )
