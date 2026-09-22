"""เปิด holdout ครั้งเดียว — ประเมินกลยุทธ์ตามเกณฑ์ที่ล็อกไว้ใน DECISIONS 2026-09-19

    .venv/bin/python -m research.experiments.holdout_eval \
        --strategy pullback_v0_volfilter --timeframe M5 --bias-tf M15 --reason "..."

open_holdout() บันทึกการเปิดลง journal/HOLDOUT_LOG.md และจะไม่ยอมเปิดซ้ำ
หลังเปิดแล้วจึงอ่านข้อมูลเต็มเพื่อใช้เป็นประวัติก่อนหน้า (warmup) ของตัวชี้วัด
แต่นับเฉพาะ signal ที่เกิดใน holdout และเริ่มทุนใหม่ที่ต้น holdout
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from research.backtest import (
    blackout_for_bars,
    load_cost_config,
    load_risk_config,
    run_backtest,
    summarize,
    write_report,
)
from research.data.loader import open_holdout, read_mt5_bars
from research.experiments.compare_random import CALENDAR, CONFIG, DATA_FILES, RANDOM_RUNS, REPO_ROOT, _compare
from research.strategies import REGISTRY, random_matched_signals

EXNESS_M5 = REPO_ROOT / "data" / "mt5" / "XAUUSDc_M5.csv"
_RESAMPLE = {"open": "first", "high": "max", "low": "min", "close": "last"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(REGISTRY), required=True)
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--bias-tf", default="H1")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()

    files = DATA_FILES["dukascopy"]
    holdout = open_holdout(files[args.timeframe], args.reason)
    start = holdout.index[0]
    print(f"เปิด holdout แล้ว (บันทึกใน journal/HOLDOUT_LOG.md) เริ่ม {start}", flush=True)

    label = f"{args.strategy}@{args.timeframe}/bias{args.bias_tf}"
    primary = _evaluate(
        args.strategy, read_mt5_bars(files[args.timeframe]), read_mt5_bars(files[args.bias_tf]), start,
        label, "dukascopy",
    )

    exness = read_mt5_bars(EXNESS_M5)
    exness_bias = exness[["open", "high", "low", "close"]].resample(args.bias_tf.replace("M", "") + "min").agg(_RESAMPLE).dropna()
    _evaluate(args.strategy, exness, exness_bias, start, label, "exness (ตรวจซ้ำ ไม่ใช่เกณฑ์)")

    print(f"\n=== ผลตัดสิน holdout (ข้อมูลหลัก): {'ผ่าน' if primary['passed'] else 'ไม่ผ่าน'} ===")
    for name, ok in primary["checks"].items():
        print(f"  {'✓' if ok else '✗'} {name}")


def _evaluate(strategy: str, entry_bars, bias_bars, start, label: str, source: str) -> dict:
    generate, params, hours_of = REGISTRY[strategy]
    session_start, session_end = hours_of(params)
    signals, _ = generate(entry_bars, bias_bars, params)
    in_holdout = entry_bars.index >= start
    bars = entry_bars[in_holdout]
    signals = signals[in_holdout]

    spec, costs = load_cost_config(CONFIG / "costs_exness_xauusdc.json")
    risk = load_risk_config(CONFIG / "risk.json")
    blackout = blackout_for_bars(bars.index, CALENDAR)
    result = run_backtest(bars, signals, spec, costs, risk, blackout=blackout)
    summary = summarize(result)

    baseline = []
    for seed in range(RANDOM_RUNS):
        random_signals = random_matched_signals(bars, signals, seed, session_start, session_end)
        s = summarize(run_backtest(bars, random_signals, spec, costs, risk, blackout=blackout))
        baseline.append(
            {
                "seed": seed,
                "n_trades": s["n_trades"],
                "expectancy_r": s.get("expectancy_r"),
                "profit_factor": s.get("profit_factor"),
                "win_rate": s.get("win_rate"),
                "return_pct": s["return_pct"],
            }
        )
    comparison = _compare(summary, pd.DataFrame(baseline))
    expectancy = summary.get("expectancy_r")
    random_median = comparison["expectancy_r"]["random_median"]
    checks = {
        "at_least_one_trade": summary["n_trades"] >= 1,
        "expectancy_positive": expectancy is not None and expectancy > 0,
        "not_below_random_median": expectancy is not None and random_median is not None and expectancy >= random_median,
    }
    verdict = {"passed": all(checks.values()), "checks": checks}

    write_report(
        result,
        summary,
        strategy=f"{label}@holdout-{source.split()[0]}",
        params=params.as_dict(),
        data_info={"source": source, "from": str(bars.index[0]), "to": str(bars.index[-1]), "bars": len(bars)},
        extra={"random_baseline": comparison, "verdict": verdict},
    )

    print(f"\n=== {source}: {bars.index[0]} → {bars.index[-1]} ===")
    for key in ("n_trades", "win_rate", "expectancy_r", "profit_factor", "return_pct", "max_drawdown_pct"):
        print(f"  {key}: {summary.get(key)}")
    print(f"  skipped: {summary['skipped_signals']}")
    c = comparison["expectancy_r"]
    print(f"  สุ่ม: median {c['random_median']} [p5 {c['random_p05']}, p95 {c['random_p95']}] | สุ่มดีกว่า/เท่า {c['share_random_at_least_as_good']}")
    if result.trades:
        for t in result.trades:
            print(
                f"    {t.entry_time}  {'BUY ' if t.side > 0 else 'SELL'}  {t.exit_reason:<10} "
                f"{t.r_multiple:+.2f}R  ${t.pnl_usd:+.2f}"
            )
    return verdict


if __name__ == "__main__":
    main()
