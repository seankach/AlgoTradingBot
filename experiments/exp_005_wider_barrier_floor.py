"""EXP-005 (pre-registered): does the cost floor actually come down at (k=6, H=270, RTH)?

Committed WITH docs/experiments/exp-005-wider-barrier-floor.md before the run. Re-labels the
2021-2025 RTH-only series at k=6/H=270 and measures barrier, timeout, cost, breakeven and the
session-crossing fraction. No model, no features.

    python experiments/exp_005_wider_barrier_floor.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from qrp.labels.triple_barrier import TripleBarrier
from qrp.validation.trials import InMemoryTrialStore, Trial, TrialSpec

from datetime import UTC, datetime  # isort: skip

K, H = 6.0, 270
# New strategy under I3: k/H are the exit policy, so this is a new label spec + dataset_id.
LABEL_SPEC = "2026.07.16-k6h270rth"
DID = "exp-005-tsla-2021-2025-rth-k6h270"
FEATURE_SPEC = "2026.07.14-eventbar"

# Predicted cell (random-walk estimate) — what this run tests.
PRED_BARRIER_BPS, PRED_COST_BPS, PRED_BE1, PRED_BE2 = 80.8, 4.88, 0.530, 0.560


def _validated_rth() -> pl.DataFrame:
    files = sorted(Path("data/validated_bars").glob("symbol=TSLA/date=202[1-5]-*/*.parquet"))
    return (
        pl.scan_parquet(files)
        .filter(pl.col("session") == "RTH")
        .select("ts_utc", "session", "open", "high", "low", "close", "is_traded")
        .sort("ts_utc")
        .collect()
    )


def _sigma() -> pl.DataFrame:
    # The barrier volatility is unchanged (a feature); only k/H change. Reuse it as-is.
    files = sorted(Path("data/datasets").glob("symbol=TSLA/date=202[1-5]-*/dataset.parquet"))
    return (
        pl.scan_parquet(files)
        .select(pl.col("decision_ts").alias("ts_utc"), "sigma")
        .drop_nulls()
        .unique(subset=["ts_utc"])
        .collect()
    )


def _rth_spread_bps() -> float:
    f = sorted(Path("data/raw_snapshots").glob("symbol=TSLA/date=202[1-5]-*/*.parquet"))
    ba = (
        pl.scan_parquet(f)
        .filter(pl.col("what_to_show") == "BID_ASK")
        .select("ts_utc", "open", "close")
        .unique(subset=["ts_utc"])
        .with_columns(
            (
                (pl.col("close") - pl.col("open")) / ((pl.col("close") + pl.col("open")) / 2) * 1e4
            ).alias("sp")
        )
        .filter((pl.col("sp") > 0) & (pl.col("sp") < 200))
    )
    v = pl.scan_parquet(
        sorted(Path("data/validated_bars").glob("symbol=TSLA/date=202[1-5]-*/*.parquet"))
    ).select("ts_utc", "session")
    return float(
        ba.join(v, on="ts_utc", how="inner")
        .filter(pl.col("session") == "RTH")
        .select(pl.col("sp").median())
        .collect()
        .item()
    )


def main() -> None:
    bars, sigma = _validated_rth(), _sigma()
    print(f"EXP-005: re-labelling {bars.height:,} RTH bars at k={K}, H={H}\n", flush=True)
    lab = TripleBarrier(k=K, h_bars=H).generate(bars, sigma)
    print(f"labels produced: {lab.height:,}")

    resolved = lab.filter(pl.col("label") != 0)
    timeout_rate = float((lab.get_column("label") == 0).mean())
    barrier = float((resolved.get_column("gross_return").abs() * 1e4).mean())
    crossed = float(
        (
            resolved.get_column("exit_ts").dt.date() != resolved.get_column("entry_ts").dt.date()
        ).mean()
    )

    spread = _rth_spread_bps()
    cost = 0.5 * spread * 2 + 1.0 * 2 + (0.0035 / 250 * 1e4) * 2 + 0.2 * 2
    be1 = 0.5 * (1 + cost / barrier)
    be2 = 0.5 * (1 + 2 * cost / barrier)

    print("\n--- MEASURED vs PREDICTED ---")
    print(f"  barrier |gross_return| : {barrier:6.2f} bps   (predicted {PRED_BARRIER_BPS})")
    print(f"  RTH spread (median)    : {spread:6.2f} bps")
    print(f"  round-trip cost @1x    : {cost:6.2f} bps   (predicted {PRED_COST_BPS})")
    print(f"  timeout rate           : {timeout_rate:6.1%}   (today at k=2,H=30: 11.2%)")
    print(f"  breakeven @1x          : {be1:6.1%}   (predicted {PRED_BE1:.1%})")
    print(f"  breakeven @2x (§8 bar) : {be2:6.1%}   (predicted {PRED_BE2:.1%})")
    print(f"\n  session-crossing exits : {crossed:6.1%}  <- multi-day swing, and barrier-fill")
    print("                                    is optimistic across an overnight gap")

    store = InMemoryTrialStore()
    store.register(
        Trial(
            trial_hash=TrialSpec(
                DID, "TripleBarrier-relabel", {"k": K, "h_bars": H}, FEATURE_SPEC, LABEL_SPEC
            ).hash(["<relabel-no-features>"]),
            dataset_id=DID,
            model_class="TripleBarrier-relabel",
            auc=float("nan"),
            registered_at=datetime.now(UTC),
        )
    )
    print(f"\n  registered as a trial on new dataset_id {DID} (count {store.count(DID)})")

    ok = 0.55 <= be2 <= 0.57
    print(f"\nVERDICT: {'DOOR UNBOLTED' if ok else 'FLOOR MOVED — do not proceed to features'}")
    where = "lands in" if ok else "is OUTSIDE"
    print(f"  2x breakeven {be2:.1%} {where} the pre-declared 55-57% band")
    if ok:
        print("  -> a SEPARATE, pre-registered FEATURE experiment is authorised.")
        print("     This says NOTHING about whether signal exists at this horizon.")


if __name__ == "__main__":
    main()
