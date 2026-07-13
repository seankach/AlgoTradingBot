"""Broker-neutral domain models that cross the ``MarketDataSource`` boundary (ADR-0002).

No vendor (``ib_async``) type ever appears here. Every timestamp is timezone-aware and
in UTC, and marks the **bar start** (ADR-0004): the bar stamped ``t`` covers
``[t, t + bar_size)`` and is not complete until its end.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import field_validator

from qrp.base import StrictModel


def _to_utc(value: datetime, field_name: str) -> datetime:
    """Normalise a timezone-aware datetime to UTC; raise if it is naive.

    A naive datetime is rejected loudly rather than assumed to be in some timezone
    (that assumption is exactly the DST trap in CLAUDE.md §5). An aware datetime in any
    zone is converted to UTC — the offset is explicit in the input, so this is a
    normalisation, not a silent default.
    """
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware (UTC)")
    return value.astimezone(UTC)


class Bar(StrictModel):
    """A single OHLCV bar in the platform's neutral representation.

    Contract:
        ``ts_utc`` is the bar's **start** in UTC (ADR-0004). For ``TRADES`` the OHLCV
        fields are last-trade prices and IBKR-view volume; for ``BID_ASK`` they carry
        quote aggregates (see :class:`~qrp.domain.enums.WhatToShow`). ``bar_count`` and
        ``wap`` are ``-1`` when the vendor does not populate them (e.g. for BID_ASK).

    Failure modes:
        Rejects naive or non-UTC ``ts_utc``, and any unknown field.
    """

    ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_count: int
    wap: float

    @field_validator("ts_utc")
    @classmethod
    def _ts_is_utc(cls, value: datetime) -> datetime:
        return _to_utc(value, "ts_utc")
