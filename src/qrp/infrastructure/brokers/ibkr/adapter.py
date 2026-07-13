"""IBKR ``MarketDataSource`` adapter, built on ``ib_async`` (ADR-0002).

This is the **only** module in the platform permitted to import ``ib_async`` (enforced by
the import-linter contract in ``pyproject.toml``). It translates the broker-neutral
:class:`~qrp.domain.protocols.MarketDataSource` interface into IBKR historical-data calls,
enforces pacing by construction (§5), pins the request timezone, and returns UTC bars whose
timestamp marks the bar start (ADR-0004).

Live IBKR behaviours that this code assumes but which can only be confirmed against a real
gateway are collected in ``docs/ibkr-open-questions.md`` and referenced inline as ``OQ-n``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from ib_async import IB, BarData, Contract, Stock

from qrp.config.models import IBKRConnectionConfig, SymbolSpec
from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.infrastructure.brokers.ibkr.pacing import PacingLimiter
from qrp.observability.logging import get_logger

_log = get_logger(__name__)

_PACING_WINDOW_SECONDS = 600.0
_MAX_REQUEST_RETRIES = 5
_BACKOFF_BASE_SECONDS = 2.0
# Per-request history duration by bar size. Conservative so no single request is rejected
# for exceeding IBKR's per-request bar cap (OQ-3).
_DURATION_BY_BAR_SIZE: Mapping[str, str] = {"1 min": "1 D"}
_DEFAULT_DURATION = "1 D"
# Depth-probe: stride forward from the head-timestamp anchor looking for the first 1-min
# data (OQ-1). Bounded so the loop always terminates.
_PROBE_STRIDE = timedelta(days=30)
_MAX_PROBE_STEPS = 500


class IBClient(Protocol):
    """The narrow slice of ``ib_async.IB`` this adapter depends on (injected for tests).

    Method and argument names mirror ``ib_async`` exactly so the real client satisfies
    this protocol structurally.
    """

    def connect(
        self, host: str, port: int, clientId: int, timeout: float, readonly: bool
    ) -> object:
        """Open a gateway connection."""

    def disconnect(self) -> object:
        """Close the gateway connection."""

    def isConnected(self) -> bool:
        """Return whether the client is currently connected."""

    def qualifyContracts(self, *contracts: Contract) -> list[Contract]:
        """Resolve ambiguous contracts to fully-specified ones."""

    def reqHeadTimeStamp(
        self, contract: Contract, whatToShow: str, useRTH: bool, formatDate: int
    ) -> datetime:
        """Return the earliest available data timestamp for the contract/series."""

    def reqHistoricalData(
        self,
        contract: Contract,
        endDateTime: datetime | str | None,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
    ) -> Sequence[BarData]:
        """Return historical bars ending at ``endDateTime`` spanning ``durationStr``."""


def _bar_from_ibkr(raw: BarData, request_timezone: str) -> Bar:
    """Convert an ``ib_async`` ``BarData`` to a neutral UTC :class:`Bar`.

    ``formatDate=2`` is requested so IBKR returns UTC (OQ-2); if a naive datetime arrives
    anyway it is localised with the pinned request timezone rather than assumed UTC.
    """
    raw_date = raw.date
    if not isinstance(raw_date, datetime):
        raise TypeError(f"expected intraday datetime bar, got {type(raw_date).__name__}")
    ts = (
        raw_date.replace(tzinfo=ZoneInfo(request_timezone)) if raw_date.tzinfo is None else raw_date
    ).astimezone(UTC)
    return Bar(
        ts_utc=ts,
        open=float(raw.open),
        high=float(raw.high),
        low=float(raw.low),
        close=float(raw.close),
        volume=float(raw.volume),
        bar_count=int(raw.barCount),
        wap=float(raw.average),
    )


class IBKRMarketDataSource:
    """Concrete :class:`~qrp.domain.protocols.MarketDataSource` backed by IBKR.

    Contract:
        Every historical request passes through a :class:`PacingLimiter` (BID_ASK counts
        double, §5) and a bounded exponential backoff. Timezone is pinned per request and
        results are UTC. Depth is discovered, never hardcoded (§5).

    Failure modes:
        ``KeyError`` for an unknown symbol; ``RuntimeError`` if a request keeps failing
        past the retry budget.
    """

    def __init__(
        self,
        config: IBKRConnectionConfig,
        symbols: Sequence[SymbolSpec],
        *,
        client: IBClient | None = None,
        limiter: PacingLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._symbols = {spec.symbol: spec for spec in symbols}
        self._client: IBClient = client if client is not None else IB()
        self._limiter = limiter or PacingLimiter(
            config.max_requests_per_10min, _PACING_WINDOW_SECONDS
        )
        self._sleep = sleep
        self._contracts: dict[str, Contract] = {}

    # -- connection -------------------------------------------------------------------

    @contextmanager
    def connected(self) -> Iterator[IBKRMarketDataSource]:
        """Open an IBKR session for the duration of the ``with`` block."""
        self._client.connect(
            self._config.host,
            self._config.port,
            self._config.client_id,
            self._config.connect_timeout_seconds,
            self._config.read_only,
        )
        _log.info("ibkr.connected", host=self._config.host, port=self._config.port)
        try:
            yield self
        finally:
            self._client.disconnect()
            _log.info("ibkr.disconnected")

    # -- helpers ----------------------------------------------------------------------

    def _weight(self, what_to_show: WhatToShow) -> int:
        double = what_to_show is WhatToShow.BID_ASK and self._config.bid_ask_counts_double
        return 2 if double else 1

    def _contract(self, symbol: str) -> Contract:
        cached = self._contracts.get(symbol)
        if cached is not None:
            return cached
        spec = self._symbols.get(symbol)
        if spec is None:
            raise KeyError(f"symbol {symbol!r} is not in the configured universe")
        stock = Stock(
            spec.symbol, spec.exchange, spec.currency, primaryExchange=spec.primary_exchange
        )
        qualified = self._client.qualifyContracts(stock)
        if not qualified:
            raise RuntimeError(f"IBKR could not qualify contract for {symbol!r}")
        self._contracts[symbol] = qualified[0]
        return qualified[0]

    @staticmethod
    def _duration_for(bar_size: str) -> str:
        return _DURATION_BY_BAR_SIZE.get(bar_size, _DEFAULT_DURATION)

    def _request_chunk(
        self,
        contract: Contract,
        *,
        end_utc: datetime,
        bar_size: str,
        what_to_show: WhatToShow,
        use_rth: bool,
        request_timezone: str,
    ) -> list[Bar]:
        """Issue one paced historical request with bounded exponential backoff."""
        weight = self._weight(what_to_show)
        last_error: Exception | None = None
        for attempt in range(_MAX_REQUEST_RETRIES):
            self._limiter.acquire(weight)
            try:
                raw = self._client.reqHistoricalData(
                    contract,
                    endDateTime=end_utc,
                    durationStr=self._duration_for(bar_size),
                    barSizeSetting=bar_size,
                    whatToShow=str(what_to_show),
                    useRTH=use_rth,
                    formatDate=2,
                )
            except Exception as exc:  # IBKR error surface is broad; retry/backoff (OQ-4)
                last_error = exc
                backoff = _BACKOFF_BASE_SECONDS**attempt
                _log.warning(
                    "ibkr.request.retry",
                    attempt=attempt + 1,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                self._sleep(backoff)
                continue
            return [_bar_from_ibkr(bar, request_timezone) for bar in raw]
        raise RuntimeError(
            f"historical request failed after {_MAX_REQUEST_RETRIES} attempts"
        ) from last_error

    # -- MarketDataSource --------------------------------------------------------------

    def earliest_available_timestamp(
        self, symbol: str, what_to_show: WhatToShow, *, bar_size: str
    ) -> datetime | None:
        """Discover the true earliest 1-min timestamp (hybrid probe, OQ-1).

        Phase 1 (anchor + forward-find): ``reqHeadTimeStamp`` gives a coarse lower bound
        (it can be earlier than real 1-min availability); stride forward from it until a
        real 1-min chunk comes back non-empty. Phase 2 (backward-pin): walk backward from
        that chunk one page at a time until a request returns empty — the last non-empty
        earliest bar is the true floor. Both phases are bounded, so the probe terminates.
        """
        contract = self._contract(symbol)
        request_tz = self._config.request_timezone
        now = datetime.now(UTC)

        try:
            head = self._client.reqHeadTimeStamp(
                contract, whatToShow=str(what_to_show), useRTH=False, formatDate=2
            )
        except Exception as exc:  # no head stamp is a valid "unknown" outcome (OQ-1)
            _log.warning("ibkr.head_timestamp.unavailable", symbol=symbol, error=str(exc))
            head = None

        if head is not None:
            anchor = (head if head.tzinfo is not None else head.replace(tzinfo=UTC)).astimezone(UTC)
        else:
            anchor = now - _PROBE_STRIDE

        # Phase 1: forward-find the first non-empty chunk.
        found: list[Bar] = []
        cursor = anchor
        for _ in range(_MAX_PROBE_STEPS):
            window_end = min(cursor + _PROBE_STRIDE, now)
            chunk = self._request_chunk(
                contract,
                end_utc=window_end,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=False,
                request_timezone=request_tz,
            )
            if chunk:
                found = chunk
                break
            if window_end >= now:
                return None
            cursor = window_end
        if not found:
            return None

        # Phase 2: backward-pin the true earliest bar.
        earliest = min(bar.ts_utc for bar in found)
        for _ in range(_MAX_PROBE_STEPS):
            chunk = self._request_chunk(
                contract,
                end_utc=earliest,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=False,
                request_timezone=request_tz,
            )
            if not chunk:
                break
            chunk_earliest = min(bar.ts_utc for bar in chunk)
            if chunk_earliest >= earliest:
                break
            earliest = chunk_earliest

        _log.info(
            "ibkr.depth.discovered",
            symbol=symbol,
            what_to_show=str(what_to_show),
            earliest=earliest.isoformat(),
        )
        return earliest

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
        """Fetch bars whose start falls in ``[start_utc, end_utc)``, chunking backward.

        Requests walk backward from ``end_utc`` (IBKR pages by ``endDateTime`` + duration)
        until the window is covered or a chunk comes back empty (before available depth).
        """
        if start_utc >= end_utc:
            return []
        contract = self._contract(symbol)
        collected: dict[datetime, Bar] = {}
        cursor = end_utc
        for _ in range(_MAX_PROBE_STEPS):
            chunk = self._request_chunk(
                contract,
                end_utc=cursor,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
                request_timezone=request_timezone,
            )
            if not chunk:
                break
            for bar in chunk:
                if start_utc <= bar.ts_utc < end_utc:
                    collected[bar.ts_utc] = bar
            earliest = min(bar.ts_utc for bar in chunk)
            if earliest <= start_utc or earliest >= cursor:
                break
            cursor = earliest
        return [collected[key] for key in sorted(collected)]
