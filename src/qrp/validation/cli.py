"""``python -m qrp.validation`` — materialise the validated-bar lake from raw snapshots.

Reads only what is on disk (no gateway). Rebuilds are safe and idempotent-in-effect:
validated bars are derived, so a rebuild overwrites the prior build.

    uv run python -m qrp.validation --config config
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from qrp.config import load_config
from qrp.infrastructure.storage import SnapshotStore
from qrp.observability.logging import configure_logging, get_logger
from qrp.validation.lake import ValidatedBarStore, build_and_store
from qrp.validation.sessions import SessionTagger

_log = get_logger(__name__)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qrp.validation", description="Build the validated-bar lake."
    )
    parser.add_argument("--config", default="config", help="Path to the config directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build validated bars for every configured symbol over the ingest sessions."""
    args = _parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)

    snapshots = SnapshotStore(config.storage)
    validated = ValidatedBarStore(config.storage)
    tagger = SessionTagger()
    # Research scope (PRE+RTH+POST by default); OVERNIGHT is ingested but excluded (§5).
    scope = [str(session) for session in config.session.tradable_sessions]

    built = 0
    for spec in config.universe.symbols:
        manifest = build_and_store(
            snapshots, validated, tagger, symbol=spec.symbol, sessions_included=scope
        )
        if manifest is not None:
            built += 1
    _log.info("validated.cli.done", symbols_built=built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
