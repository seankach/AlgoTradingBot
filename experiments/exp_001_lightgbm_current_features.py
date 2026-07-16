"""EXP-001 (pre-registered): does the current feature set carry a directional edge?

Committed WITH docs/experiments/exp-001-lightgbm-current-features.md before the run. Everything here
is frozen by that pre-registration: span, subsample (by effective n), the 11 features, H=30/k=2,
CPCV(6,2), the K=12 grid, B=300 deflation at 3 seeds, and the verdict rule. Run once; read the
verdict whatever it is. A null ("no edge in these features") is a success.

    python experiments/exp_001_lightgbm_current_features.py
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import polars as pl

from qrp.models.gbm import LightGBMModel
from qrp.validation.overfitting import auc_deflation
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import Study
from qrp.validation.trials import InMemoryTrialStore, TrialSpec

FEATURES = [
    "ret_1b",
    "ret_5b",
    "ret_15b",
    "ret_30b",
    "ewma_vol",
    "range_vol",
    "rel_volume",
    "minute_of_day",
    "is_pre",
    "is_rth",
    "is_post",
]
H = 30
STRIDE = 15  # -> ~74k effective n (pre-registered)
DID = "exp-001-tsla-2021-2025"
FEATURE_SPEC = "2026.07.14-eventbar"
LABEL_SPEC = "2026.07.14-eventbar"
B = 300
SEEDS = (0, 1, 2)

# K = 12: the entire declared trial space.
GRID = [
    {"num_leaves": nl, "learning_rate": lr, "min_child_samples": mc}
    for nl, lr, mc in product((15, 31, 63), (0.03, 0.10), (50, 200))
]


def _load() -> pl.DataFrame:
    files = sorted(Path("data/datasets").glob("symbol=TSLA/date=*/dataset.parquet"))
    return (
        pl.scan_parquet(files)
        .filter(pl.col("decision_ts").dt.year().is_between(2021, 2025))
        .sort("decision_ts")
        .collect()
        .gather_every(STRIDE)
        .drop_nulls(FEATURES)
    )


def main() -> None:
    df = _load()
    store = InMemoryTrialStore()
    study = Study(PurgedCPCV(6, 2), trial_store=store, inner_val_frac=0.2)
    print(f"EXP-001: {df.height:,} rows (stride {STRIDE}, 2021-2025 PRE+RTH+POST), K={len(GRID)}\n")

    scored: list[tuple[dict[str, object], float]] = []
    for cfg in GRID:
        spec = TrialSpec(DID, "LightGBMModel", cfg, FEATURE_SPEC, LABEL_SPEC)
        res = study.run(
            df, LightGBMModel(params=cfg), feature_columns=FEATURES, h_bars=H, trial=spec
        )
        scored.append((cfg, res.auc))
        print(f"  trials={store.count(DID):2d}  wAUC {res.auc:.4f}  {cfg}")

    k = store.count(DID)
    best_cfg, best_auc = max(scored, key=lambda r: r[1])
    print(f"\ntrial count = {k} (declared K=12)\nBEST wAUC {best_auc:.4f}  {best_cfg}\n")

    deflations = []
    for seed in SEEDS:
        d = auc_deflation(
            study,
            df,
            LightGBMModel(params=best_cfg),
            observed_auc=best_auc,
            n_trials=k,
            feature_columns=FEATURES,
            h_bars=H,
            n_permutations=B,
            seed=seed,
        )
        deflations.append(d)
        print(f"  deflation(K={k}, B={B}, seed={seed}) = {d:.4f}")

    arr = np.array(deflations)
    mean, spread = float(arr.mean()), float(arr.max() - arr.min())
    stable = spread < 0.05
    if not stable:
        verdict = "UNSTABLE across seeds — under-powered, do not certify"
    elif mean < 0.5:
        verdict = "NO directional edge in these features -> better FEATURES (not grid, not label)"
    elif mean > 0.9:
        verdict = "weak real edge survives the 12-way search -> next gate: cost analysis (Phase 5)"
    else:
        verdict = "AMBIGUOUS (0.5-0.9) -> back to FEATURES (not grid, not label)"
    print(f"\ndeflation mean {mean:.4f}  seed-spread {spread:.4f}  (stable<0.05: {stable})")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
