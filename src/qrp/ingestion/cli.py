"""Command-line entrypoint for ingestion (requires a live IB gateway).

Usage:
    uv run python -m qrp.ingestion --config config --mode auto

Modes:
    backfill  — ingest full available history for every symbol/series.
    update    — ingest only the tail since the last stored bar (daily incremental).
    auto      — update where prior snapshots exist, else backfill (default).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from qrp.config import load_config
from qrp.domain.enums import WhatToShow
from qrp.infrastructure.brokers.ibkr import IBKRMarketDataSource
from qrp.infrastructure.storage import SnapshotStore
from qrp.ingestion.orchestrator import Ingestor
from qrp.observability.logging import configure_logging, get_logger

_log = get_logger(__name__)
_SERIES = (WhatToShow.TRADES, WhatToShow.BID_ASK)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qrp.ingestion", description="Ingest IBKR bars.")
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    parser.add_argument(
        "--mode",
        choices=("backfill", "update", "auto"),
        default="auto",
        help="Ingestion mode (default: auto).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion for every configured symbol and both series."""
    args = _parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)

    source = IBKRMarketDataSource(config.ibkr, config.universe.symbols)
    store = SnapshotStore(config.storage)
    ingestor = Ingestor(
        source,
        store,
        request_timezone=config.ibkr.request_timezone,
        depth_dir=config.storage.manifests_dir / "depth",
    )

    with source.connected():
        for spec in config.universe.symbols:
            for series in _SERIES:
                has_history = store_has_history(store, spec.symbol, series)
                use_update = args.mode == "update" or (args.mode == "auto" and has_history)
                if use_update:
                    ingestor.incremental(spec.symbol, series)
                else:
                    ingestor.backfill(spec.symbol, series)
    _log.info("ingest.cli.done", mode=args.mode)
    return 0


def store_has_history(store: SnapshotStore, symbol: str, what_to_show: WhatToShow) -> bool:
    """Return whether any snapshot already exists for this symbol/series."""
    return any(
        manifest.symbol == symbol and manifest.what_to_show == what_to_show
        for manifest in store.list_manifests()
    )


if __name__ == "__main__":
    raise SystemExit(main())
