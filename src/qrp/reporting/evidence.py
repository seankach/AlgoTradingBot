"""Evidence reports over validated bars (the Stage B deliverables).

Produces the numbers Phase 2 needs to decide whether extended-hours trading is viable:
the earliest available timestamp, row counts by session, and the spread distribution by
session.

Spread is derived from ``BID_ASK`` bars using the documented IBKR convention (open =
time-average bid, close = time-average ask; OQ-5) — flagged as an assumption to confirm
against a live gateway.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

_SESSION_ORDER = ("RTH", "PRE", "POST", "OVERNIGHT")


def add_spread_columns(bid_ask_frame: pl.DataFrame) -> pl.DataFrame:
    """Add ``spread`` and ``spread_bps`` to a session-indexed BID_ASK frame (OQ-5).

    ``spread = ask - bid`` with ``bid = open``, ``ask = close``; ``spread_bps`` is relative
    to the midpoint. Untraded minutes yield null spreads.
    """
    bid = pl.col("open")
    ask = pl.col("close")
    midpoint = (bid + ask) / 2.0
    spread = ask - bid
    return bid_ask_frame.with_columns(
        spread=pl.when(pl.col("is_traded")).then(spread).otherwise(None),
        spread_bps=pl.when(pl.col("is_traded") & (midpoint > 0))
        .then(spread / midpoint * 10_000.0)
        .otherwise(None),
    )


def earliest_traded(frame: pl.DataFrame) -> datetime | None:
    """Return the earliest timestamp with an actual trade, or ``None`` if none."""
    traded = frame.filter(pl.col("is_traded"))
    if traded.height == 0:
        return None
    value = traded.get_column("ts_utc").min()
    assert value is None or isinstance(value, datetime)
    return value


def row_counts_by_session(frame: pl.DataFrame) -> dict[str, int]:
    """Return the count of traded bars per session label."""
    counts = frame.filter(pl.col("is_traded")).group_by("session").agg(pl.len().alias("n"))
    mapping = {row["session"]: int(row["n"]) for row in counts.iter_rows(named=True)}
    return {session: mapping.get(session, 0) for session in _SESSION_ORDER if session in mapping}


def spread_distribution_by_session(bid_ask_frame: pl.DataFrame) -> pl.DataFrame:
    """Return spread-in-bps distribution statistics per session.

    Columns: ``session, n, mean_bps, median_bps, p25_bps, p75_bps, p95_bps``.
    """
    frame = add_spread_columns(bid_ask_frame).filter(pl.col("spread_bps").is_not_null())
    stats = frame.group_by("session").agg(
        pl.len().alias("n"),
        pl.col("spread_bps").mean().alias("mean_bps"),
        pl.col("spread_bps").median().alias("median_bps"),
        pl.col("spread_bps").quantile(0.25).alias("p25_bps"),
        pl.col("spread_bps").quantile(0.75).alias("p75_bps"),
        pl.col("spread_bps").quantile(0.95).alias("p95_bps"),
    )
    order = pl.DataFrame({"session": list(_SESSION_ORDER)}).with_row_index("_ord")
    return stats.join(order, on="session", how="left").sort("_ord").drop("_ord")


def render_evidence(
    *,
    symbol: str,
    earliest_trades: datetime | None,
    earliest_bid_ask: datetime | None,
    trades_counts: dict[str, int],
    bid_ask_counts: dict[str, int],
    spread_stats: pl.DataFrame,
) -> str:
    """Render the evidence deliverables as a human-readable text block."""
    lines = [
        f"=== Ingestion evidence: {symbol} ===",
        "",
        "Discovered earliest 1-minute timestamp:",
        f"  TRADES : {earliest_trades.isoformat() if earliest_trades else 'unknown'}",
        f"  BID_ASK: {earliest_bid_ask.isoformat() if earliest_bid_ask else 'unknown'}",
        "",
        "Traded row counts by session (TRADES):",
    ]
    lines += [f"  {session:<9} {count:>12,}" for session, count in trades_counts.items()]
    lines += ["", "Traded row counts by session (BID_ASK):"]
    lines += [f"  {session:<9} {count:>12,}" for session, count in bid_ask_counts.items()]
    lines += ["", "Spread distribution by session (bps), from BID_ASK (OQ-5):"]
    lines.append(str(spread_stats))
    return "\n".join(lines)
