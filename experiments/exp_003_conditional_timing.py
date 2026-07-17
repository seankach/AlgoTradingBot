"""EXP-003 (pre-registered): once you can't profit from the clock, is any timing signal left?

Committed WITH docs/experiments/exp-003-conditional-timing.md. The threshold below was pre-declared
from the measured 1-min conditional null (shuffled labels only) BEFORE market-only was ever run.

    python experiments/exp_003_conditional_timing.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from qrp.models.gbm import LightGBMModel
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import Study
from qrp.validation.trials import InMemoryTrialStore, TrialSpec

MARKET = ["ret_1b", "ret_5b", "ret_15b", "ret_30b", "ewma_vol", "range_vol", "rel_volume"]
CALENDAR = ["minute_of_day", "is_pre", "is_rth", "is_post"]
FULL = MARKET + CALENDAR

H, STRIDE = 30, 15
DID = "exp-001-tsla-2021-2025"
FEATURE_SPEC = LABEL_SPEC = "2026.07.14-eventbar"
BEST = {"num_leaves": 31, "learning_rate": 0.03, "min_child_samples": 200}

# Pre-declared from the measured 1-min conditional null (mean 0.50000, std 0.00164). Mechanical.
NULL_MEAN, NULL_STD = 0.50000, 0.00164
THRESHOLD = NULL_MEAN + 3 * NULL_STD  # 0.50492
RESOLVABLE_EXCESS = 3 * NULL_STD  # 0.00492 -> rho >= 0.0087


def _load() -> pl.DataFrame:
    files = sorted(Path("data/datasets").glob("symbol=TSLA/date=*/dataset.parquet"))
    df = (
        pl.scan_parquet(files)
        .filter(pl.col("decision_ts").dt.year().is_between(2021, 2025))
        .sort("decision_ts")
        .collect()
        .gather_every(STRIDE)
        .drop_nulls(FULL)
    )
    # 1-min buckets: every calendar feature is constant within a bucket, so the calendar is removed
    # by construction (calendar-only conditional AUC == 0.5000 exactly). Forced, not tuned.
    return df.with_columns(pl.col("minute_of_day").cast(pl.Float64).alias("tod_bucket"))


def main() -> None:
    df = _load()
    store = InMemoryTrialStore()
    study = Study(
        PurgedCPCV(6, 2), trial_store=store, inner_val_frac=0.2, bucket_column="tod_bucket"
    )
    nb = df.get_column("tod_bucket").n_unique()
    print(f"EXP-003: {df.height:,} rows, {nb} 1-min buckets (~{df.height // nb} rows/bucket)")
    print(f"pre-declared threshold = {THRESHOLD:.5f} (null {NULL_MEAN:.5f} + 3*{NULL_STD:.5f})\n")

    aucs: dict[str, float] = {}
    for name, feats in (("market_only", MARKET), ("full_11", FULL)):
        spec = TrialSpec(DID, "LightGBMModel", BEST, FEATURE_SPEC, LABEL_SPEC)
        res = study.run(df, LightGBMModel(params=BEST), feature_columns=feats, h_bars=H, trial=spec)
        aucs[name] = res.auc
        sig = (res.auc - NULL_MEAN) / NULL_STD
        n_t = store.count(DID)
        print(f"  trials={n_t}  {name:12s} conditional AUC {res.auc:.4f}  ({sig:+.2f} sigma)")

    mkt = aucs["market_only"]
    print(f"\nfull_11 - market_only = {aucs['full_11'] - mkt:+.4f} (calendar should add ~nothing)")
    if mkt >= THRESHOLD:
        verdict = f"within-bucket timing DETECTABLE ({mkt:.4f} >= {THRESHOLD:.5f}) -> Phase 5 costs"
    else:
        verdict = (
            f"NO within-bucket timing detectable at this power ({mkt:.4f} < {THRESHOLD:.5f})"
            f" -> NEW FEATURES. Not 'absent': resolves excess >= {RESOLVABLE_EXCESS:.5f}"
            f" (rho >= 0.0087)"
        )
    print(f"\nVERDICT: {verdict}")


if __name__ == "__main__":
    main()
