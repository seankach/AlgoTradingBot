"""Triple-barrier labelling (§6, ADR-0007/0008) — the label IS the exit policy (I3).

For a decision at the close of a traded bar, a position is entered at the **open of the next
traded bar** and walked forward over bars that actually exist (§5) until the first of:
take-profit (``+k*sigma``), stop-loss (``-k*sigma``), or the vertical barrier ``H`` **bars**
after entry (ADR-0008: horizons are counted in bars of the active sampler, not wall-clock
minutes). Outcome ``+1 / -1 / 0``. The volatility ``sigma`` is the causal, time-of-day-bucketed
estimate shared with the ``ewma_vol`` feature (ADR-0007), so the signal and the barrier that
defines the strategy cannot drift.

Conservative intrabar tie-break (ADR-0008): if one bar's range spans *both* barriers, OHLCV
cannot reveal which was hit first, so the outcome is resolved to the **stop** (``label = -1``,
exit at the lower barrier); ``touched = "both"`` is kept as a diagnostic. The walk is vectorised
over a bounded bar offset (H is small), so it runs over millions of bars in numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

_I64 = npt.NDArray[np.int64]
_F64 = npt.NDArray[np.float64]

_TOUCHED = {1: "tp", -1: "sl", 2: "both", 0: "vertical"}


@dataclass(frozen=True)
class TripleBarrier:
    """Symmetric +/-k*sigma barriers with an H-bar vertical timeout."""

    k: float
    h_bars: int
    name: str = "triple_barrier"

    def generate(self, bars: pl.DataFrame, sigma: pl.DataFrame) -> pl.DataFrame:
        """Label every traded decision bar (see :class:`LabelGenerator`)."""
        traded = (
            bars.join(sigma, on="ts_utc", how="left").filter(pl.col("is_traded")).sort("ts_utc")
        )
        if traded.height < 2:
            return _empty_labels()

        ts_us = traded.get_column("ts_utc").dt.epoch(time_unit="us").to_numpy()
        return _walk(
            ts_us=ts_us.astype(np.int64),
            open_=traded.get_column("open").to_numpy().astype(np.float64),
            high=traded.get_column("high").to_numpy().astype(np.float64),
            low=traded.get_column("low").to_numpy().astype(np.float64),
            close=traded.get_column("close").to_numpy().astype(np.float64),
            sigma=traded.get_column("sigma").to_numpy().astype(np.float64),
            k=self.k,
            h_bars=self.h_bars,
        )


def _empty_labels() -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "decision_ts": pl.Datetime("us", "UTC"),
        "entry_ts": pl.Datetime("us", "UTC"),
        "exit_ts": pl.Datetime("us", "UTC"),
        "label": pl.Int64,
        "touched": pl.String,
        "gross_return": pl.Float64,
        "sigma": pl.Float64,
    }
    return pl.DataFrame(schema=schema)


def _walk(
    *,
    ts_us: _I64,
    open_: _F64,
    high: _F64,
    low: _F64,
    close: _F64,
    sigma: _F64,
    k: float,
    h_bars: int,
) -> pl.DataFrame:
    """Vectorised first-touch barrier walk over H bars. Returns labels for labelable bars."""
    n = ts_us.shape[0]
    decision = np.arange(n - 1)  # decide at bar i, enter at bar i+1
    entry = decision + 1

    sig = sigma[decision]
    entry_open = open_[entry]
    entry_ts = ts_us[entry]
    upper = entry_open * (1.0 + k * sig)
    lower = entry_open * (1.0 - k * sig)
    valid = np.isfinite(sig) & (sig > 0) & np.isfinite(entry_open) & (entry_open > 0)

    m = decision.shape[0]
    label = np.zeros(m, dtype=np.int64)
    touched = np.zeros(m, dtype=np.int64)  # 0 vertical, 1 tp, -1 sl, 2 both
    exit_ts = entry_ts.copy()
    exit_price = np.full(m, np.nan)
    resolved = np.zeros(m, dtype=bool)
    in_any_window = np.zeros(m, dtype=bool)
    last_close = np.full(m, np.nan)
    last_ts = entry_ts.copy()

    for offset in range(h_bars + 1):  # entry bar (0) through the vertical barrier (H)
        j = entry + offset
        in_bounds = j < n
        js = np.where(in_bounds, j, n - 1)
        in_window = in_bounds & valid & ~resolved
        last_close = np.where(in_window, close[js], last_close)
        last_ts = np.where(in_window, ts_us[js], last_ts)
        in_any_window |= in_window

        tp = in_window & (high[js] >= upper)
        sl = in_window & (low[js] <= lower)
        up = tp & ~sl
        both = tp & sl
        # Conservative tie-break: a stop touch (alone or with tp) resolves to the stop.
        label = np.where(sl, -1, np.where(up, 1, label))
        touched = np.where(both, 2, np.where(up, 1, np.where(sl & ~tp, -1, touched)))
        exit_ts = np.where(tp | sl, ts_us[js], exit_ts)
        exit_price = np.where(sl, lower, np.where(up, upper, exit_price))
        resolved |= tp | sl

    timeout = valid & in_any_window & ~resolved
    exit_ts = np.where(timeout, last_ts, exit_ts)
    exit_price = np.where(timeout, last_close, exit_price)

    keep = valid & in_any_window
    gross_return = exit_price / entry_open - 1.0

    return pl.DataFrame(
        {
            "decision_ts": ts_us[decision][keep],
            "entry_ts": entry_ts[keep],
            "exit_ts": exit_ts[keep],
            "label": label[keep],
            "touched": touched[keep],
            "gross_return": gross_return[keep],
            "sigma": sig[keep],
        }
    ).with_columns(
        pl.col("touched").replace_strict(_TOUCHED, return_dtype=pl.String),
        pl.col("decision_ts", "entry_ts", "exit_ts")
        .cast(pl.Datetime("us"))
        .dt.replace_time_zone("UTC"),
    )
