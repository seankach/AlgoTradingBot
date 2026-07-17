"""The feature-generation boundary (ADR-0006).

A ``FeatureGenerator`` owns one feature family. It computes its columns **through bar t**
(it may use bar *t* itself); the feature store then applies the single mandatory 1-bar lag
so the stored row at *t* reflects only bars ``<= t - 1min`` (I1, ADR-0004). Generators whose
output is deterministic/known at the decision time (calendar features) set
``is_deterministic = True`` and are exempt from that lag.
"""

from __future__ import annotations

from collections.abc import Mapping
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


@runtime_checkable
class ContextFeatureGenerator(Protocol):
    """Computes cross-asset features from the target's bars plus aligned context symbols (ADR-0013).

    Extends — does not replace — :class:`FeatureGenerator`. Same ``name`` / ``output_columns`` /
    ``is_deterministic`` contract, and the same single mandatory 1-bar lag applies to the output.

    **The generator never constructs the cross-symbol join.** The store hands it ``context`` already
    aligned as-of the target's bar *t* (the most recent *traded* context bar with ``ts <= t``), and
    the store's existing lag then makes the stored row at *t* use target **and** context data from
    ``<= t - 1`` (§5/I1). A dangerous join belongs to the framework, not to the thing being tested —
    the same reason ``Study`` owns the purged inner fold (ADR-0011).
    """

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
        """Whether outputs are known at decision time and so are not lagged."""
        ...

    def generate(self, bars: pl.DataFrame, context: Mapping[str, pl.DataFrame]) -> pl.DataFrame:
        """Return ``ts_utc`` plus :attr:`output_columns`, computed through bar *t*.

        Args:
            bars: the target's traded frame (as :class:`FeatureGenerator` receives).
            context: symbol -> that symbol's frame **row-aligned to** ``bars``: row *i* holds the
                most recent traded context bar with ``ts <= bars[i].ts_utc``, or nulls when the
                context has no such bar (stale/absent — never dropped, ADR-0013 §5a).
        """
        ...
