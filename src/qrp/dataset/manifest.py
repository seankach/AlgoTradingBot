"""Dataset identity and provenance (ADR-0003; invariant I6).

``dataset_id = hash{raw_snapshot_ids, feature_spec_version, label_spec_version,
cost_model_version, git_sha}`` — so any reported result traces deterministically to the
exact raw data, specs, costs, and code that produced it. A ``DatasetManifest`` records the
full expansion behind each id.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Sequence
from datetime import datetime

from qrp.base import StrictModel

_ID_LENGTH = 16


class DatasetManifest(StrictModel):
    """The full expansion behind one ``dataset_id`` (persisted as JSON)."""

    dataset_id: str
    symbol: str
    built_at_utc: datetime
    git_sha: str
    bar_spec_version: str
    feature_spec_version: str
    label_spec_version: str
    cost_model_version: str
    raw_snapshot_ids: list[str]
    feature_columns: list[str]
    row_count: int


def compute_dataset_id(
    *,
    raw_snapshot_ids: Sequence[str],
    bar_spec_version: str,
    feature_spec_version: str,
    label_spec_version: str,
    cost_model_version: str,
    git_sha: str,
) -> str:
    """Return the content hash that identifies a research dataset (ADR-0003/0008).

    Deterministic: raw snapshot ids are sorted so ordering cannot change the id.
    ``bar_spec_version`` is included so datasets on different samplers cannot collide.
    """
    parts = [
        "raw:" + ",".join(sorted(raw_snapshot_ids)),
        "bar:" + bar_spec_version,
        "feature:" + feature_spec_version,
        "label:" + label_spec_version,
        "cost:" + cost_model_version,
        "git:" + git_sha,
    ]
    digest = hashlib.sha256("\n".join(parts).encode())
    return digest.hexdigest()[:_ID_LENGTH]


def git_head_sha() -> str:
    """Return the current git HEAD sha (with a ``-dirty`` suffix if the tree is modified).

    A dirty tree is not reproducible, so it deliberately changes the ``dataset_id``.
    Returns ``"unknown"`` if git is unavailable.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
