"""Shared Pydantic base for all config and domain models.

Centralised so the immutability/strictness policy is defined once and cannot drift
between modules.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Immutable model that rejects unknown keys.

    ``frozen`` — no hidden mutable state after construction (CLAUDE.md §3).
    ``extra="forbid"`` — a misspelled key raises instead of being silently ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
