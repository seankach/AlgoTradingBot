# TSLA Quantitative Research Platform (`qrp`)

An institutional-quality quantitative **research** platform trading a single instrument
(TSLA) on 1-minute bars from Interactive Brokers. The governing charter is
[`CLAUDE.md`](CLAUDE.md) — read it before contributing. Research quality beats backtest
performance, always.

> **Status: Phase 1, Stage A (Foundation).** Only the foundation and the four gating ADRs
> exist. IBKR ingestion (Stage B) begins after the ADRs are approved.

## What's here now

```
config/                 # YAML configuration (one file per domain; costs.yaml per §8)
docs/adr/               # Architecture Decision Records (0001–0004 proposed, awaiting approval)
docker/mlflow/          # MLflow server image
docker-compose.yml      # PostgreSQL + MLflow local stack
src/qrp/
  config/               # Pydantic v2 models + YAML loader (validated at load)
  observability/        # structlog → JSON logging conventions
tests/                  # unit tests for config + logging
.github/workflows/ci.yml# quality gates (CLAUDE.md §9)
```

Stage B directories (`infrastructure/brokers/ibkr/`, ingestion, storage) are intentionally
**not** created yet — the charter forbids empty packages reserved for later (§3, §10).

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

## Configuration

Edit the YAML files under `config/`. Everything is validated at load; a missing
result-affecting value fails immediately rather than defaulting silently.

**Before trusting any result**, set the commission numbers in `config/costs.yaml` to your
actual IBKR account schedule (§8).

## Quality gates (a module is not done until all pass)

`ruff check` · `ruff format --check` · `mypy --strict` · `pytest` · docstrings on public
interfaces · module README · structured JSON logging · config validated at load. Enforced in
CI. **Black is never used** (§4).
