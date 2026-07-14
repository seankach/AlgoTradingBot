"""Validation layer: cross-snapshot conflicts, session tagging, gap index, quality flags.

Enforces the §5 data contract on raw snapshots: retroactive re-adjustment is caught
(never silent), every bar is session-tagged, the session-time index is complete with an
``is_traded`` flag (no forward-fill), and gaps/halts/anomalies are recorded as data.
"""

from qrp.validation.assemble import assemble_validated, load_series_frames
from qrp.validation.conflicts import (
    SnapshotConflictError,
    assert_no_conflicts,
    find_conflicts,
)
from qrp.validation.lake import (
    ValidatedBarStore,
    ValidatedBuildManifest,
    build_and_store,
    build_validated_bars,
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
    "ValidatedBarStore",
    "ValidatedBuildManifest",
    "assemble_validated",
    "assert_no_conflicts",
    "attach_bars",
    "bars_to_frame",
    "build_and_store",
    "build_session_index",
    "build_validated_bars",
    "find_conflicts",
    "flag_quality",
    "load_series_frames",
    "validated_frame",
]
