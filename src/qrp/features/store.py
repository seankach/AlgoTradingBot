"""Feature composition, the point-in-time lag, and the feature lake (ADR-0006).

``build_features`` runs each generator (which computes *through* bar t), then applies the
**single mandatory 1-bar lag** so every stored market feature at t reflects only bars
``<= t - 1min`` (I1, ADR-0004). Deterministic (calendar) features are exempt. The feature
lake is derived (regenerable, like validated bars — I2 governs raw only) and stamps
``feature_spec_version`` for the ``dataset_id`` hash (ADR-0003).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from qrp.base import StrictModel
from qrp.config.models import FeatureSpecConfig, StoragePathsConfig, VolatilityEstimatorConfig
from qrp.features.generators import (
    _SESSION_DATE,
    LaggedReturns,
    RangeVolatility,
    RelativeVolume,
    SessionConditionalEwmaVol,
    TimeOfDay,
)
from qrp.features.protocols import FeatureGenerator
from qrp.observability.logging import get_logger

_log = get_logger(__name__)
_LAG_MIN = 1  # single mandatory point-in-time lag: row t reflects bars <= t-1min (ADR-0006)
_PARQUET_NAME = "features.parquet"
_MANIFEST_NAME = "_build.json"
_KEEP = ("ts_utc", "session", "is_traded")


class FeatureBuildManifest(StrictModel):
    """Provenance for one symbol's feature build (persisted as JSON)."""

    symbol: str
    built_at_utc: datetime
    feature_spec_version: str
    feature_columns: list[str]
    row_count: int


def default_generators(
    features: FeatureSpecConfig,
    volatility: VolatilityEstimatorConfig,
    *,
    timezone: str,
) -> list[FeatureGenerator]:
    """Construct the v1 generator set (ADR-0006) from config.

    The EWMA volatility generator reuses ``volatility`` (from the label spec) so features and
    the barrier share one estimator (I3).
    """
    return [
        LaggedReturns(horizons_min=tuple(features.return_horizons_min)),
        SessionConditionalEwmaVol(
            span_bars=volatility.window_bars,
            session_conditional=volatility.session_conditional,
        ),
        RangeVolatility(window_min=features.range_vol_window_min),
        RelativeVolume(window_min=features.relative_volume_window_min),
        TimeOfDay(timezone=timezone),
    ]


def build_features(
    validated: pl.DataFrame,
    generators: Sequence[FeatureGenerator],
    *,
    timezone: str,
) -> pl.DataFrame:
    """Compose generator outputs and apply the point-in-time lag.

    Returns ``ts_utc, session, is_traded`` plus the (lagged) feature columns. Empty in →
    empty out.
    """
    if validated.is_empty():
        return pl.DataFrame()

    frame = validated.sort("ts_utc").with_columns(
        pl.col("ts_utc").dt.convert_time_zone(timezone).dt.date().alias(_SESSION_DATE)
    )
    result = frame.select(*_KEEP, _SESSION_DATE)
    market_columns: list[str] = []
    for generator in generators:
        result = result.join(generator.generate(frame), on="ts_utc", how="left")
        if not generator.is_deterministic:
            market_columns.extend(generator.output_columns)

    if market_columns:
        result = result.with_columns(
            pl.col(column).shift(_LAG_MIN).over(_SESSION_DATE).alias(column)
            for column in market_columns
        )
    return result.drop(_SESSION_DATE).sort("ts_utc")


class FeatureStore:
    """Reads and writes the derived point-in-time feature lake."""

    def __init__(self, paths: StoragePathsConfig) -> None:
        self._root = paths.features_dir

    def write(self, symbol: str, frame: pl.DataFrame) -> int:
        """Write ``frame`` partitioned by UTC date, overwriting any prior build."""
        dated = frame.with_columns(pl.col("ts_utc").dt.date().alias("_date"))
        written = 0
        for (date_val,), group in dated.group_by(["_date"], maintain_order=True):
            partition_dir = self._root / f"symbol={symbol}" / f"date={date_val}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            group.drop("_date").write_parquet(partition_dir / _PARQUET_NAME)
            written += group.height
        return written

    def write_manifest(self, manifest: FeatureBuildManifest) -> None:
        """Persist the build manifest for a symbol."""
        symbol_dir = self._root / f"symbol={manifest.symbol}"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        (symbol_dir / _MANIFEST_NAME).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

    def read(self, symbol: str) -> pl.DataFrame:
        """Read the full feature frame for ``symbol`` (empty if not built)."""
        files = sorted((self._root / f"symbol={symbol}").glob(f"date=*/{_PARQUET_NAME}"))
        if not files:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(path) for path in files]).sort("ts_utc")

    def read_manifest(self, symbol: str) -> FeatureBuildManifest | None:
        """Read the build manifest for ``symbol`` (``None`` if not built)."""
        path = self._root / f"symbol={symbol}" / _MANIFEST_NAME
        if not path.is_file():
            return None
        return FeatureBuildManifest.model_validate_json(path.read_text(encoding="utf-8"))


def build_and_store(
    validated: pl.DataFrame,
    store: FeatureStore,
    generators: Sequence[FeatureGenerator],
    *,
    symbol: str,
    feature_spec_version: str,
    timezone: str,
) -> FeatureBuildManifest | None:
    """Build features for a symbol from its validated frame, persist them, return the manifest.

    Returns ``None`` if ``validated`` is empty.
    """
    frame = build_features(validated, generators, timezone=timezone)
    if frame.is_empty():
        _log.warning("features.build.no_data", symbol=symbol)
        return None

    rows = store.write(symbol, frame)
    feature_columns = [c for c in frame.columns if c not in _KEEP]
    manifest = FeatureBuildManifest(
        symbol=symbol,
        built_at_utc=datetime.now(UTC),
        feature_spec_version=feature_spec_version,
        feature_columns=feature_columns,
        row_count=rows,
    )
    store.write_manifest(manifest)
    _log.info(
        "features.build.done",
        symbol=symbol,
        rows=rows,
        features=len(feature_columns),
        spec_version=feature_spec_version,
    )
    return manifest
