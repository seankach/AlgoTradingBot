"""EXP-002 (pre-registered): is EXP-001's edge alpha, or a calendar?

Committed WITH docs/experiments/exp-002-calendar-ablation.md before the run. Three ablations through
the SAME Study (not feature importance), identical to EXP-001 except the feature set. All three
register as trials. The read is pre-declared in the doc and reproduced in the verdict below.

    python experiments/exp_002_calendar_ablation.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from qrp.models.gbm import LightGBMModel
from qrp.validation.splits import PurgedCPCV
from qrp.validation.study import Study
from qrp.validation.trials import InMemoryTrialStore, TrialSpec

CALENDAR = ["minute_of_day", "is_pre", "is_rth", "is_post"]
MARKET = ["ret_1b", "ret_5b", "ret_15b", "ret_30b", "ewma_vol", "range_vol", "rel_volume"]
FULL = MARKET + CALENDAR

H = 30
STRIDE = 15
DID = "exp-001-tsla-2021-2025"  # same dataset as EXP-001; the count accumulates against it
FEATURE_SPEC = "2026.07.14-eventbar"
LABEL_SPEC = "2026.07.14-eventbar"
# The EXP-001 winner. Only the feature set varies across the three trials.
BEST = {"num_leaves": 31, "learning_rate": 0.03, "min_child_samples": 200}
FULL_AUC = 0.5289  # EXP-001 result; the read is anchored to its excess over 0.5

ABLATIONS = [("calendar_floor", CALENDAR), ("market_only", MARKET), ("full", FULL)]


def _load() -> pl.DataFrame:
    files = sorted(Path("data/datasets").glob("symbol=TSLA/date=*/dataset.parquet"))
    return (
        pl.scan_parquet(files)
        .filter(pl.col("decision_ts").dt.year().is_between(2021, 2025))
        .sort("decision_ts")
        .collect()
        .gather_every(STRIDE)
        .drop_nulls(FULL)
    )


def main() -> None:
    df = _load()
    store = InMemoryTrialStore()
    study = Study(PurgedCPCV(6, 2), trial_store=store, inner_val_frac=0.2)
    print(f"EXP-002: {df.height:,} rows (same span/stride as EXP-001)\n", flush=True)

    aucs: dict[str, float] = {}
    for name, feats in ABLATIONS:
        # feature_set folded into hyperparameters: trial_hash does NOT cover feature columns
        # (ADR-0010 gap, filed) — without this the three ablations would register as ONE trial.
        params = {**BEST, "feature_set": name}
        spec = TrialSpec(DID, "LightGBMModel", params, FEATURE_SPEC, LABEL_SPEC)
        res = study.run(df, LightGBMModel(params=BEST), feature_columns=feats, h_bars=H, trial=spec)
        aucs[name] = res.auc
        n_trials = store.count(DID)
        print(f"  trials={n_trials:d}  {name:14s} ({len(feats):2d} feats)  wAUC {res.auc:.4f}")

    full_excess = FULL_AUC - 0.5
    cal_excess = aucs["calendar_floor"] - 0.5
    mkt_excess = aucs["market_only"] - 0.5
    cal_share, mkt_share = cal_excess / full_excess, mkt_excess / full_excess
    print(f"\nfull excess over 0.5 = {full_excess:.4f} (EXP-001 anchor {FULL_AUC:.4f})")
    print(f"  calendar floor carries {cal_share:6.1%}  (AUC {aucs['calendar_floor']:.4f})")
    print(f"  market-only  carries {mkt_share:6.1%}  (AUC {aucs['market_only']:.4f})")

    # Pre-declared read (docs/experiments/exp-002-calendar-ablation.md)
    if cal_excess >= 0.5 * full_excess:
        verdict = "SUBSTANTIALLY BASE-RATE (calendar >= 50% of excess) -> back to FEATURES"
    elif aucs["market_only"] >= 0.5 + 0.75 * full_excess:
        verdict = "REAL CONDITIONAL EDGE (calendar low, market-only retains >=75%) -> Phase 5 costs"
    else:
        verdict = "AMBIGUOUS -> back to FEATURES"
    print(f"\nVERDICT: {verdict}")
    print(f"(trial count on {DID} this run: {store.count(DID)}; EXP-001 registered 12 more)")


if __name__ == "__main__":
    main()
