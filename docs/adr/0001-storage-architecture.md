# ADR-0001: Storage architecture — Parquet lake + DuckDB query layer + Postgres registry

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** Romesh Sharma (approved 2026-07-13)
- **Charter refs:** §4 (Architecture), §2 invariants I2, I6, I7

## Context

The platform must store, from Phase 1 onward:

1. **Raw market data** — TSLA 1-minute bars (`TRADES` and `BID_ASK`), `useRTH=0`,
   potentially ~1.5M+ rows per `whatToShow` per year of extended-hours coverage, arriving
   as immutable snapshots that are never overwritten (I2).
2. **Validated, session-tagged bars** — derived from raw snapshots.
3. **Registry/metadata** — experiment, run, and (later) trade records, plus MLflow's own
   backend store.

These three have different access patterns. Bars are append-only, columnar, and scanned in
large analytical ranges. Registry data is transactional, relational, small, and frequently
updated. Forcing them into one engine serves neither well. The charter (§4) already names
the intended stack; this ADR records the reasoning and the schema commitments so Stage B
can build against a fixed target.

Constraints: reproducibility bit-for-bit (I6); raw data immutable (I2); no CSV as a source
of truth (I7); Polars + PyArrow in the core, no pandas.

## Options considered

- **Everything in PostgreSQL (incl. bars as rows).** Pros: one engine, transactional,
  familiar. Cons: columnar analytical scans over millions of minute bars are slow and
  storage-heavy in a row store; immutability must be enforced by convention, not by the
  medium; couples bulk data to a running server; poor fit for content-addressed snapshots.
  Rejected.
- **TimescaleDB (Postgres + hypertables).** Pros: good time-series ergonomics. Cons: still
  a server-bound row/columnar hybrid; adds an extension dependency; snapshots and
  content-addressing are unnatural; overkill for a single instrument. Rejected.
- **Parquet files only, queried directly with Polars.** Pros: simplest; immutable by
  nature. Cons: no convenient SQL/ad-hoc analytical layer across many partition files;
  cross-snapshot diffing and exploration get verbose. Insufficient alone.
- **Parquet lake + DuckDB query layer + Postgres registry (chosen).** Parquet is the system
  of record for all market data and features, partitioned `symbol/date`. DuckDB is a
  *stateless query layer* that reads the Parquet lake in place (SQL, joins, cross-snapshot
  diffs) — it stores nothing authoritative. PostgreSQL holds only the MLflow backend store
  and the experiment/run/trade registry.
- **Delta Lake / lakeFS / Iceberg over the Parquet.** Pros: ACID table semantics, time
  travel. Cons: heavy machinery and a second versioning system that competes with our
  content-addressed manifest scheme (see ADR-0003); operationally large for a single-node
  research platform. Rejected for Phase 1.

## Decision

Adopt the three-tier split exactly as the charter states:

- **Parquet lake** is the immutable system of record for raw snapshots and validated bars,
  partitioned by `symbol/date`, written via PyArrow, read via Polars/DuckDB.
- **DuckDB** is an analytical query layer over the lake. It is **not** a storage engine; its
  database file is a disposable cache/catalog and may be deleted and rebuilt from Parquet at
  any time.
- **PostgreSQL** (via Docker Compose) is the MLflow backend store and the
  experiment/run/trade metadata registry. It is **not** a feature store and never holds bulk
  bars.

Raw-snapshot schema (columns, finalized in Stage B under this ADR): `ts_utc` (UTC, bar
start), `open`, `high`, `low`, `close`, `volume`, `bar_count`, `wap`, plus provenance
columns `snapshot_id`, `fetch_ts_utc`, `what_to_show`, `symbol`. Validated-bar schema adds
`session` (`PRE|RTH|POST|OVERNIGHT`), `is_traded`, and quality flags.

## Consequences

- **Protects I2/I6/I7:** immutability is a property of the medium (append-only Parquet
  snapshots), reproducibility is anchored to file-level content hashes, and CSV never enters
  the pipeline.
- Bulk data does not depend on a running database server; only metadata does. The lake is
  portable and cheap to back up.
- DuckDB being disposable means a corrupted catalog is never a data-loss event.
- Cost: two storage technologies to understand (files + Postgres). Accepted — they map
  cleanly onto the two genuinely different access patterns.
- Commits us to: a defined partition layout (`symbol/date`), a snapshot schema, and a
  Postgres registry schema. Any later change to those schemas requires a new ADR (§3b).
