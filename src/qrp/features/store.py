"""Feature composition, the point-in-time lag, and the feature lake (ADR-0006).

``build_features`` runs each generator (which computes *through* bar t) over the **traded**
series, then applies the **single mandatory 1-bar lag** so every stored market feature at t
reflects only bars ``<=`` the previous *traded* bar (I1, ADR-0004/0008). Deterministic
(calendar) features are exempt. The feature lake is derived (regenerable, like validated bars
— I2 governs raw only) and stamps ``feature_spec_version`` for the ``dataset_id`` hash
(ADR-0003).
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import polars as pl

from qrp.base import StrictModel
from qrp.config.models import FeatureSpecConfig, StoragePathsConfig, VolatilityEstimatorConfig
from qrp.features.generators import (
    _SESSION_DATE,
    BarrierVolatility,
    LaggedReturns,
    RangeVolatility,
    RelativeVolume,
    TimeOfDay,
)
from qrp.features.protocols import ContextFeatureGenerator, FeatureGenerator
from qrp.observability.logging import get_logger

_log = get_logger(__name__)
_LAG_BARS = 1  # single mandatory point-in-time lag: row t reflects bars <= previous traded bar
_PARQUET_NAME = "features.parquet"
_MANIFEST_NAME = "_build.json"
_KEEP = ("ts_utc", "session", "is_traded")
# The aligned context bar's TRUE stamp, carried through the as-of join so a generator can see how
# stale its context is (ADR-0013 §5a: stale context nulls the feature, never drops the row).
_CTX_TS = "_ctx_ts"


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
        LaggedReturns(horizons_bars=tuple(features.return_horizons_bars)),
        BarrierVolatility(
            bucket_minutes=volatility.bucket_minutes,
            ewma_span_days=volatility.ewma_span_days,
            timezone=timezone,
        ),
        RangeVolatility(window_bars=features.range_vol_window_bars),
        RelativeVolume(window_bars=features.relative_volume_window_bars),
        TimeOfDay(timezone=timezone),
    ]


def _wants_context(generator: object) -> bool:
    """Whether a generator's ``generate`` takes the aligned ``context`` (ADR-0013).

    Dispatch is by signature, not ``isinstance``: both protocols are ``runtime_checkable`` and
    structurally identical apart from ``generate``, and runtime protocol checks only verify method
    *presence*, never signatures — so ``isinstance`` would match both and silently mis-dispatch.
    """
    generate = getattr(generator, "generate", None)
    if generate is None:
        return False
    return "context" in inspect.signature(generate).parameters


def _align_context(
    target: pl.DataFrame, context: Mapping[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Row-align each context symbol to the target's traded bars, as-of ``ts <= t`` (ADR-0013 §2).

    The **store** owns this join so no generator can construct it — a dangerous join belongs to
    the framework, not the thing being tested (the ADR-0011 principle). Alignment is an as-of
    *backward* join over the context's own **traded** series (ADR-0008), so it respects that SPY's
    halts are not TSLA's and never pairs a padded minute. Where the context has no prior bar the
    row is **null** (stale/absent), never dropped — dropping would couple the target's sample set
    to context liquidity, a selection effect (ADR-0013 §5a). ``_ctx_ts`` carries the context bar's
    true stamp so staleness is observable.

    The result is aligned as-of *t* (concurrent allowed) **on purpose**: the store's single
    mandatory lag then carries the PIT contract for target and context alike — one tested path.
    """
    target_ts = target.select("ts_utc")
    aligned: dict[str, pl.DataFrame] = {}
    for symbol, frame in context.items():
        ctx = (
            frame.filter(pl.col("is_traded"))
            .sort("ts_utc")
            .with_columns(pl.col("ts_utc").alias(_CTX_TS))
        )
        aligned[symbol] = target_ts.join_asof(ctx, on="ts_utc", strategy="backward")
    return aligned


def build_features(
    validated: pl.DataFrame,
    generators: Sequence[FeatureGenerator | ContextFeatureGenerator],
    *,
    timezone: str,
    context: Mapping[str, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    """Compose generator outputs and apply the point-in-time lag.

    Returns ``ts_utc, session, is_traded`` plus the (lagged) feature columns. Empty in →
    empty out. ``context`` (symbol -> validated frame) is aligned by :func:`_align_context` and
    handed to context-aware generators; the same single lag then governs it (ADR-0013).
    """
    if validated.is_empty():
        return pl.DataFrame()

    # Event-based (ADR-0008): compute and lag over the TRADED series so "previous bar" means
    # the previous traded *event*, never a padded-grid minute. Decisions/labels only exist on
    # traded bars, so nothing is lost.
    frame = (
        validated.filter(pl.col("is_traded"))
        .sort("ts_utc")
        .with_columns(
            pl.col("ts_utc").dt.convert_time_zone(timezone).dt.date().alias(_SESSION_DATE)
        )
    )
    if frame.is_empty():
        return pl.DataFrame()

    aligned = _align_context(frame, context) if context else {}
    result = frame.select(*_KEEP, _SESSION_DATE)
    market_columns: list[str] = []
    for generator in generators:
        produced = (
            generator.generate(frame, aligned)  # type: ignore[call-arg]
            if _wants_context(generator)
            else generator.generate(frame)  # type: ignore[call-arg]
        )
        result = result.join(produced, on="ts_utc", how="left")
        if not generator.is_deterministic:
            market_columns.extend(generator.output_columns)

    if market_columns:
        # Single mandatory point-in-time lag: row t reflects only bars <= previous traded bar.
        result = result.with_columns(
            pl.col(column).shift(_LAG_BARS).over(_SESSION_DATE).alias(column)
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
