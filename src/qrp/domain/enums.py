"""Broker-neutral enumerations used across the domain boundary (ADR-0002)."""

from __future__ import annotations

from enum import StrEnum


class WhatToShow(StrEnum):
    """The kind of historical series requested.

    ``TRADES`` is split-adjusted last-trade OHLCV (CLAUDE.md §5). ``BID_ASK`` returns
    quote aggregates used for the measured spread cost model (§8); note that IBKR maps
    BID_ASK into the OHLC fields by convention (open=time-avg bid, high=max ask,
    low=min bid, close=time-avg ask) and that BID_ASK requests count double against
    pacing (§5).
    """

    TRADES = "TRADES"
    BID_ASK = "BID_ASK"
