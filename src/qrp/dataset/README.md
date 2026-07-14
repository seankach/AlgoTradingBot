# `qrp.dataset` — research dataset & `dataset_id` (ADR-0003)

## Purpose

Assemble the model-ready research dataset — the point-in-time feature vector aligned to its
triple-barrier label at the decision time — and address it by a **reproducible
`dataset_id`** so any result traces to the exact data, specs, costs, and code (I6).

## Architecture

- `manifest.py`:
  - `compute_dataset_id(...)` = `sha256{ sorted(raw_snapshot_ids), feature_spec_version,
    label_spec_version, cost_model_version, git_sha }[:16]`. Deterministic and
    order-independent.
  - `git_head_sha()` — HEAD sha with a `-dirty` suffix if the tree is modified (a dirty tree
    is not reproducible, so it deliberately changes the id).
  - `DatasetManifest` — the full expansion behind an id.
- `store.py`:
  - `assemble_dataset(features, labels)` — left-join features onto labels at
    `decision_ts == ts_utc`. Features are already point-in-time correct (ADR-0006) and labels
    look forward, so the join introduces no leakage.
  - `DatasetStore` — Parquet partitioned `symbol/date` (by decision-date); the manifest is
    written both per-symbol and **id-addressed** under `manifests/datasets/<id>.json`.
- `cli.py` / `__main__.py` — `python -m qrp.dataset` reads the feature/label/validated
  manifests for lineage and builds the dataset.

## Dependencies

`polars`, `qrp.features`, `qrp.labels`, `qrp.validation`, `qrp.config`. Uses `git` via
subprocess for the sha.

## Public interface

```bash
uv run python -m qrp.dataset --config config
```

```python
from qrp.dataset import DatasetStore, build_and_store, git_head_sha
build_and_store(features, labels, DatasetStore(cfg.storage), symbol="TSLA",
                feature_spec_version=..., label_spec_version=..., cost_model_version=...,
                raw_snapshot_ids=[...], feature_columns=[...], git_sha=git_head_sha())
frame = DatasetStore(cfg.storage).read("TSLA")
```

## Testing strategy

`tests/dataset/test_dataset.py`: `dataset_id` is deterministic + order-independent and
changes when *any* component changes; the assembly aligns the correct feature row to each
label at `decision_ts`; store + manifest (per-symbol and id-addressed) round-trip.

## Extension points

The `dataset_id` is what MLflow runs and the lockbox log reference (Module 5). Multi-symbol
datasets and a feature/label spec bump flow through unchanged (a new id is minted).
