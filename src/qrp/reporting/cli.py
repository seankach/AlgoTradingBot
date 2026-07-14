"""``python -m qrp.reporting`` — print the Stage B evidence from the snapshot lake.

Reads what has already been ingested (no gateway needed) and prints, per symbol: the
discovered earliest 1-minute timestamp, traded row counts by session, and the BID_ASK
spread distribution by session.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import polars as pl

from qrp.config import load_config
from qrp.domain.enums import WhatToShow
from qrp.infrastructure.storage import SnapshotStore
from qrp.reporting.build import assemble_validated
from qrp.reporting.evidence import (
    earliest_traded,
    render_evidence,
    row_counts_by_session,
    spread_distribution_by_session,
)
from qrp.validation.sessions import SessionTagger


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qrp.reporting", description="Print ingestion evidence.")
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Render the evidence report for every configured symbol."""
    args = _parse_args(argv)
    # Windows consoles default to cp1252; keep the report printable everywhere.
    pl.Config.set_ascii_tables(active=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = load_config(args.config)
    store = SnapshotStore(config.storage)
    tagger = SessionTagger()
    scope = [str(session) for session in config.session.ingest_sessions]

    for spec in config.universe.symbols:
        trades = assemble_validated(
            store,
            tagger,
            symbol=spec.symbol,
            what_to_show=WhatToShow.TRADES,
            sessions_included=scope,
        )
        bid_ask = assemble_validated(
            store,
            tagger,
            symbol=spec.symbol,
            what_to_show=WhatToShow.BID_ASK,
            sessions_included=scope,
        )
        report = render_evidence(
            symbol=spec.symbol,
            earliest_trades=None if trades.is_empty() else earliest_traded(trades),
            earliest_bid_ask=None if bid_ask.is_empty() else earliest_traded(bid_ask),
            trades_counts={} if trades.is_empty() else row_counts_by_session(trades),
            bid_ask_counts={} if bid_ask.is_empty() else row_counts_by_session(bid_ask),
            spread_stats=(
                bid_ask if bid_ask.is_empty() else spread_distribution_by_session(bid_ask)
            ),
        )
        print(report)  # stdout is the product of this report CLI

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
