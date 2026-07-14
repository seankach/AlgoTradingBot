"""``python -m qrp.labels`` — build the triple-barrier label lake from validated bars.

Reads only what is on disk (no gateway). Labels are derived, so a rebuild overwrites the
prior build.

    uv run python -m qrp.labels --config config
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from qrp.config import load_config
from qrp.features.volatility import barrier_volatility
from qrp.labels.store import LabelStore, build_and_store
from qrp.labels.triple_barrier import TripleBarrier
from qrp.observability.logging import configure_logging, get_logger
from qrp.validation.lake import ValidatedBarStore

_log = get_logger(__name__)
_EXCHANGE_TZ = "America/New_York"  # must match the session tagging / feature build


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qrp.labels", description="Build the label lake.")
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build triple-barrier labels for every configured symbol."""
    args = _parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)

    validated_store = ValidatedBarStore(config.storage)
    label_store = LabelStore(config.storage)
    generator = TripleBarrier(
        k=config.labels.barrier_sigma_multiple_k,
        h_minutes=config.labels.vertical_barrier_bars_h,
    )
    vol = config.labels.volatility

    built = 0
    for spec in config.universe.symbols:
        validated = validated_store.read(spec.symbol)
        if validated.is_empty():
            _log.warning("labels.cli.no_validated_bars", symbol=spec.symbol)
            continue
        sigma = barrier_volatility(
            validated,
            bucket_minutes=vol.bucket_minutes,
            ewma_span_days=vol.ewma_span_days,
            timezone=_EXCHANGE_TZ,
        )
        manifest = build_and_store(
            validated,
            sigma,
            generator,
            label_store,
            symbol=spec.symbol,
            label_spec_version=config.labels.version,
        )
        if manifest is not None:
            built += 1
    _log.info("labels.cli.done", symbols_built=built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
