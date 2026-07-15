"""The trial registry: the persisted, append-only count that deflates every result (ADR-0010).

Both PBO (its `N` axis) and `auc_deflation` (its `K`) are only as honest as the number of distinct
configurations that were tried. That count is a **contract**, so — like the lockbox — it lives in a
dedicated append-only table keyed by ``dataset_id``, counted by ``COUNT(DISTINCT trial_hash)``, and
never in convenience-logging infrastructure whose schema is not ours to pin.

Trial identity is the content hash of everything that can change the out-of-sample score:
``{model_class, hyperparameters (incl. any fit-affecting seed), feature_spec_version,
label_spec_version, dataset_id}``. A **new configuration increments**; an **idempotent re-run of an
identical hash does not** (I6: a reproduction is not a new bet). A seed change that alters the fit
is a new configuration (fishing across seeds is fishing).

Threat model (ADR-0010 §5): this count is honest **only for search conducted through the Study**. A
fifty-idea notebook search run as a single winner registers one trial and gets false comfort; the
backstop is discipline (exploratory search on a designated exploration/pre-lockbox surface), not
code — there is no hash for an idea that never reached the choke point.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

# Append-only schema (ADR-0010). UNIQUE(dataset_id, trial_hash) makes re-registration idempotent;
# the count is COUNT(DISTINCT trial_hash), never a stored integer that could be rewritten.
TRIALS_DDL = """
CREATE TABLE IF NOT EXISTS trials (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_id    TEXT NOT NULL,
    trial_hash    TEXT NOT NULL,
    model_class   TEXT NOT NULL,
    auc           DOUBLE PRECISION,
    UNIQUE (dataset_id, trial_hash)
);
"""


def trial_hash(
    *,
    dataset_id: str,
    model_class: str,
    hyperparameters: Mapping[str, object],
    feature_spec_version: str,
    label_spec_version: str,
) -> str:
    """Content hash of the trial identity — distinct hash iff the OOS score can differ."""
    payload = json.dumps(
        {
            "dataset_id": dataset_id,
            "model_class": model_class,
            "hyperparameters": hyperparameters,
            "feature_spec_version": feature_spec_version,
            "label_spec_version": label_spec_version,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class TrialSpec:
    """The identity of a configuration to be scored — everything that can change the OOS number.

    Passed to ``Study.run`` so the choke point can register the trial as it scores it. A new spec
    (any field differs) is a new bet; an identical spec re-run is idempotent (I6).
    """

    dataset_id: str
    model_class: str
    hyperparameters: Mapping[str, object]
    feature_spec_version: str
    label_spec_version: str

    def hash(self) -> str:
        """The content hash that identifies this trial in the registry."""
        return trial_hash(
            dataset_id=self.dataset_id,
            model_class=self.model_class,
            hyperparameters=self.hyperparameters,
            feature_spec_version=self.feature_spec_version,
            label_spec_version=self.label_spec_version,
        )


@dataclass(frozen=True)
class Trial:
    """One registered configuration and the aggregate score it produced."""

    trial_hash: str
    dataset_id: str
    model_class: str
    auc: float
    registered_at: datetime


@runtime_checkable
class TrialStore(Protocol):
    """Append-only, idempotent-on-``(dataset_id, trial_hash)`` trial store."""

    def register(self, trial: Trial) -> None:
        """Record a trial; a repeat of an existing ``(dataset_id, trial_hash)`` is a no-op."""
        ...

    def count(self, dataset_id: str) -> int:
        """Number of DISTINCT trial hashes for ``dataset_id`` (the deflation's ``K``/``N``)."""
        ...

    def trials(self, dataset_id: str) -> list[Trial]:
        """The distinct trials registered for ``dataset_id``."""
        ...


class InMemoryTrialStore:
    """Fixture registry for CI — distinct-hash semantics without a live server."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Trial] = {}

    def register(self, trial: Trial) -> None:
        """Idempotent insert: the first registration of a hash wins; re-runs do not increment."""
        self._rows.setdefault((trial.dataset_id, trial.trial_hash), trial)

    def count(self, dataset_id: str) -> int:
        """Distinct trial-hash count for ``dataset_id``."""
        return sum(1 for (did, _), _ in self._rows.items() if did == dataset_id)

    def trials(self, dataset_id: str) -> list[Trial]:
        """Distinct trials for ``dataset_id`` in registration order."""
        return [t for (did, _), t in self._rows.items() if did == dataset_id]


class PostgresTrialStore:
    """The trial registry backed by the Postgres registry (§4); count is COUNT(DISTINCT)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def ensure_schema(self) -> None:
        """Create the append-only ``trials`` table if it does not exist."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(TRIALS_DDL)

    def register(self, trial: Trial) -> None:
        """Insert a trial, ignoring a repeat of an existing ``(dataset_id, trial_hash)``."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO trials (registered_at, dataset_id, trial_hash, model_class, auc) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (dataset_id, trial_hash) DO NOTHING",
                (
                    trial.registered_at,
                    trial.dataset_id,
                    trial.trial_hash,
                    trial.model_class,
                    trial.auc,
                ),
            )

    def count(self, dataset_id: str) -> int:
        """Distinct trial-hash count for ``dataset_id``."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT trial_hash) FROM trials WHERE dataset_id = %s",
                (dataset_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def trials(self, dataset_id: str) -> list[Trial]:
        """Distinct trials for ``dataset_id`` ordered by registration time."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (trial_hash) trial_hash, dataset_id, model_class, auc, "
                "registered_at FROM trials WHERE dataset_id = %s "
                "ORDER BY trial_hash, registered_at",
                (dataset_id,),
            ).fetchall()
        return [Trial(r[0], r[1], r[2], r[3], r[4]) for r in rows]
