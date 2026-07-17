"""Cross-symbol PIT leakage tests — the acceptance gate for the context seam (ADR-0013 §4).

The existing ``close_t`` arbiter only knows single-symbol lag and CANNOT catch this: a naive
``join(context, on="ts_utc")`` pairs SPY's bar *t* with TSLA's decision bar *t*. Under §5 a bar
stamped *t* covers ``[t, t+1)`` and is incomplete until *t+1*, so features as-of *t* may use only
bars ``<= t-1`` — the naive join is a one-bar CROSS-SYMBOL look-ahead.

Two controls, each proven to FAIL a naive implementation (a leakage test that cannot fail is
decoration — the canary principle, ADR-0009):

* **Control 1 — concurrent-bar leak**, lockstep calendars.
* **Control 2 — cross-calendar off-by-one**, the UNION timeline: SPY prints in minutes TSLA does
  not, so "previous SPY traded close" and "previous TSLA traded bar" land on different timestamps.
  An off-by-one in *which symbol's clock defines "previous"* is invisible to Control 1.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from qrp.features.store import build_features

_TZ = "America/New_York"


def _bars(minutes: list[int], closes: list[float]) -> pl.DataFrame:
    """A validated traded-bar frame at the given minute offsets (RTH, 2024-01-03 10:00 ET)."""
    start = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "ts_utc": [start + timedelta(minutes=m) for m in minutes],
            "session": ["RTH"] * len(minutes),
            "open": list(closes),
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": list(closes),
            "volume": [1_000.0] * len(minutes),
            "is_traded": [True] * len(minutes),
        }
    )


class _PlantedContextClose:
    """Plants the context's close as a feature — the cross-symbol analogue of the close_t arbiter.

    It reads ONLY the aligned context handed to it by the store. If the store's alignment leaks the
    concurrent bar, this feature carries it and the controls below catch it.
    """

    name = "planted_context_close"
    output_columns = ("ctx_close",)
    is_deterministic = False  # must be lagged like any other market feature

    def generate(self, bars: pl.DataFrame, context: Mapping[str, pl.DataFrame]) -> pl.DataFrame:
        ctx = context["SPY"]
        return bars.select("ts_utc").with_columns(ctx.get_column("close").alias("ctx_close"))


def _stored(target: pl.DataFrame, spy: pl.DataFrame) -> pl.DataFrame:
    return build_features(
        target, [_PlantedContextClose()], timezone=_TZ, context={"SPY": spy}
    ).sort("ts_utc")


# --------------------------------------------------------------------------------------------
# Control 1 — the concurrent-bar leak (lockstep calendars)
# --------------------------------------------------------------------------------------------


def test_control1_context_close_is_never_the_concurrent_bar() -> None:
    closes = [10.0, 11.0, 13.0, 16.0, 20.0]
    spy_closes = [100.0, 101.0, 103.0, 106.0, 110.0]
    out = _stored(_bars([0, 1, 2, 3, 4], closes), _bars([0, 1, 2, 3, 4], spy_closes))
    got = out.get_column("ctx_close").to_list()

    assert got[0] is None  # nothing precedes the first decision bar
    for t in range(1, len(spy_closes)):
        assert got[t] == spy_closes[t - 1]  # the PREVIOUS SPY close...
        assert got[t] != spy_closes[t]  # ...never the concurrent one (I1, §5)


# --------------------------------------------------------------------------------------------
# Control 2 — the cross-calendar off-by-one (UNION timeline)
# --------------------------------------------------------------------------------------------


def test_control2_alignment_uses_the_targets_clock_across_differing_calendars() -> None:
    # TSLA trades at {0,1,4}; SPY trades at {0,1,2,3,4}. SPY bars 2 and 3 exist ONLY in minutes
    # TSLA was absent. On TSLA's decision bar 4 the aligned context must be SPY bar 1 — SPY as-of
    # TSLA's PREVIOUS TRADED BAR — pinning the target's clock as the definition of "previous".
    tsla = _bars([0, 1, 4], [10.0, 11.0, 20.0])
    spy = _bars([0, 1, 2, 3, 4], [100.0, 101.0, 102.0, 103.0, 104.0])
    got = _stored(tsla, spy).get_column("ctx_close").to_list()

    assert got[0] is None
    assert got[1] == 100.0  # decision bar 1 -> SPY as-of TSLA's previous traded bar (0)
    # The crux: decision bar 4.
    assert got[2] == 101.0, "must be SPY bar 1 (as-of TSLA's previous traded bar)"
    assert got[2] != 104.0, "must NOT be SPY bar 4 — the concurrent-bar leak"
    assert got[2] not in (102.0, 103.0), "must NOT be a SPY bar existing only when TSLA was absent"


# --------------------------------------------------------------------------------------------
# The negative controls: a naive implementation must FAIL BOTH (else the tests are decoration)
# --------------------------------------------------------------------------------------------


def _naive_stored(target: pl.DataFrame, spy: pl.DataFrame) -> pl.DataFrame:
    """The realistic bug: join the context on ts_utc into the feature frame AFTER the lag, so the
    context is never lagged and the row at t carries the CONCURRENT context bar."""
    lagged = build_features(target, [], timezone=_TZ).sort("ts_utc")
    return lagged.join(
        spy.select("ts_utc", pl.col("close").alias("ctx_close")), on="ts_utc", how="left"
    )


def test_negative_control_naive_join_fails_control1() -> None:
    spy_closes = [100.0, 101.0, 103.0, 106.0, 110.0]
    out = _naive_stored(_bars([0, 1, 2, 3, 4], [10.0, 11.0, 13.0, 16.0, 20.0]),
                        _bars([0, 1, 2, 3, 4], spy_closes))
    got = out.get_column("ctx_close").to_list()
    # The naive join carries the CONCURRENT bar — exactly the leak. Assert the leak is present, so
    # this test fails loudly if someone "fixes" the naive path and the control stops discriminating.
    assert got[2] == spy_closes[2], "naive join should leak the concurrent bar (control is live)"
    with pytest.raises(AssertionError):
        for t in range(1, len(spy_closes)):
            assert got[t] == spy_closes[t - 1]  # the real rule — must NOT hold for the naive path


def test_negative_control_naive_join_fails_control2() -> None:
    tsla = _bars([0, 1, 4], [10.0, 11.0, 20.0])
    spy = _bars([0, 1, 2, 3, 4], [100.0, 101.0, 102.0, 103.0, 104.0])
    got = _naive_stored(tsla, spy).get_column("ctx_close").to_list()
    assert got[2] == 104.0, "naive join leaks SPY's concurrent bar 4 on TSLA's decision bar 4"
    with pytest.raises(AssertionError):
        assert got[2] == 101.0  # the aligned answer — must NOT hold for the naive path
