"""Adapter tests against a synthetic IBKR client — never a live gateway (§9).

The fake generates a contiguous 1-minute series in ``[data_start, data_end)`` on demand
(per request window), so an arbitrarily wide history costs nothing to model. Its
``reqHeadTimeStamp`` deliberately returns a stamp *earlier* than the true 1-min floor, to
exercise the hybrid probe's forward-find + backward-pin (OQ-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from ib_async import BarData

from qrp.config.models import IBKRConnectionConfig, SymbolSpec
from qrp.domain.enums import WhatToShow
from qrp.infrastructure.brokers.ibkr.adapter import IBKRMarketDataSource, _bar_from_ibkr
from qrp.infrastructure.brokers.ibkr.pacing import PacingLimiter

_TZ = "America/New_York"


@dataclass
class FakeBar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    average: float
    barCount: int


@dataclass
class FakeIB:
    data_start: datetime
    data_end: datetime
    head_stamp: datetime | None
    connected: bool = False
    request_ends: list[datetime] = field(default_factory=list)

    def connect(
        self,
        host: str,
        port: int,
        clientId: int,
        timeout: float,
        readonly: bool,
    ) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    def qualifyContracts(self, *contracts: object) -> list[object]:
        return list(contracts)

    def reqHeadTimeStamp(
        self,
        contract: object,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
    ) -> datetime:
        if self.head_stamp is None:
            raise ValueError("no head timestamp")
        return self.head_stamp

    def reqHistoricalData(
        self,
        contract: object,
        endDateTime: datetime,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
    ) -> list[FakeBar]:
        self.request_ends.append(endDateTime)
        days = int(durationStr.split()[0])
        window_start = endDateTime - timedelta(days=days)
        bars: list[FakeBar] = []
        cur = max(window_start, self.data_start)
        stop = min(endDateTime, self.data_end)
        while cur < stop:
            bars.append(FakeBar(cur, 1.0, 1.5, 0.5, 1.2, 100.0, 1.1, 10))
            cur += timedelta(minutes=1)
        return bars


def _config() -> IBKRConnectionConfig:
    return IBKRConnectionConfig(request_timezone=_TZ, max_requests_per_10min=60)


def _source(fake: FakeIB, **kwargs: object) -> IBKRMarketDataSource:
    symbols = [SymbolSpec(symbol="TSLA", primary_exchange="NASDAQ")]
    # Large pacing budget + no-op sleep so tests never actually wait.
    limiter = PacingLimiter(10_000, 600.0, clock=lambda: 0.0, sleep=lambda _s: None)
    return IBKRMarketDataSource(_config(), symbols, client=fake, limiter=limiter, **kwargs)  # type: ignore[arg-type]


def test_bar_conversion_passthrough_and_localise() -> None:
    aware = BarData(date=datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
    assert _bar_from_ibkr(aware, _TZ).ts_utc == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    naive = BarData(date=datetime(2024, 1, 2, 9, 30))
    # 09:30 America/New_York (EST, -05:00) == 14:30 UTC
    assert _bar_from_ibkr(naive, _TZ).ts_utc == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def test_depth_probe_pins_true_earliest_despite_early_head() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    data_start = now - timedelta(days=400)
    fake = FakeIB(
        data_start=data_start,
        data_end=now,
        head_stamp=data_start - timedelta(days=45),  # earlier than true 1-min floor
    )
    source = _source(fake)
    earliest = source.earliest_available_timestamp("TSLA", WhatToShow.TRADES, bar_size="1 min")
    assert earliest == data_start


def test_depth_probe_returns_none_when_no_data() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    fake = FakeIB(data_start=now, data_end=now, head_stamp=now - timedelta(days=10))
    assert (
        _source(fake).earliest_available_timestamp("TSLA", WhatToShow.TRADES, bar_size="1 min")
        is None
    )


def test_fetch_bars_returns_sorted_window_only() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    data_start = now - timedelta(days=400)
    fake = FakeIB(data_start=data_start, data_end=now, head_stamp=None)
    source = _source(fake)

    start = data_start + timedelta(days=100)
    end = start + timedelta(days=2)
    bars = source.fetch_bars(
        "TSLA",
        start_utc=start,
        end_utc=end,
        what_to_show=WhatToShow.TRADES,
        bar_size="1 min",
        use_rth=False,
        request_timezone=_TZ,
    )
    assert bars[0].ts_utc == start
    assert bars[-1].ts_utc == end - timedelta(minutes=1)
    assert bars == sorted(bars, key=lambda b: b.ts_utc)
    assert len(bars) == 2 * 24 * 60  # two full days of continuous minutes


def test_unknown_symbol_raises() -> None:
    fake = FakeIB(datetime.now(UTC), datetime.now(UTC), None)
    with pytest.raises(KeyError, match="not in the configured universe"):
        _source(fake).fetch_bars(
            "AAPL",
            start_utc=datetime.now(UTC) - timedelta(days=1),
            end_utc=datetime.now(UTC),
            what_to_show=WhatToShow.TRADES,
            bar_size="1 min",
            use_rth=False,
            request_timezone=_TZ,
        )


def test_bid_ask_acquires_double_weight() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    fake = FakeIB(now - timedelta(days=2), now, None)
    weights: list[int] = []

    class RecordingLimiter(PacingLimiter):
        def acquire(self, weight: int) -> float:
            weights.append(weight)
            return 0.0

    source = IBKRMarketDataSource(
        _config(),
        [SymbolSpec(symbol="TSLA", primary_exchange="NASDAQ")],
        client=fake,  # type: ignore[arg-type]
        limiter=RecordingLimiter(60, 600.0),
    )
    source.fetch_bars(
        "TSLA",
        start_utc=now - timedelta(minutes=30),
        end_utc=now,
        what_to_show=WhatToShow.BID_ASK,
        bar_size="1 min",
        use_rth=False,
        request_timezone=_TZ,
    )
    assert weights and all(w == 2 for w in weights)


def test_request_retries_with_backoff_then_succeeds() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    class FlakyIB(FakeIB):
        fail_once: bool = True

        def reqHistoricalData(self, *args: object, **kwargs: object) -> list[FakeBar]:
            if self.fail_once:
                self.fail_once = False
                raise ConnectionError("transient")
            return super().reqHistoricalData(*args, **kwargs)  # type: ignore[arg-type]

    fake = FlakyIB(now - timedelta(minutes=10), now, None)
    slept: list[float] = []
    source = _source(fake, sleep=slept.append)
    bars = source.fetch_bars(
        "TSLA",
        start_utc=now - timedelta(minutes=5),
        end_utc=now,
        what_to_show=WhatToShow.TRADES,
        bar_size="1 min",
        use_rth=False,
        request_timezone=_TZ,
    )
    assert slept == [1.0]  # one backoff of _BACKOFF_BASE_SECONDS ** 0
    assert len(bars) == 5


def test_connected_context_manager_opens_and_closes() -> None:
    fake = FakeIB(datetime.now(UTC), datetime.now(UTC), None)
    source = _source(fake)
    assert not fake.connected
    with source.connected():
        assert fake.connected
    assert not fake.connected
