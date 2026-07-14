"""Research dataset: features aligned to labels, addressed by a reproducible dataset_id.

See ADR-0003 for the versioning scheme and invariant I6 (reproducibility).
"""

from qrp.dataset.manifest import DatasetManifest, compute_dataset_id, git_head_sha
from qrp.dataset.store import DatasetStore, assemble_dataset, build_and_store

__all__ = [
    "DatasetManifest",
    "DatasetStore",
    "assemble_dataset",
    "build_and_store",
    "compute_dataset_id",
    "git_head_sha",
]
