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
from qrp.validation.overfitting import (
    DEFAULT_PBO_BLOCKS,
    auc_deflation,
    block_bars_for_horizon,
    deflated_probability,
    pbo,
    permutation_null,
    permutation_null_block,
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
from qrp.validation.study import (
    CorrelationSignModel,
    FitValidation,
    Model,
    Study,
    StudyResult,
)
from qrp.validation.trials import (
    TRIALS_DDL,
    InMemoryTrialStore,
    PostgresTrialStore,
    Trial,
    TrialSpec,
    TrialStore,
    trial_hash,
)
from qrp.validation.weights import uniqueness_weights

__all__ = [
    "DEFAULT_PBO_BLOCKS",
    "TRIALS_DDL",
    "CorrelationSignModel",
    "FitValidation",
    "InMemoryLockboxStore",
    "InMemoryTrialStore",
    "LeakageError",
    "Lockbox",
    "LockboxBurnedError",
    "LockboxError",
    "LockboxStore",
    "LockboxTouch",
    "Model",
    "PostgresLockboxStore",
    "PostgresTrialStore",
    "PurgedCPCV",
    "SessionTagger",
    "SnapshotConflictError",
    "Study",
    "StudyResult",
    "Trial",
    "TrialSpec",
    "TrialStore",
    "ValidatedBarStore",
    "ValidatedBuildManifest",
    "assemble_validated",
    "assert_features_are_not_outcomes",
    "assert_no_conflicts",
    "attach_bars",
    "auc_deflation",
    "bars_to_frame",
    "block_bars_for_horizon",
    "build_and_store",
    "build_session_index",
    "build_validated_bars",
    "deflated_probability",
    "find_conflicts",
    "flag_quality",
    "load_series_frames",
    "pbo",
    "permutation_null",
    "permutation_null_block",
    "purged_train_mask",
    "shuffle_labels",
    "shuffle_labels_block",
    "shuffle_time_order",
    "trial_hash",
    "uniqueness_weights",
    "validated_frame",
]
