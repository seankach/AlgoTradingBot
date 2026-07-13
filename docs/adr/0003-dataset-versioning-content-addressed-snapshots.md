# ADR-0003: Dataset versioning via content-addressed snapshots + manifests (not DVC)

- **Status:** Proposed
- **Date:** 2026-07-13
- **Deciders:** (awaiting approval)
- **Charter refs:** §4, §2 invariants I2, I6; §8 (costs in `dataset_id`)

## Context

Every reported result must be regenerable bit-for-bit from a `dataset_id` and a git SHA
(I6). Raw data is immutable and append-only (I2). Complicating this: `whatToShow=TRADES` is
split-adjusted, and **IBKR retroactively rewrites bar history after each split** (TSLA 5:1
Aug 2020, 3:1 Aug 2022) — so re-fetching the "same" range can legitimately return different
numbers. The versioning scheme must make that visible and reproducible, not paper over it.

We need an identity for (a) each raw pull and (b) each research dataset assembled from raw
pulls plus a feature spec and a label spec.

## Options considered

- **DVC.** Pros: purpose-built data versioning, git-integrated. Cons: introduces a *second
  source of truth* that must be kept in sync with our own manifests and with MLflow; another
  CLI, cache, and remote to operate; its pointer model duplicates what content-addressing
  already gives us. The charter explicitly rejects it (§4): "A second versioning system is a
  second source of truth to get out of sync." Rejected.
- **git-lfs.** Pros: simple large-file storage. Cons: not a dataset-composition model; no
  notion of manifests over feature/label specs; storage-oriented, not lineage-oriented.
  Rejected.
- **Delta Lake / Iceberg / lakeFS time travel.** Pros: table-level versioning. Cons: heavy;
  overlaps ADR-0001's decision to keep Parquet as plain immutable files; another system to
  reconcile. Rejected for Phase 1.
- **Content-addressed snapshots + a manifest hash (chosen).** Each raw pull is written once
  and identified by a `snapshot_id` derived from its content; a `dataset_id` is a hash over
  the set of contributing snapshot ids plus spec versions and the git SHA.

## Decision

- **Raw snapshot identity.** Each pull produces an immutable snapshot tagged with a
  `fetch_ts_utc` and a `snapshot_id` (a content hash over the snapshot's canonical bytes /
  row content plus its provenance: symbol, range, `what_to_show`, request timezone). Re-fetches
  never overwrite; they create new snapshots. The validator diffs overlapping ranges across
  snapshots and **raises** on mismatch (this is how retroactive split re-adjustment is
  caught rather than silently absorbed — I2, §5).
- **Dataset identity.** `dataset_id = hash{ set(raw_snapshot_ids), feature_spec_version,
  label_spec_version, cost_model_version, git_sha }`. Cost model version is included because
  costs affect results and are frozen per instance (I4, §8). A manifest file records the full
  expansion behind each `dataset_id` and is stored under the manifests directory.
- **No DVC, no second versioning system.** The manifest + content hashes are the single
  lineage record; MLflow references `dataset_id`s but does not own them.

The concrete hash function, canonicalization rules, and manifest schema are finalized in
Stage B / Phase 2 under this ADR.

## Consequences

- **Protects I2 and I6:** immutability is structural, and any result traces deterministically
  to the exact bytes and specs that produced it.
- Split re-adjustment becomes a *detected event* (validator raises) with both snapshots
  retained, rather than a silent corruption — directly serving §5.
- One lineage system, not two; nothing to sync. MLflow, the manifest, and the lake agree by
  construction.
- Cost: we implement and maintain our own hashing/canonicalization and manifest format
  instead of adopting an off-the-shelf tool. Accepted: the charter deems the sync burden of a
  second tool the greater risk.
- Commits us to including `cost_model_version` (and later feature/label spec versions) in the
  dataset hash; changing any of them yields a new `dataset_id` and flags prior results as
  invalidated (§8).
