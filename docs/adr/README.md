# Architecture Decision Records

An ADR captures one architecturally significant decision: its context, the options
weighed, the choice made, and the consequences accepted.

Per `CLAUDE.md` §3, an ADR is **required** for any decision that:

- (a) changes a public interface,
- (b) changes a storage schema,
- (c) adds or removes a dependency, or
- (d) affects any invariant in `CLAUDE.md` §2.

**Process:** write the ADR, set its status to `Proposed`, then **stop and wait for
approval**. Do not build on an unapproved decision. Once approved, set the status to
`Accepted` and record the date.

## Conventions

- Filename: `NNNN-short-kebab-title.md`, `NNNN` zero-padded and monotonically increasing.
- Never edit an accepted decision in place. To change it, write a new ADR that supersedes
  the old one, and set the old one's status to `Superseded by ADR-XXXX`.
- Copy `0000-adr-template.md` to start a new record.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-storage-architecture.md) | Storage architecture: Parquet lake + DuckDB + Postgres registry | Accepted |
| [0002](0002-broker-abstraction-boundary.md) | Broker abstraction boundary (`MarketDataSource` / `Broker`) | Accepted |
| [0003](0003-dataset-versioning-content-addressed-snapshots.md) | Dataset versioning via content-addressed snapshots + manifests | Accepted |
| [0004](0004-bar-timestamp-semantics-and-point-in-time-correctness.md) | Bar timestamp semantics and the point-in-time rule | Accepted |
| [0005](0005-frontier-settling-vs-retroactive-readjustment.md) | Frontier settling vs. retroactive re-adjustment in conflict detection | Accepted |
| [0006](0006-feature-store-interface-and-point-in-time-contract.md) | Feature store: interface, point-in-time contract, initial feature spec | Accepted |
| [0007](0007-triple-barrier-label-spec-and-barrier-volatility.md) | Triple-barrier label spec, exit-policy unity, and barrier volatility | Accepted |
| [0008](0008-pit-and-horizon-corrections-from-review.md) | Point-in-time, horizon, and tie-break corrections (external review) | Accepted |
