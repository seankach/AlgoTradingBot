"""IBKR historical-data pacing limiter (CLAUDE.md §5).

IBKR allows at most ``max_weight`` historical requests per rolling ``window_seconds``
(60 per 10 minutes), and a ``BID_ASK`` request counts double. This limiter enforces that
**by construction**: :meth:`PacingLimiter.acquire` blocks the caller until issuing a
request of the given weight would keep the rolling sum within budget. It does not import
``ib_async`` and has no global state.

The clock and sleep functions are injected so the policy is fully unit-testable without
real time passing.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class PacingLimiter:
    """A rolling-window weighted rate limiter.

    Contract:
        ``acquire(weight)`` records a request of ``weight`` units, blocking first if
        necessary so that the sum of weights within any ``window_seconds`` interval never
        exceeds ``max_weight``. Single-threaded use (one ingester loop); not thread-safe.

    Failure modes:
        Raises ``ValueError`` for a non-positive weight or a weight that alone exceeds
        ``max_weight`` (that request could never satisfy the budget).
    """

    def __init__(
        self,
        max_weight: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_weight <= 0:
            raise ValueError("max_weight must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_weight = max_weight
        self._window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()

    def _current_weight(self) -> int:
        return sum(weight for _, weight in self._events)

    def acquire(self, weight: int) -> float:
        """Block until a request of ``weight`` fits the budget, then record it.

        Args:
            weight: Cost of the pending request (e.g. 1 for TRADES, 2 for BID_ASK).

        Returns:
            Total seconds slept while waiting (``0.0`` if the request fit immediately).
        """
        if weight <= 0:
            raise ValueError("weight must be positive")
        if weight > self._max_weight:
            raise ValueError(
                f"weight {weight} exceeds max_weight {self._max_weight}; "
                "this request can never fit the pacing budget"
            )

        slept_total = 0.0
        while True:
            now = self._clock()
            self._evict(now)
            if self._current_weight() + weight <= self._max_weight:
                self._events.append((now, weight))
                return slept_total

            # Free just enough of the oldest weight to admit this request, then wait for
            # those events to age out of the window.
            needed = self._current_weight() + weight - self._max_weight
            freed = 0
            wait_until = now
            for ts, event_weight in self._events:
                freed += event_weight
                if freed >= needed:
                    wait_until = ts + self._window_seconds
                    break
            sleep_for = max(0.0, wait_until - now)
            self._sleep(sleep_for)
            slept_total += sleep_for
