"""Triple-barrier labelling (§6, ADR-0007). The label is the exit policy (I3)."""

from qrp.labels.protocols import LabelGenerator
from qrp.labels.store import LabelBuildManifest, LabelStore, build_and_store
from qrp.labels.triple_barrier import TripleBarrier

__all__ = [
    "LabelBuildManifest",
    "LabelGenerator",
    "LabelStore",
    "TripleBarrier",
    "build_and_store",
]
