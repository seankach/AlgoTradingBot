"""Ingestion orchestrator: backfill and daily incremental share one code path.

Both ``backfill`` and ``incremental`` funnel through :meth:`Ingestor._ingest_window`, so
the daily update exercises exactly the same fetch-and-store logic as the historical
backfill (a requirement of §5). The orchestrator depends only on the broker-neutral
:class:`~qrp.domain.protocols.MarketDataSource` — connection lifecycle is the caller's
concern — so it is broker-agnostic.

The discovered earliest timestamp is persisted as a :class:`DepthMarker` so depth is
recorded, never re-probed unnecessarily and never hardcoded (§5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qrp.base import StrictModel
from qrp.domain.enums import WhatToShow
from qrp.domain.protocols import MarketDataSource
from qrp.infrastructure.storage.snapshots import SnapshotManifest, SnapshotStore
from qrp.observability.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_WINDOW = timedelta(days=30)


class DepthMarker(StrictModel):
    """Persisted record of a series' discovered earliest available timestamp."""

    symbol: str
    what_to_show: WhatToShow
    earliest_utc: datetime
    discovered_at_utc: datetime


class Ingestor:
    """Coordinates a :class:`MarketDataSource` and a :class:`SnapshotStore`."""

    def __init__(
        self,
        source: MarketDataSource,
        store: SnapshotStore,
        *,
        request_timezone: str,
        depth_dir: Path,
        bar_size: str = "1 min",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._source = source
        self._store = store
        self._tz = request_timezone
        self._depth_dir = depth_dir
        self._bar_size = bar_size
        self._clock = clock

    def _depth_path(self, symbol: str, what_to_show: WhatToShow) -> Path:
        return self._depth_dir / f"{symbol}_{what_to_show}.json"

    def discover_earliest(
        self, symbol: str, what_to_show: WhatToShow, *, force: bool = False
    ) -> datetime | None:
        """Return the persisted earliest timestamp, probing and persisting it if absent."""
        path = self._depth_path(symbol, what_to_show)
        if path.is_file() and not force:
            return DepthMarker.model_validate_json(path.read_text(encoding="utf-8")).earliest_utc

        earliest = self._source.earliest_available_timestamp(
            symbol, what_to_show, bar_size=self._bar_size
        )
        if earliest is None:
            _log.warning("ingest.depth.unknown", symbol=symbol, what_to_show=str(what_to_show))
            return None

        marker = DepthMarker(
            symbol=symbol,
            what_to_show=what_to_show,
            earliest_utc=earliest,
            discovered_at_utc=self._clock(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker.model_dump_json(indent=2), encoding="utf-8")
        _log.info(
            "ingest.depth.persisted",
            symbol=symbol,
            what_to_show=str(what_to_show),
            earliest=earliest.isoformat(),
        )
        return earliest

    def _latest_end(self, symbol: str, what_to_show: WhatToShow) -> datetime | None:
        ends = [
            manifest.range_end_utc
            for manifest in self._store.list_manifests()
            if manifest.symbol == symbol and manifest.what_to_show == what_to_show
        ]
        return max(ends) if ends else None

    def _ingest_window(
        self, symbol: str, what_to_show: WhatToShow, start: datetime, end: datetime
    ) -> SnapshotManifest | None:
        """Fetch ``[start, end)`` and store it as one immutable snapshot (shared path)."""
        if start >= end:
            return None
        bars = self._source.fetch_bars(
            symbol,
            start_utc=start,
            end_utc=end,
            what_to_show=what_to_show,
            bar_size=self._bar_size,
            use_rth=False,
            request_timezone=self._tz,
        )
        if not bars:
            return None
        return self._store.write_snapshot(
            symbol=symbol,
            what_to_show=what_to_show,
            bars=bars,
            request_timezone=self._tz,
            bar_size=self._bar_size,
        )

    def backfill(
        self,
        symbol: str,
        what_to_show: WhatToShow,
        *,
        window: timedelta = _DEFAULT_WINDOW,
    ) -> list[SnapshotManifest]:
        """Ingest the full available history in windows, one snapshot per window."""
        earliest = self.discover_earliest(symbol, what_to_show)
        if earliest is None:
            return []
        now = self._clock()
        manifests: list[SnapshotManifest] = []
        cursor = earliest
        while cursor < now:
            window_end = min(cursor + window, now)
            manifest = self._ingest_window(symbol, what_to_show, cursor, window_end)
            if manifest is not None:
                manifests.append(manifest)
            cursor = window_end
        _log.info(
            "ingest.backfill.done",
            symbol=symbol,
            what_to_show=str(what_to_show),
            snapshots=len(manifests),
        )
        return manifests

    def incremental(self, symbol: str, what_to_show: WhatToShow) -> SnapshotManifest | None:
        """Ingest from the last stored bar to now (same path as backfill).

        Starts at the previous last bar (a one-bar overlap) so the conflict validator can
        confirm continuity against the prior snapshot.
        """
        start = self._latest_end(symbol, what_to_show) or self.discover_earliest(
            symbol, what_to_show
        )
        if start is None:
            return None
        return self._ingest_window(symbol, what_to_show, start, self._clock())
