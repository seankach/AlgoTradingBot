"""Unit tests for broker-neutral domain models (timestamp semantics, strictness)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from qrp.domain.models import Bar


def _bar(ts: datetime) -> Bar:
    return Bar(
        ts_utc=ts,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100.0,
        bar_count=10,
        wap=1.4,
    )


def test_accepts_utc_timestamp() -> None:
    bar = _bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
    assert bar.ts_utc.utcoffset() == timedelta(0)


def test_converts_aware_non_utc_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    bar = _bar(datetime(2024, 1, 2, 9, 30, tzinfo=eastern))
    # 09:30 -05:00 == 14:30 UTC
    assert bar.ts_utc == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    assert bar.ts_utc.tzinfo == UTC


def test_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _bar(datetime(2024, 1, 2, 14, 30))


def test_bar_is_frozen_and_strict() -> None:
    bar = _bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
    with pytest.raises(ValidationError):
        bar.close = 9.9  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Bar(  # type: ignore[call-arg]
            ts_utc=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=100.0,
            bar_count=10,
            wap=1.4,
            unexpected="x",
        )
