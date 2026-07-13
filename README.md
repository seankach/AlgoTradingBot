# TSLA Quantitative Research Platform (`qrp`)

An institutional-quality quantitative **research** platform trading a single instrument
(TSLA) on 1-minute bars from Interactive Brokers. The governing charter is
[`CLAUDE.md`](CLAUDE.md) — read it before contributing. Research quality beats backtest
performance, always.

> **Status: Phase 1 complete (Stage A + Stage B), ADRs accepted.** The full IBKR ingestion
> pipeline is built and tested against fixtures. Producing the real dataset + evidence
> requires a live IB gateway (see below).

## What's here now

```
config/                 # YAML configuration (one file per domain; costs.yaml per §8)
docs/adr/               # Architecture Decision Records (0001–0004, Accepted)
docs/ibkr-open-questions.md  # live-gateway behaviours to confirm (OQ-1…OQ-6)
docker/                 # MLflow server image; docker-compose.yml = Postgres + MLflow
src/qrp/
  base.py               # shared strict Pydantic base
  config/               # Pydantic v2 models + YAML loader (validated at load)
  observability/        # structlog → JSON logging conventions
  domain/               # broker-neutral Bar + MarketDataSource/Broker protocols (ADR-0002)
  infrastructure/
    brokers/ibkr/       # ib_async adapter: pacing, hybrid depth probe, paced fetch
    storage/            # immutable content-addressed Parquet snapshots (ADR-0001/0003)
  validation/           # conflicts, session tagging, gap index, quality flags (§5)
  ingestion/            # backfill + daily incremental orchestrator + CLI
  reporting/            # evidence: earliest depth, session counts, spread distribution
tests/                  # unit + fixture-based tests (never a live gateway, §9)
.github/workflows/ci.yml# quality gates + import-linter boundary (CLAUDE.md §9)
```

The `ib_async` import is confined to `infrastructure/brokers/ibkr/`, enforced by an
import-linter contract in CI (ADR-0002).

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                      # create venv + install from the committed lockfile
uv run pytest                # run tests
uv run ruff check .          # lint
uv run ruff format --check . # format check
uv run mypy                  # strict type-check
```

Local research services (PostgreSQL + MLflow):

```bash
cp .env.example .env         # then edit credentials
docker compose up -d         # Postgres :5432, MLflow UI :5000
```

## Running ingestion (needs a live IB gateway)

With IB Gateway/TWS running on the port in `config/ibkr.yaml` (7497 = TWS paper):

```bash
uv run python -m qrp.ingestion --config config --mode auto   # backfill, then incremental
uv run python -m qrp.reporting --config config               # print the evidence report
```

The ingester discovers TSLA's true earliest 1-minute timestamp (no hardcoded start),
respects IBKR pacing by construction (≤60 req/10 min, BID_ASK ×2), stores immutable
content-addressed snapshots, and never overwrites. The reporting command reads what's on
disk (no gateway needed) and prints the earliest depth, session row counts, and BID_ASK
spread distribution by session.

## Configuration

Edit the YAML files under `config/`. Everything is validated at load; a missing
result-affecting value fails immediately rather than defaulting silently.

**Before trusting any result**, set the commission numbers in `config/costs.yaml` to your
actual IBKR account schedule (§8).

## Quality gates (a module is not done until all pass)

`ruff check` · `ruff format --check` · `mypy --strict` · `pytest` · docstrings on public
interfaces · module README · structured JSON logging · config validated at load. Enforced in
CI. **Black is never used** (§4).
