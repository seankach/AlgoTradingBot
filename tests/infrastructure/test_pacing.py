"""Unit tests for the IBKR pacing limiter — no real time passes (injected clock)."""

from __future__ import annotations

import pytest

from qrp.infrastructure.brokers.ibkr.pacing import PacingLimiter


class FakeClock:
    """Deterministic clock whose ``sleep`` advances virtual time."""

    def __init__(self) -> None:
        self.t = 1000.0

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.t += seconds


def _limiter(clock: FakeClock, max_weight: int = 60, window: float = 600.0) -> PacingLimiter:
    return PacingLimiter(max_weight, window, clock=clock.time, sleep=clock.sleep)


def test_requests_within_budget_do_not_sleep() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(60):
        assert limiter.acquire(1) == 0.0
    assert clock.t == 1000.0


def test_over_budget_sleeps_until_oldest_expires() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(60):
        limiter.acquire(1)
    # 61st request must wait a full window for the first event to age out.
    slept = limiter.acquire(1)
    assert slept == 600.0
    assert clock.t == 1600.0


def test_bid_ask_weight_counts_double() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(30):
        assert limiter.acquire(2) == 0.0  # 30 * 2 == 60, exactly full
    assert limiter.acquire(2) == 600.0  # next one must wait


def test_window_slides_so_later_requests_fit_without_sleeping() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(60):
        limiter.acquire(1)
    clock.t += 600.0  # let the whole window age out
    assert limiter.acquire(1) == 0.0


def test_partial_expiry_frees_exactly_enough() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, max_weight=3, window=100.0)
    limiter.acquire(1)  # t=1000
    clock.t += 40.0
    limiter.acquire(1)  # t=1040
    clock.t += 40.0
    limiter.acquire(1)  # t=1080; window now holds 3 -> full
    # Need 1 unit; the oldest (t=1000) expires at t=1100 -> sleep 20s from t=1080.
    slept = limiter.acquire(1)
    assert slept == pytest.approx(20.0)
    assert clock.t == pytest.approx(1100.0)


def test_invalid_weights_raise() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    with pytest.raises(ValueError, match="weight must be positive"):
        limiter.acquire(0)
    with pytest.raises(ValueError, match="exceeds max_weight"):
        limiter.acquire(61)
