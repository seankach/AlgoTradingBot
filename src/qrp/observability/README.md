# `qrp.observability` — structured logging

## Purpose

Define the structured-logging conventions the whole platform follows: `structlog` →
JSON, UTC ISO-8601 timestamps, context bound as key/values rather than formatted strings
(CLAUDE.md §4, §9). No `print` at boundaries.

## Architecture

- `logging.py` — `configure_logging(config)` sets up structlog process-wide;
  `get_logger(name, **context)` returns a bound logger. Configuration is explicit: importing
  the module does nothing (§3, no import-time side effects).

Processor chain: contextvars merge → log level → stack info → UTC ISO timestamp →
exception formatting → JSON (or console) renderer. Level filtering uses
`make_filtering_bound_logger`.

## Dependencies

`structlog`, and `qrp.config` (for `LoggingConfig`).

## Public interface

```python
from qrp.observability import configure_logging, get_logger
from qrp.config import load_config

config = load_config("config")
configure_logging(config.logging)              # once, at application entry

log = get_logger(__name__, symbol="TSLA")
log.info("ingest.chunk.fetched", bars=2000, snapshot_id="…")
```

Event names are dotted, lowercase, and stable (`ingest.chunk.fetched`), so logs are
greppable and machine-parseable. Bind durable context (symbol, snapshot_id, request_id) once
via `get_logger(...)` or `structlog.contextvars.bind_contextvars(...)`.

## Usage

Set level and renderer in `config/logging.yaml` (`renderer: json` for production/CI,
`console` for local human-readable output). JSON records always carry `event`, `level`,
`logger`, and a `timestamp` ending in `Z`.

## Testing strategy

Unit tests (`tests/observability/`) assert that the JSON renderer emits valid,
key-complete JSON with a UTC timestamp, that level filtering suppresses sub-threshold
events, and that the console renderer is human-oriented (not JSON).

## Extension points

Additional processors (e.g. sampling, redaction, or a call-site adder) are inserted into the
`shared` processor list in `configure_logging`. Sinks other than stdout are configured via the
`logger_factory`.
