"""Command-line entrypoint for ingestion (requires a live IB gateway).

Usage:
    uv run python -m qrp.ingestion --config config --mode auto

Modes:
    backfill  — ingest full available history for every symbol/series (resumable).
    update    — ingest only the tail since the last stored bar (daily incremental).
    auto      — same as backfill; it resumes from the frontier (default).
    status    — no gateway; exit 0 if every series has caught up to ~now, else 1.

A long IBKR backfill can be killed when the gateway drops the API socket. Because
ingestion is resumable and idempotent, the supported pattern for an unattended run is a
supervisor that re-runs ``auto`` until ``status`` reports complete (see
``run_ingest_until_done.ps1``).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import timedelta

from qrp.config import load_config
from qrp.config.models import AppConfig
from qrp.domain.enums import WhatToShow
from qrp.infrastructure.brokers.ibkr import IBKRMarketDataSource
from qrp.infrastructure.storage import SnapshotStore
from qrp.ingestion.orchestrator import Ingestor
from qrp.observability.logging import configure_logging, get_logger

_log = get_logger(__name__)
_SERIES = (WhatToShow.TRADES, WhatToShow.BID_ASK)
# A caught-up backfill's last bar trails the wall clock by the non-trading gap; four days
# absorbs a long weekend so "status" does not report a completed run as still pending.
_STATUS_TOLERANCE = timedelta(days=4)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qrp.ingestion", description="Ingest IBKR bars.")
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    parser.add_argument(
        "--mode",
        choices=("backfill", "update", "auto", "status"),
        default="auto",
        help="Ingestion mode (default: auto).",
    )
    return parser.parse_args(argv)


def _status(ingestor: Ingestor, config: AppConfig) -> int:
    """Exit 0 only if every symbol/series has data within ``_STATUS_TOLERANCE`` of now."""
    pending = [
        f"{spec.symbol}/{series}"
        for spec in config.universe.symbols
        for series in _SERIES
        if not ingestor.is_complete(spec.symbol, series, tolerance=_STATUS_TOLERANCE)
    ]
    if pending:
        _log.info("ingest.status.incomplete", pending=pending)
        return 1
    _log.info("ingest.status.complete")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion (or report status) for every configured symbol and both series."""
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

    if args.mode == "status":
        return _status(ingestor, config)

    try:
        with source.connected():
            for spec in config.universe.symbols:
                for series in _SERIES:
                    if args.mode == "update":
                        ingestor.incremental(spec.symbol, series)
                    else:
                        # backfill/auto: resumes from the frontier, so it both fills
                        # history and picks up a daily tail as a one-window run.
                        ingestor.backfill(spec.symbol, series)
    except Exception:
        # A dropped gateway surfaces here as a connection error; log it and exit non-zero
        # so a supervisor re-runs (the resume is gap-free). Uncatchable hard kills are
        # handled by the same supervisor at the process level.
        _log.error("ingest.cli.failed", exc_info=True)
        return 1
    _log.info("ingest.cli.done", mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
