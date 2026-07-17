"""EXP-004 (pre-registered): is the edge concentrated in a tradeable tail?

Committed WITH docs/experiments/exp-004-tail-concentration.md before the run. Breakevens below are
derived from measured quantities + the frozen config/costs.yaml, not chosen.

    python experiments/exp_004_tail_concentration.py
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
H, STRIDE = 30, 15
DID = "exp-001-tsla-2021-2025"
FEATURE_SPEC = LABEL_SPEC = "2026.07.14-eventbar"
BEST = {"num_leaves": 31, "learning_rate": 0.03, "min_child_samples": 200}
QUANTILES = [0.10, 0.01]

# Breakevens: measured barrier 20.03 bps mean; frozen costs 6.15 bps round-trip at 1x.
BARRIER_BPS = 20.03
COST_1X_BPS = 6.15
BREAKEVEN_1X = 0.5 * (1 + COST_1X_BPS / BARRIER_BPS)  # 0.654
BREAKEVEN_2X = 0.5 * (1 + 2 * COST_1X_BPS / BARRIER_BPS)  # 0.807


def _load() -> pl.DataFrame:
    files = sorted(Path("data/datasets").glob("symbol=TSLA/date=*/dataset.parquet"))
    df = (
        pl.scan_parquet(files)
        .filter(pl.col("decision_ts").dt.year().is_between(2021, 2025))
        .sort("decision_ts")
        .collect()
        .gather_every(STRIDE)
        .drop_nulls(MARKET + CALENDAR)
    )
    return df.with_columns(pl.col("minute_of_day").cast(pl.Float64).alias("tod_bucket"))


def main() -> None:
    df = _load()
    store = InMemoryTrialStore()
    study = Study(
        PurgedCPCV(6, 2), trial_store=store, inner_val_frac=0.2, bucket_column="tod_bucket"
    )
    print(f"EXP-004: {df.height:,} rows; market-only model (EXP-003 scoping)")
    print(f"breakeven accuracy: 1x {BREAKEVEN_1X:.3f}   2x {BREAKEVEN_2X:.3f}")
    print(f"(barrier {BARRIER_BPS} bps, round-trip cost {COST_1X_BPS} bps @1x, frozen config)\n")

    results: dict[str, dict[float, float]] = {}
    for arm, within in (("global", False), ("within_bucket", True)):
        spec = TrialSpec(DID, f"LightGBMModel/tail-{arm}", BEST, FEATURE_SPEC, LABEL_SPEC)
        acc = study.tail_accuracies(
            df,
            LightGBMModel(params=BEST),
            feature_columns=MARKET,
            h_bars=H,
            quantiles=QUANTILES,
            within_bucket=within,
            trial=spec,
        )
        results[arm] = acc
        n_t = store.count(DID)
        for q in QUANTILES:
            v = "CLEARS 1x" if acc[q] >= BREAKEVEN_1X else "below 1x breakeven"
            print(f"  trials={n_t}  {arm:13s} q={q:.2f}  accuracy {acc[q]:.4f}  {v}")

    best = max(max(v.values()) for v in results.values())
    print(f"\nbest tail accuracy: {best:.4f}  vs 1x breakeven {BREAKEVEN_1X:.3f}")
    if best >= BREAKEVEN_1X:
        print(
            "VERDICT: concentrated edge survives the arithmetic -> scope the full spread-lake gate"
        )
        print("         (PROVISIONAL until the account's real commission schedule is supplied, §8)")
    else:
        print("VERDICT: signal present but NOT tradeable -> DEATH-AT-COST -> new features.")
        print(
            "         Complete answer: signal-vs-tradeable settled. Do NOT build the spread lake."
        )


if __name__ == "__main__":
    main()
