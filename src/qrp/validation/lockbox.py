"""The lockbox: an append-only touch counter enforcing I5 (ADR-0009, build step 5).

The final out-of-sample range may be evaluated **at most twice for the whole project** (§7). That
limit is enforced by code, never by the developer's memory: the only path to the lockbox is
:meth:`qrp.validation.study.Study.evaluate_lockbox`, which calls :meth:`Lockbox.touch` *before* it
scores anything, so every look costs a touch whether or not the evaluation then succeeds.

Tamper-evidence by construction: the counter **is the row count** of an append-only
``lockbox_touches`` table — there is no mutable counter column and no decrement/update path in the
store interface, so a touch cannot be un-counted by anything short of a visible row delete. A blank
justification is rejected: the justification is the audit trail, and a silent touch defeats it.

CI exercises the enforcement logic against :class:`InMemoryLockboxStore` (a fixture/disposable
registry — no live server, per ADR-0009); :class:`PostgresLockboxStore` is the same contract backed
by the Postgres registry (§4) and is covered by an integration test that is skipped without a DSN.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

MAX_TOUCHES = 2  # §7: the lockbox may be touched at most twice for the entire project.

# Append-only schema (ADR-0009 §4). The CHECK enforces the non-empty justification at the DB layer
# too (defence in depth); the counter is COUNT(*), never a stored integer that could be rewritten.
LOCKBOX_TOUCHES_DDL = """
CREATE TABLE IF NOT EXISTS lockbox_touches (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    touched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_id   TEXT NOT NULL,
    git_sha      TEXT NOT NULL,
    justification TEXT NOT NULL CHECK (length(btrim(justification)) > 0)
);
"""


class LockboxError(ValueError):
    """A lockbox touch was rejected for a bad argument (e.g. an empty justification)."""


class LockboxBurnedError(RuntimeError):
    """The lockbox has already been touched the maximum number of times (I5)."""


@dataclass(frozen=True)
class LockboxTouch:
    """One immutable audit row: who looked at the lockbox, when, at which commit, and why."""

    touched_at: datetime
    dataset_id: str
    git_sha: str
    justification: str


@runtime_checkable
class LockboxStore(Protocol):
    """Append-only touch store. Deliberately has **no** update/delete — appends and counts only."""

    def append_touch(self, touch: LockboxTouch) -> None:
        """Append an immutable touch row."""
        ...

    def count(self, dataset_id: str) -> int:
        """Return the number of touch rows for ``dataset_id`` — the counter *is* this row count."""
        ...

    def touches(self, dataset_id: str) -> list[LockboxTouch]:
        """Return the touch rows for ``dataset_id`` in insertion order (the audit trail)."""
        ...


class InMemoryLockboxStore:
    """Fixture/disposable registry for CI — the row-count contract without a live server."""

    def __init__(self) -> None:
        self._rows: list[LockboxTouch] = []

    def append_touch(self, touch: LockboxTouch) -> None:
        """Append an immutable touch row."""
        self._rows.append(touch)

    def count(self, dataset_id: str) -> int:
        """Row count for ``dataset_id`` (no separate mutable counter exists to disagree with it)."""
        return sum(1 for r in self._rows if r.dataset_id == dataset_id)

    def touches(self, dataset_id: str) -> list[LockboxTouch]:
        """Touch rows for ``dataset_id`` in insertion order."""
        return [r for r in self._rows if r.dataset_id == dataset_id]


class Lockbox:
    """Enforces the at-most-``max_touches`` rule for one lockbox range (a ``dataset_id``)."""

    def __init__(
        self,
        store: LockboxStore,
        *,
        dataset_id: str,
        git_sha: str,
        max_touches: int = MAX_TOUCHES,
    ) -> None:
        self._store = store
        self._dataset_id = dataset_id
        self._git_sha = git_sha
        self._max_touches = max_touches

    def count(self) -> int:
        """How many times this lockbox has been touched (the append-only row count)."""
        return self._store.count(self._dataset_id)

    def remaining(self) -> int:
        """Touches left before the lockbox is burned."""
        return max(0, self._max_touches - self.count())

    def touch(self, justification: str) -> int:
        """Record one touch and return the new count; raise instead of exceeding the limit.

        Raises:
            LockboxError: the justification is empty/blank (a silent touch is not allowed).
            LockboxBurnedError: the lockbox is already at its touch limit. The row is **not**
                appended, so the count is unchanged — the raise does not itself increment.
        """
        if not justification or not justification.strip():
            raise LockboxError("a lockbox touch requires a non-empty justification (audit trail)")
        current = self.count()
        if current >= self._max_touches:
            raise LockboxBurnedError(
                f"lockbox {self._dataset_id!r} is burned: already touched {current} times "
                f"(limit {self._max_touches}). Carve a new range from future data (I5)."
            )
        self._store.append_touch(
            LockboxTouch(
                touched_at=datetime.now(UTC),
                dataset_id=self._dataset_id,
                git_sha=self._git_sha,
                justification=justification.strip(),
            )
        )
        return self.count()


class PostgresLockboxStore:
    """The lockbox store backed by the Postgres registry (§4). Append-only; count is COUNT(*)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PostgresLockboxStore:
        """Build a DSN from ``POSTGRES_*`` env vars (as in ``docker-compose.yml``); no defaults."""
        e = os.environ if env is None else env
        missing = [k for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB") if k not in e]
        if missing:
            raise LockboxError(f"missing Postgres env for the lockbox registry: {missing}")
        host = e.get("POSTGRES_HOST", "localhost")
        port = e.get("POSTGRES_PORT", "5432")
        dsn = (
            f"host={host} port={port} dbname={e['POSTGRES_DB']} "
            f"user={e['POSTGRES_USER']} password={e['POSTGRES_PASSWORD']}"
        )
        return cls(dsn)

    def ensure_schema(self) -> None:
        """Create the append-only ``lockbox_touches`` table if it does not exist."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(LOCKBOX_TOUCHES_DDL)

    def append_touch(self, touch: LockboxTouch) -> None:
        """Insert one immutable touch row."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO lockbox_touches (touched_at, dataset_id, git_sha, justification) "
                "VALUES (%s, %s, %s, %s)",
                (touch.touched_at, touch.dataset_id, touch.git_sha, touch.justification),
            )

    def count(self, dataset_id: str) -> int:
        """Row count for ``dataset_id`` — ``SELECT COUNT(*)``, never a stored counter."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM lockbox_touches WHERE dataset_id = %s", (dataset_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def touches(self, dataset_id: str) -> list[LockboxTouch]:
        """Touch rows for ``dataset_id`` ordered by ``touched_at`` (the audit trail)."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT touched_at, dataset_id, git_sha, justification FROM lockbox_touches "
                "WHERE dataset_id = %s ORDER BY touched_at, id",
                (dataset_id,),
            ).fetchall()
        return [LockboxTouch(r[0], r[1], r[2], r[3]) for r in rows]
