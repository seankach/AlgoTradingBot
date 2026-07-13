"""Unit tests for the configuration models: required fields, validators, immutability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qrp.config.models import (
    CommissionConfig,
    CostModelConfig,
    IBKRConnectionConfig,
    LoggingConfig,
    Session,
    SessionScopeConfig,
    SymbolUniverseConfig,
)


def _commission() -> CommissionConfig:
    return CommissionConfig(
        per_share_usd=0.0035,
        min_per_order_usd=0.35,
        max_percent_of_trade_value=0.01,
        exchange_regulatory_fees_bps=0.2,
    )


class TestNoSilentDefaults:
    def test_request_timezone_is_required(self) -> None:
        with pytest.raises(ValidationError):
            IBKRConnectionConfig()  # type: ignore[call-arg]

    def test_invalid_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IBKRConnectionConfig(request_timezone="Mars/Olympus_Mons")

    def test_cost_version_is_required(self) -> None:
        with pytest.raises(ValidationError):
            CostModelConfig(  # type: ignore[call-arg]
                commission=_commission(),
                spread_cross_fraction=0.5,
                fixed_impact_bps=1.0,
                cost_multipliers=[1.0, 2.0, 3.0],
            )


class TestValidators:
    def test_cost_multipliers_require_1_2_3(self) -> None:
        with pytest.raises(ValidationError, match="1x/2x/3x"):
            CostModelConfig(
                version="v",
                commission=_commission(),
                spread_cross_fraction=0.5,
                fixed_impact_bps=1.0,
                cost_multipliers=[1.0, 2.0],
            )

    def test_tradable_must_be_subset_of_ingested(self) -> None:
        with pytest.raises(ValidationError, match="tradable sessions must be ingested"):
            SessionScopeConfig(
                ingest_sessions=[Session.RTH],
                tradable_sessions=[Session.RTH, Session.PRE],
            )

    def test_duplicate_symbols_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate symbols"):
            SymbolUniverseConfig(
                symbols=[
                    {"symbol": "TSLA", "primary_exchange": "NASDAQ"},  # type: ignore[list-item]
                    {"symbol": "TSLA", "primary_exchange": "NASDAQ"},  # type: ignore[list-item]
                ]
            )

    def test_log_level_normalised_and_validated(self) -> None:
        assert LoggingConfig(level="info").level == "INFO"
        with pytest.raises(ValidationError):
            LoggingConfig(level="LOUD")


class TestStrictness:
    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IBKRConnectionConfig(request_timezone="America/New_York", typo_field=1)  # type: ignore[call-arg]

    def test_models_are_frozen(self) -> None:
        cfg = IBKRConnectionConfig(request_timezone="America/New_York")
        with pytest.raises(ValidationError):
            cfg.host = "10.0.0.1"  # type: ignore[misc]
