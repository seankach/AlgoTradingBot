"""Unit tests for structured logging configuration."""

from __future__ import annotations

import json

import pytest

from qrp.config.models import LoggingConfig
from qrp.observability.logging import configure_logging, get_logger


def test_json_renderer_emits_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingConfig(level="INFO", renderer="json"))
    log = get_logger("test.logger", symbol="TSLA")
    log.info("ingest.chunk.fetched", bars=2000)

    line = capsys.readouterr().out.strip()
    record = json.loads(line)

    assert record["event"] == "ingest.chunk.fetched"
    assert record["level"] == "info"
    assert record["symbol"] == "TSLA"
    assert record["bars"] == 2000
    assert "timestamp" in record
    # UTC ISO-8601 timestamps end in Z.
    assert record["timestamp"].endswith("Z")


def test_level_filtering_suppresses_below_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(LoggingConfig(level="WARNING", renderer="json"))
    log = get_logger("test.logger")
    log.info("should.be.filtered")
    log.warning("should.appear")

    out = capsys.readouterr().out.strip()
    assert "should.be.filtered" not in out
    assert "should.appear" in out


def test_console_renderer_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingConfig(level="INFO", renderer="console"))
    get_logger("test.logger").info("human.readable")
    out = capsys.readouterr().out
    assert "human.readable" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip())
