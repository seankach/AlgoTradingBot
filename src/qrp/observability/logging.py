"""Structured JSON logging for the platform (CLAUDE.md §4, §9).

Conventions the rest of the platform follows:

* Call :func:`configure_logging` exactly once, at application entry. Importing this
  module has **no side effects** (CLAUDE.md §3: no import-time configuration).
* Obtain loggers via :func:`get_logger`; bind stable context with keyword arguments
  (``symbol``, ``snapshot_id``, ``request_id``, ...) rather than formatting strings.
* Timestamps are UTC ISO-8601. Never ``print`` at module boundaries.
* Per-task context (e.g. a request id spanning several log lines) is carried with
  :func:`structlog.contextvars.bind_contextvars`, merged automatically into every event.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import FilteringBoundLogger, Processor

from qrp.config.models import LoggingConfig


def configure_logging(config: LoggingConfig) -> None:
    """Configure structlog process-wide according to ``config``.

    Contract:
        Idempotent-safe to call once at startup. Emits to stdout. With
        ``renderer="json"`` every record is a single JSON object carrying at least
        ``event``, ``level``, ``logger`` and an ISO-8601 UTC ``timestamp``.

    Args:
        config: Validated logging configuration (level and renderer).

    Failure modes:
        ``config.level`` is validated by :class:`LoggingConfig`, so an unknown level
        cannot reach this function.
    """
    level = logging.getLevelNamesMapping()[config.level]

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if config.renderer == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **initial_values: object) -> FilteringBoundLogger:
    """Return a bound logger, optionally pre-bound with context.

    Args:
        name: Logger name, conventionally the module's ``__name__``.
        **initial_values: Context key/values bound to every event from this logger.

    Returns:
        A structlog bound logger.

    Example:
        >>> log = get_logger(__name__, symbol="TSLA")  # doctest: +SKIP
        >>> log.info("ingest.chunk.fetched", bars=2000)  # doctest: +SKIP
    """
    logger: FilteringBoundLogger = structlog.get_logger(name, **initial_values)
    return logger
