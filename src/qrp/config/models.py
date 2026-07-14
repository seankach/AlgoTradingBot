"""Pydantic v2 configuration models for the platform.

Design rules encoded here (CLAUDE.md §4, §9, invariants I4/I6):

* **No silent defaults for result-affecting values.** Any field whose value can
  change research output is *required* (no default). A missing key in YAML therefore
  fails at load time instead of silently substituting an assumption. Purely
  operational values that cannot alter results (log level, connection host) may carry
  defaults.
* **Immutable and typo-proof.** Every model is ``frozen`` and forbids unknown keys, so
  configuration cannot mutate after load and a misspelled key is an error, not a
  silently ignored no-op.
* **Validated at load, not at use.** Cross-field rules (e.g. tradable sessions must be
  a subset of ingested sessions) are enforced here so no downstream code has to.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from qrp.base import StrictModel as _Strict

_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


class Session(StrEnum):
    """Market-session label attached to every bar (CLAUDE.md §5).

    Ingestion runs with ``useRTH=0`` so all four are captured; the tradable subset is
    a config choice, never a hardcode.
    """

    PRE = "PRE"
    RTH = "RTH"
    POST = "POST"
    OVERNIGHT = "OVERNIGHT"


class IBKRConnectionConfig(_Strict):
    """Connection and pacing parameters for the IBKR gateway/TWS.

    Connection details are operational and may default. ``request_timezone`` is the
    exception: an unpinned or wrong timezone silently corrupts session tagging across
    DST boundaries (CLAUDE.md §5), so it is required and validated.
    """

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    account: str | None = None
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    read_only: bool = True
    request_timezone: str = Field(
        ...,
        description="IANA timezone pinned on every historical request (§5). "
        "Bars are converted to UTC on ingest.",
    )
    max_requests_per_10min: int = Field(default=60, gt=0)
    chunk_size_bars: int = Field(default=2000, gt=0)
    bid_ask_counts_double: bool = True

    @field_validator("request_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value


class SymbolSpec(_Strict):
    """A single tradable contract. Fields affecting contract resolution are required."""

    symbol: str = Field(..., min_length=1)
    sec_type: str = "STK"
    exchange: str = "SMART"
    primary_exchange: str = Field(..., min_length=1)
    currency: str = "USD"


class SymbolUniverseConfig(_Strict):
    """The set of instruments the platform trades. Phase 1: TSLA only."""

    symbols: list[SymbolSpec] = Field(..., min_length=1)

    @field_validator("symbols")
    @classmethod
    def _unique_symbols(cls, value: list[SymbolSpec]) -> list[SymbolSpec]:
        names = [spec.symbol for spec in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate symbols in universe: {duplicates}")
        return value


class SessionScopeConfig(_Strict):
    """Which sessions are ingested and which are tradable (CLAUDE.md §5).

    Both are required: the tradable set must be an explicit, versioned choice, never a
    hardcode or a silent default.
    """

    ingest_sessions: list[Session] = Field(..., min_length=1)
    tradable_sessions: list[Session] = Field(..., min_length=1)

    @field_validator("ingest_sessions", "tradable_sessions")
    @classmethod
    def _no_duplicate_sessions(cls, value: list[Session]) -> list[Session]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate session labels")
        return value

    @model_validator(mode="after")
    def _tradable_is_subset(self) -> SessionScopeConfig:
        extra = set(self.tradable_sessions) - set(self.ingest_sessions)
        if extra:
            names = sorted(session.value for session in extra)
            raise ValueError(f"tradable sessions must be ingested; not ingested: {names}")
        return self


class CommissionConfig(_Strict):
    """IBKR commission schedule. Read from config; never hardcoded (CLAUDE.md §8)."""

    per_share_usd: float = Field(..., ge=0)
    min_per_order_usd: float = Field(..., ge=0)
    max_percent_of_trade_value: float = Field(..., ge=0, le=1)
    exchange_regulatory_fees_bps: float = Field(..., ge=0)


class CostModelConfig(_Strict):
    """Frozen cost model (invariant I4). Every field affects results, so all are required.

    ``version`` participates in the ``dataset_id`` hash; changing any cost invalidates
    prior results and must be surfaced as such (CLAUDE.md §8).
    """

    version: str = Field(..., min_length=1)
    commission: CommissionConfig
    spread_cross_fraction: float = Field(..., ge=0, le=1)
    fixed_impact_bps: float = Field(..., ge=0)
    cost_multipliers: list[float] = Field(..., min_length=1)

    @field_validator("cost_multipliers")
    @classmethod
    def _requires_1_2_3(cls, value: list[float]) -> list[float]:
        required = {1.0, 2.0, 3.0}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"cost_multipliers must include 1x/2x/3x (§8); missing {missing}")
        return value


class VolatilityEstimatorConfig(_Strict):
    """Causal, time-of-day-bucketed EWMA volatility for the barriers (ADR-0007; §6).

    For a bar, sigma is the EWMA (over **past days**) of the realized variance of the same
    intraday bucket, so open-hour and midday have separate estimators (§6). Shared by the
    barrier and the ``ewma_vol`` feature (I3).
    """

    method: Literal["time_of_day_ewma"]
    bucket_minutes: int = Field(..., gt=0)
    ewma_span_days: int = Field(..., gt=1)


class LabelSpecConfig(_Strict):
    """Triple-barrier label specification (default). The barriers ARE the strategy (I3).

    Purge and embargo are derived from the horizon downstream and are deliberately not
    configurable here (CLAUDE.md §6, §7). ``version`` feeds the ``dataset_id`` hash.
    """

    version: str = Field(..., min_length=1)
    method: Literal["triple_barrier", "fixed_horizon_direction", "fixed_horizon_magnitude"]
    barrier_sigma_multiple_k: float = Field(..., gt=0)
    vertical_barrier_bars_h: int = Field(..., gt=0)
    volatility: VolatilityEstimatorConfig


class FeatureSpecConfig(_Strict):
    """Versioned feature specification (ADR-0006). ``version`` feeds the ``dataset_id`` hash.

    The session-conditional EWMA volatility feature reuses ``LabelSpecConfig.volatility`` so
    features and the barrier that defines the strategy share one estimator (I3). Windows are
    frozen here; nothing is tuned.
    """

    version: str = Field(..., min_length=1)
    return_horizons_min: list[int] = Field(..., min_length=1)
    range_vol_window_min: int = Field(..., gt=1)
    relative_volume_window_min: int = Field(..., gt=1)

    @field_validator("return_horizons_min")
    @classmethod
    def _positive_unique_horizons(cls, value: list[int]) -> list[int]:
        if any(h <= 0 for h in value):
            raise ValueError("return horizons must be positive minutes")
        if len(set(value)) != len(value):
            raise ValueError("duplicate return horizons")
        return value


class StoragePathsConfig(_Strict):
    """Filesystem layout of the Parquet lake and registry artifacts.

    Paths locate data but do not change it, so subdirectory names may default; the
    root is required so the location is always an explicit choice.
    """

    data_root: Path
    raw_snapshots_subdir: str = "raw_snapshots"
    validated_bars_subdir: str = "validated_bars"
    features_subdir: str = "features"
    labels_subdir: str = "labels"
    manifests_subdir: str = "manifests"
    duckdb_subpath: str = "catalog/qrp.duckdb"

    @property
    def raw_snapshots_dir(self) -> Path:
        """Root of the immutable raw-snapshot Parquet lake (partitioned symbol/date)."""
        return self.data_root / self.raw_snapshots_subdir

    @property
    def validated_bars_dir(self) -> Path:
        """Root of the validated, session-tagged bar lake."""
        return self.data_root / self.validated_bars_subdir

    @property
    def features_dir(self) -> Path:
        """Root of the point-in-time feature lake (ADR-0006)."""
        return self.data_root / self.features_subdir

    @property
    def labels_dir(self) -> Path:
        """Root of the derived label lake (ADR-0007)."""
        return self.data_root / self.labels_subdir

    @property
    def manifests_dir(self) -> Path:
        """Directory holding dataset/snapshot manifests."""
        return self.data_root / self.manifests_subdir

    @property
    def duckdb_path(self) -> Path:
        """Path to the DuckDB catalog file (query layer, not storage)."""
        return self.data_root / self.duckdb_subpath


class LoggingConfig(_Strict):
    """Structured-logging configuration. Operational; not result-affecting."""

    level: str = "INFO"
    renderer: Literal["json", "console"] = "json"

    @field_validator("level")
    @classmethod
    def _valid_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in _LOG_LEVELS:
            raise ValueError(f"invalid log level {value!r}; expected one of {sorted(_LOG_LEVELS)}")
        return upper


class AppConfig(_Strict):
    """Top-level, fully-validated platform configuration.

    Assembled by :func:`qrp.config.loader.load_config` from one YAML file per section.
    """

    config_version: str = Field(..., min_length=1)
    ibkr: IBKRConnectionConfig
    universe: SymbolUniverseConfig
    session: SessionScopeConfig
    costs: CostModelConfig
    labels: LabelSpecConfig
    features: FeatureSpecConfig
    storage: StoragePathsConfig
    logging: LoggingConfig
