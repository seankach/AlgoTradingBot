"""The feature-generation boundary (ADR-0006).

A ``FeatureGenerator`` owns one feature family. It computes its columns **through bar t**
(it may use bar *t* itself); the feature store then applies the single mandatory 1-bar lag
so the stored row at *t* reflects only bars ``<= t - 1min`` (I1, ADR-0004). Generators whose
output is deterministic/known at the decision time (calendar features) set
``is_deterministic = True`` and are exempt from that lag.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import polars as pl


@runtime_checkable
class FeatureGenerator(Protocol):
    """Computes one family of point-in-time features from validated bars."""

    @property
    def name(self) -> str:
        """Stable identifier for the family (used in logs/manifests)."""
        ...

    @property
    def output_columns(self) -> tuple[str, ...]:
        """Names of the columns :meth:`generate` produces."""
        ...

    @property
    def is_deterministic(self) -> bool:
        """Whether outputs are known at decision time (calendar) and so are not lagged."""
        ...

    def generate(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Return ``ts_utc`` plus :attr:`output_columns`, computed through bar *t*.

        ``bars`` is the validated frame plus a ``_session_date`` column (ET trading date),
        sorted by ``ts_utc``. Within a session date the minute index is contiguous, so
        row-wise operations grouped by ``_session_date`` are exactly minute-based and never
        bleed across the overnight gap.
        """
        ...
