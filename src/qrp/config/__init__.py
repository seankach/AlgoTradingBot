"""Configuration subsystem: Pydantic v2 models plus a YAML directory loader.

Public surface: :func:`load_config` and the model types. Configuration is validated
at load and immutable thereafter (CLAUDE.md §4, §9).
"""

from qrp.config.loader import ConfigError, load_config
from qrp.config.models import (
    AppConfig,
    CommissionConfig,
    CostModelConfig,
    IBKRConnectionConfig,
    LabelSpecConfig,
    LoggingConfig,
    Session,
    SessionScopeConfig,
    StoragePathsConfig,
    SymbolSpec,
    SymbolUniverseConfig,
    VolatilityEstimatorConfig,
)

__all__ = [
    "AppConfig",
    "CommissionConfig",
    "ConfigError",
    "CostModelConfig",
    "IBKRConnectionConfig",
    "LabelSpecConfig",
    "LoggingConfig",
    "Session",
    "SessionScopeConfig",
    "StoragePathsConfig",
    "SymbolSpec",
    "SymbolUniverseConfig",
    "VolatilityEstimatorConfig",
    "load_config",
]
