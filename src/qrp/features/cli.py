"""``python -m qrp.features`` — build the point-in-time feature lake from validated bars.

Reads only what is on disk (no gateway). Features are derived, so a rebuild overwrites the
prior build.

    uv run python -m qrp.features --config config
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from qrp.config import load_config
from qrp.features.store import FeatureStore, build_and_store, default_generators
from qrp.observability.logging import configure_logging, get_logger
from qrp.validation.lake import ValidatedBarStore

_log = get_logger(__name__)
# Exchange timezone used for session tagging; must match the SessionTagger used to build the
# validated lake so feature session-date grouping aligns with the session labels.
_EXCHANGE_TZ = "America/New_York"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qrp.features", description="Build the feature lake.")
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build point-in-time features for every configured symbol."""
    args = _parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)

    validated_store = ValidatedBarStore(config.storage)
    feature_store = FeatureStore(config.storage)
    generators = default_generators(
        config.features, config.labels.volatility, timezone=_EXCHANGE_TZ
    )

    built = 0
    for spec in config.universe.symbols:
        validated = validated_store.read(spec.symbol)
        if validated.is_empty():
            _log.warning("features.cli.no_validated_bars", symbol=spec.symbol)
            continue
        manifest = build_and_store(
            validated,
            feature_store,
            generators,
            symbol=spec.symbol,
            feature_spec_version=config.features.version,
            timezone=_EXCHANGE_TZ,
        )
        if manifest is not None:
            built += 1
    _log.info("features.cli.done", symbols_built=built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
