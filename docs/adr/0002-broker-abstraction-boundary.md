# ADR-0002: Broker abstraction boundary — `MarketDataSource` / `Broker` protocols

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** Romesh Sharma (approved 2026-07-13)
- **Charter refs:** §4 (Broker isolation), §3 (public interfaces), §5 (data contract)

## Context

IBKR is the Phase-1 data source, accessed via `ib_async`. IBKR-specific concepts (contracts,
pacing rules, `whatToShow`, the split-readjustment quirk) must not leak into the research
platform, or a future second broker — or a recorded-fixture test harness — becomes
impossible without touching everything. The charter (§4) mandates: the platform depends on a
`MarketDataSource` protocol and a `Broker` protocol, and **`ib_async` must never be imported
outside `infrastructure/brokers/ibkr/`**.

This ADR fixes the *shape* of that boundary so Stage B can implement the IBKR adapter behind
it. It changes a public interface (§3a) and therefore requires a record.

## Options considered

- **No abstraction; call `ib_async` directly where needed.** Pros: least code now. Cons:
  hard-couples the whole platform to one vendor; makes fixture-based testing (§9) contort
  around a live-gateway client; violates the charter. Rejected.
- **Abstract base classes (`abc.ABC`) as the interface.** Pros: explicit, familiar. Cons:
  imposes an inheritance relationship; the adapter must import the base to subclass it,
  coupling infrastructure upward; nominal typing is heavier than needed. Rejected in favor
  of structural typing.
- **`typing.Protocol` structural interfaces (chosen).** The platform defines
  `MarketDataSource` and `Broker` as `Protocol`s in a broker-agnostic domain module. The
  IBKR adapter in `infrastructure/brokers/ibkr/` satisfies them structurally — no import of
  platform base classes, no inheritance. A second broker is a second adapter that satisfies
  the same protocols.

## Decision

Define two `Protocol`s (exact method signatures finalized in Stage B under this ADR):

- **`MarketDataSource`** — read-only historical/market data. Phase-1 surface centers on
  historical bar retrieval: fetch bars for a contract over a time range, for a given
  `what_to_show`, `use_rth`, and an explicitly pinned request timezone (§5), returning
  broker-neutral bar records in UTC. Also exposes earliest-available-timestamp discovery
  (the depth probe) and contract resolution.
- **`Broker`** — order placement, positions, account (Phase 5+). Declared as a protocol now
  only insofar as needed to reserve the boundary; **not implemented in Phase 1** (an unused
  abstraction is a liability, §10 — so the `Broker` protocol is defined minimally or deferred
  until its first real consumer).

Enforcement is mechanical, not by vigilance: an **import-linter** contract (run in CI)
forbids any module outside `infrastructure/brokers/ibkr/` from importing `ib_async`. Adding
`import-linter` is a dependency change recorded by this ADR (§3c).

All types crossing the boundary are platform-owned (plain dataclasses / Pydantic models),
never `ib_async` objects.

## Consequences

- The research platform is vendor-neutral above `infrastructure/`; a second data source is
  additive.
- Tests run against **recorded IBKR fixtures** through the same protocol the platform uses,
  never a live gateway (§9).
- Structural typing keeps the adapter dependency-free of platform base classes; the
  dependency arrow points only inward.
- Cost: protocol definitions must be kept in sync with real adapter capabilities; a
  capability the protocol cannot express signals the boundary needs revisiting (new ADR).
- The CI import contract is now a load-bearing gate: if it is removed, the boundary can rot
  silently. It is treated as part of §9.
