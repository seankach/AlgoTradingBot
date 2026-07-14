"""Point-in-time feature store (ADR-0006).

Features are computed through bar *t* by ``FeatureGenerator``s, then a single mandatory
1-bar lag makes each stored row at *t* depend only on bars ``<= t - 1min`` (I1). Deterministic
calendar features are exempt from the lag.
"""

from qrp.features.generators import (
    LaggedReturns,
    RangeVolatility,
    RelativeVolume,
    SessionConditionalEwmaVol,
    TimeOfDay,
)
from qrp.features.protocols import FeatureGenerator
from qrp.features.store import (
    FeatureBuildManifest,
    FeatureStore,
    build_and_store,
    build_features,
    default_generators,
)

__all__ = [
    "FeatureBuildManifest",
    "FeatureGenerator",
    "FeatureStore",
    "LaggedReturns",
    "RangeVolatility",
    "RelativeVolume",
    "SessionConditionalEwmaVol",
    "TimeOfDay",
    "build_and_store",
    "build_features",
    "default_generators",
]
