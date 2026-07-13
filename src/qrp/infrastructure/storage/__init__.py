"""Storage layer: the immutable, content-addressed Parquet lake (ADR-0001, ADR-0003)."""

from qrp.infrastructure.storage.snapshots import (
    SnapshotManifest,
    SnapshotStore,
    compute_snapshot_id,
)

__all__ = ["SnapshotManifest", "SnapshotStore", "compute_snapshot_id"]
