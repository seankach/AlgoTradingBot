"""Assemble validated frames from the snapshot lake for reporting.

Reads every snapshot for a symbol/series, checks cross-snapshot consistency (raising on a
retroactive re-adjustment, §5), unions the bars, and runs the validation pipeline (session
tagging, complete index, quality flags).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import polars as pl

from qrp.domain.enums import WhatToShow
from qrp.infrastructure.storage.snapshots import SnapshotStore
from qrp.validation.conflicts import assert_no_conflicts
from qrp.validation.quality import flag_quality
from qrp.validation.session_index import attach_bars, build_session_index
from qrp.validation.sessions import SessionTagger


def load_series_frames(
    store: SnapshotStore, symbol: str, what_to_show: WhatToShow
) -> list[pl.DataFrame]:
    """Read every snapshot frame for a symbol/series."""
    return [
        store.read_snapshot(manifest)
        for manifest in store.list_manifests()
        if manifest.symbol == symbol and manifest.what_to_show == what_to_show
    ]


def assemble_validated(
    store: SnapshotStore,
    tagger: SessionTagger,
    *,
    symbol: str,
    what_to_show: WhatToShow,
    sessions_included: Sequence[str],
) -> pl.DataFrame:
    """Return the session-tagged, gap-complete, quality-flagged frame for a series.

    Raises:
        SnapshotConflictError: If overlapping snapshots disagree (§5, ADR-0003).
    """
    frames = load_series_frames(store, symbol, what_to_show)
    if not frames:
        return pl.DataFrame()
    assert_no_conflicts(frames)

    combined = pl.concat(frames).unique(subset="ts_utc", keep="first").sort("ts_utc")
    start = combined.get_column("ts_utc").min()
    end = combined.get_column("ts_utc").max()
    assert isinstance(start, datetime)
    assert isinstance(end, datetime)

    index = build_session_index(start, end + timedelta(minutes=1), sessions_included, tagger)
    attached = attach_bars(index, combined)
    return flag_quality(attached)
