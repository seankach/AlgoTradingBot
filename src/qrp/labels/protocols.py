"""The label-generation boundary (§6, ADR-0007).

A ``LabelGenerator`` turns validated bars + the barrier volatility into labels. The label is
the exit policy (I3): the same object generates the training target and drives the backtest
exit, so they cannot drift.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import polars as pl


@runtime_checkable
class LabelGenerator(Protocol):
    """Generates labels from validated bars and a per-bar barrier volatility."""

    @property
    def name(self) -> str:
        """Stable identifier for the label method (used in logs/manifests)."""
        ...

    def generate(self, bars: pl.DataFrame, sigma: pl.DataFrame) -> pl.DataFrame:
        """Return one row per labelled decision bar.

        Args:
            bars: Validated bars (``ts_utc, session, open, high, low, close, is_traded``).
            sigma: Barrier volatility (``ts_utc, sigma``), causal (ADR-0007).

        Returns:
            Columns ``decision_ts, entry_ts, exit_ts, label, touched, realized_return, sigma``.
            ``label`` is ``+1`` (upper barrier first), ``-1`` (lower first), or ``0``
            (vertical timeout / ambiguous same-bar touch).
        """
        ...
