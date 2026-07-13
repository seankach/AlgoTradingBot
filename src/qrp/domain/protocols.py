"""The broker-abstraction boundary: structural protocols (ADR-0002).

The research platform depends only on these protocols, never on a concrete broker.
Implementations live under ``infrastructure/brokers/<vendor>/`` and are the *only* place
a vendor SDK (``ib_async``) may be imported. A second broker is a second adapter that
satisfies the same protocols — nothing above this boundary changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar


@runtime_checkable
class MarketDataSource(Protocol):
    """Read-only historical market data, in broker-neutral terms.

    All datetimes are timezone-aware; returned bars are UTC with the timestamp marking
    the bar start (ADR-0004). The request timezone is pinned explicitly per call (§5)
    so behaviour never depends on a gateway's login timezone.
    """

    def earliest_available_timestamp(
        self,
        symbol: str,
        what_to_show: WhatToShow,
        *,
        bar_size: str,
    ) -> datetime | None:
        """Discover the earliest timestamp for which the source has data.

        Args:
            symbol: Instrument symbol (e.g. ``"TSLA"``).
            what_to_show: Series kind (depth differs between TRADES and BID_ASK).
            bar_size: Bar size string (e.g. ``"1 min"``).

        Returns:
            The earliest available timestamp in UTC, or ``None`` if the source cannot
            determine it. Depth is *discovered*, never assumed (§5).
        """
        ...

    def fetch_bars(
        self,
        symbol: str,
        *,
        start_utc: datetime,
        end_utc: datetime,
        what_to_show: WhatToShow,
        bar_size: str,
        use_rth: bool,
        request_timezone: str,
    ) -> list[Bar]:
        """Fetch bars whose start falls in ``[start_utc, end_utc)``.

        Args:
            symbol: Instrument symbol.
            start_utc: Inclusive window start (UTC, tz-aware).
            end_utc: Exclusive window end (UTC, tz-aware).
            what_to_show: Series kind.
            bar_size: Bar size string.
            use_rth: If ``False``, include pre/post/overnight bars (§5 ingests with
                ``useRTH=0`` so nothing is discarded).
            request_timezone: IANA timezone pinned on the request; results are returned
                in UTC regardless.

        Returns:
            Bars sorted ascending by ``ts_utc``. May be empty (a legitimate result
            outside RTH, or before available depth).
        """
        ...


@runtime_checkable
class Broker(Protocol):
    """Reserved order-execution boundary (Phase 5+).

    Declared to fix the boundary named in ADR-0002; intentionally has no members yet.
    Its methods are defined when the first real consumer exists — an abstraction is not
    implemented ahead of use (CLAUDE.md §10).
    """
