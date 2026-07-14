"""Reporting: the Stage B evidence — earliest depth, session counts, spread distribution."""

from qrp.reporting.evidence import (
    add_spread_columns,
    earliest_traded,
    render_evidence,
    row_counts_by_session,
    spread_distribution_by_session,
)

__all__ = [
    "add_spread_columns",
    "earliest_traded",
    "render_evidence",
    "row_counts_by_session",
    "spread_distribution_by_session",
]
