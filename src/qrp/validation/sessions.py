"""Session tagging from the exchange calendar (§5).

Every bar is labelled ``PRE | RTH | POST | OVERNIGHT``. Regular-session boundaries come
from ``exchange_calendars`` (so early closes are honoured); the pre/post extended-hours
window edges (04:00 and 20:00 ET by convention) are applied on top. Tags are derived from
the calendar, never from naive local time (§5).

``exchange_calendars`` speaks pandas ``Timestamp``; that is confined to this module's
calendar calls and converted to plain ``datetime`` immediately — the data pipeline itself
stays in Polars (no pandas, §4).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import polars as pl

_PRE_START_ET = time(4, 0)
_POST_END_ET = time(20, 0)


class SessionTagger:
    """Labels UTC bar timestamps with their market session.

    Contract:
        ``tag_frame`` adds a string ``session`` column. Regular-hours boundaries are taken
        from the calendar per trading day (early closes included); pre/post edges are the
        ET wall-clock window. Non-trading days and out-of-window minutes are ``OVERNIGHT``.
    """

    def __init__(
        self,
        calendar_name: str = "XNYS",
        *,
        timezone: str = "America/New_York",
        pre_start_et: time = _PRE_START_ET,
        post_end_et: time = _POST_END_ET,
    ) -> None:
        self._calendar = xcals.get_calendar(calendar_name)
        self._zone = ZoneInfo(timezone)
        self._pre_start = pre_start_et
        self._post_end = post_end_et

    def _boundary_frame(self, min_date: date, max_date: date) -> pl.DataFrame:
        """Build a per-trading-day table of UTC session boundaries."""
        sessions = self._calendar.sessions_in_range(min_date.isoformat(), max_date.isoformat())
        rows: list[dict[str, object]] = []
        for session in sessions:
            session_date: date = session.date()
            rows.append(
                {
                    "et_date": session_date,
                    "pre_start": datetime.combine(
                        session_date, self._pre_start, tzinfo=self._zone
                    ).astimezone(UTC),
                    "rth_open": self._calendar.session_open(session).to_pydatetime(),
                    "rth_close": self._calendar.session_close(session).to_pydatetime(),
                    "post_end": datetime.combine(
                        session_date, self._post_end, tzinfo=self._zone
                    ).astimezone(UTC),
                }
            )
        schema: dict[str, pl.DataType | type[pl.DataType]] = {
            "et_date": pl.Date,
            "pre_start": pl.Datetime("us", "UTC"),
            "rth_open": pl.Datetime("us", "UTC"),
            "rth_close": pl.Datetime("us", "UTC"),
            "post_end": pl.Datetime("us", "UTC"),
        }
        return pl.DataFrame(rows, schema=schema)

    def tag_frame(self, frame: pl.DataFrame, *, ts_column: str = "ts_utc") -> pl.DataFrame:
        """Return ``frame`` with a ``session`` column added.

        Raises:
            ValueError: If ``frame`` is empty (no date range to resolve).
        """
        if frame.height == 0:
            raise ValueError("cannot tag sessions on an empty frame")

        et_date = pl.col(ts_column).dt.convert_time_zone(str(self._zone)).dt.date()
        with_date = frame.with_columns(et_date=et_date)
        min_date = with_date.get_column("et_date").min()
        max_date = with_date.get_column("et_date").max()
        assert isinstance(min_date, date)
        assert isinstance(max_date, date)

        bounds = self._boundary_frame(min_date, max_date)
        ts = pl.col(ts_column)
        session = (
            pl.when(pl.col("rth_open").is_null())
            .then(pl.lit("OVERNIGHT"))
            .when((ts >= pl.col("pre_start")) & (ts < pl.col("rth_open")))
            .then(pl.lit("PRE"))
            .when((ts >= pl.col("rth_open")) & (ts < pl.col("rth_close")))
            .then(pl.lit("RTH"))
            .when((ts >= pl.col("rth_close")) & (ts < pl.col("post_end")))
            .then(pl.lit("POST"))
            .otherwise(pl.lit("OVERNIGHT"))
        )
        return (
            with_date.join(bounds, on="et_date", how="left")
            .with_columns(session=session)
            .drop("et_date", "pre_start", "rth_open", "rth_close", "post_end")
        )
