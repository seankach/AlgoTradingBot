"""Ingestion orchestration: backfill and daily incremental over the same code path (§5)."""

from qrp.ingestion.orchestrator import DepthMarker, Ingestor

__all__ = ["DepthMarker", "Ingestor"]
