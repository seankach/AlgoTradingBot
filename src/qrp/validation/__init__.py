"""Validation layer: cross-snapshot conflicts, session tagging, gap index, quality flags.

Enforces the §5 data contract on raw snapshots: retroactive re-adjustment is caught
(never silent), every bar is session-tagged, the session-time index is complete with an
``is_traded`` flag (no forward-fill), and gaps/halts/anomalies are recorded as data.
"""

from qrp.validation.conflicts import (
    SnapshotConflictError,
    assert_no_conflicts,
    find_conflicts,
)
from qrp.validation.quality import flag_quality
from qrp.validation.session_index import (
    attach_bars,
    bars_to_frame,
    build_session_index,
    validated_frame,
)
from qrp.validation.sessions import SessionTagger

__all__ = [
    "SessionTagger",
    "SnapshotConflictError",
    "assert_no_conflicts",
    "attach_bars",
    "bars_to_frame",
    "build_session_index",
    "find_conflicts",
    "flag_quality",
    "validated_frame",
]
