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
from qrp.validation.leakage import (
    LeakageError,
    assert_features_are_not_outcomes,
    shuffle_labels,
    shuffle_labels_block,
    shuffle_time_order,
)
from qrp.validation.lockbox import (
    InMemoryLockboxStore,
    Lockbox,
    LockboxBurnedError,
    LockboxError,
    LockboxStore,
    LockboxTouch,
    PostgresLockboxStore,
)
from qrp.validation.quality import flag_quality
from qrp.validation.session_index import (
    attach_bars,
    bars_to_frame,
    build_session_index,
    validated_frame,
)
from qrp.validation.sessions import SessionTagger
from qrp.validation.splits import PurgedCPCV, purged_train_mask
from qrp.validation.study import CorrelationSignModel, Model, Study, StudyResult

__all__ = [
    "CorrelationSignModel",
    "InMemoryLockboxStore",
    "LeakageError",
    "Lockbox",
    "LockboxBurnedError",
    "LockboxError",
    "LockboxStore",
    "LockboxTouch",
    "Model",
    "PostgresLockboxStore",
    "PurgedCPCV",
    "SessionTagger",
    "SnapshotConflictError",
    "Study",
    "StudyResult",
    "ValidatedBarStore",
    "ValidatedBuildManifest",
    "assemble_validated",
    "assert_features_are_not_outcomes",
    "assert_no_conflicts",
    "attach_bars",
    "bars_to_frame",
    "build_and_store",
    "build_session_index",
    "build_validated_bars",
    "find_conflicts",
    "flag_quality",
    "load_series_frames",
    "purged_train_mask",
    "shuffle_labels",
    "shuffle_labels_block",
    "shuffle_time_order",
    "validated_frame",
]
