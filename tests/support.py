"""Shared test helpers: a known-good configuration and a writer for it.

Kept separate from ``conftest.py`` so it can be imported explicitly by test modules
without depending on pytest's plugin-loading order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# A known-good configuration, one entry per file. Tests mutate a single field and assert
# the loader/model rejects (or accepts) exactly that change.
VALID_CONFIG: dict[str, dict[str, Any]] = {
    "config": {"config_version": "test-1"},
    "ibkr": {
        "host": "127.0.0.1",
        "port": 7497,
        "client_id": 7,
        "request_timezone": "America/New_York",
    },
    "universe": {
        "symbols": [
            {"symbol": "TSLA", "primary_exchange": "NASDAQ"},
        ]
    },
    "session": {
        "ingest_sessions": ["PRE", "RTH", "POST", "OVERNIGHT"],
        "tradable_sessions": ["PRE", "RTH", "POST"],
    },
    "costs": {
        "version": "test-1",
        "commission": {
            "per_share_usd": 0.0035,
            "min_per_order_usd": 0.35,
            "max_percent_of_trade_value": 0.01,
            "exchange_regulatory_fees_bps": 0.2,
        },
        "spread_cross_fraction": 0.5,
        "fixed_impact_bps": 1.0,
        "cost_multipliers": [1.0, 2.0, 3.0],
    },
    "labels": {
        "version": "test-1",
        "method": "triple_barrier",
        "barrier_sigma_multiple_k": 2.0,
        "vertical_barrier_bars_h": 30,
        "volatility": {
            "method": "ewma",
            "window_bars": 60,
            "session_conditional": True,
        },
    },
    "storage": {"data_root": "./data"},
    "logging": {"level": "INFO", "renderer": "json"},
}


def write_config_dir(root: Path, sections: dict[str, dict[str, Any]]) -> Path:
    """Write ``sections`` as ``<name>.yaml`` files under ``root`` and return ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in sections.items():
        (root / f"{name}.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    return root
