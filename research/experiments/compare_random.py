"""รันกลยุทธ์ (ค่าเริ่มต้น ไม่จูน) เทียบกับเข้าไม้สุ่มที่คงรูปทรงไม้เดียวกัน — ช่วง dev เท่านั้น

    .venv/bin/python -m research.experiments.compare_random --strategy smc_v0.1 --source dukascopy
    .venv/bin/python -m research.experiments.compare_random --strategy asian_breakout_v0 --source dukascopy

ทุกครั้งที่รัน = 1 trial ของกลยุทธ์ใน reports/runs.jsonl
การรันคู่เทียบสุ่มไม่นับเป็น trial (เป็นตัวอย่างสำหรับวัดว่าผลของกลยุทธ์ต่างจากดวงแค่ไหน)
เกณฑ์ผ่านที่ล็อกไว้ล่วงหน้า: journal/DECISIONS.md 2026-09-17
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from research.backtest import (
    assert_causal,
    blackout_for_bars,
    load_cost_config,
    load_risk_config,
    run_backtest,
    summarize,
    write_report,
)
from research.data.loader import load_research_bars
from research.strategies import REGISTRY, random_matched_signals

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "config"
CALENDAR = REPO_ROOT / "data" / "mt5" / "calendar.csv"
SOURCES = {
    "exness": (REPO_ROOT / "data" / "mt5" / "XAUUSDc_M5.csv", REPO_ROOT / "data" / "mt5" / "XAUUSDc_H1.csv"),
    "dukascopy": (REPO_ROOT / "data" / "dukascopy" / "XAUUSD_M5.csv", REPO_ROOT / "data" / "dukascopy" / "XAUUSD_H1.csv"),
}
RANDOM_RUNS = 50
THAI_OFFSET = pd.Timedelta(hours=7)  # server Exness และ Dukascopy = UTC

# เกณฑ์ผ่านขั้น dev (DECISIONS 2026-09-17) — แก้ตรงนี้ต้องแก้เอกสารด้วย
MIN_TRADES = 100
MAX_RANDOM_SHARE = 0.05
MIN_POSITIVE_YEAR_SHARE = 0.60
MIN_TRADES_PER_YEAR = 10
MAX_SINGLE_YEAR_PROFIT_SHARE = 0.50
MAX_DRAWDOWN_PCT = 25.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(REGISTRY), required=True)
    parser.add_argument("--source", choices=sorted(SOURCES), default="dukascopy")
    args = parser.parse_args()

    generate, params_class, hours_of = REGISTRY[args.strategy]
    params = params_class()
    session_start, session_end = hours_of(params)

    m5_path, h1_path = SOURCES[args.source]
    m5 = load_research_bars(m5_path)
    h1 = load_research_bars(h1_path)
    spec, costs = load_cost_config(CONFIG / "costs_exness_xauusdc.json")
    risk = load_risk_config(CONFIG / "risk.json")
    blackout = blackout_for_bars(m5.index, CALENDAR)
    print(f"{args.strategy} | source={args.source} | dev: {m5.index[0]} → {m5.index[-1]}  ({len(m5):,} แท่ง M5)", flush=True)

    print("ตรวจ look-ahead ...", flush=True)
    assert_causal(lambda frame: generate(frame, h1, params)[0], m5, n_checks=3, min_bars=20_000)
    print("  ผ่าน", flush=True)

    signals, setups = generate(m5, h1, params)
    result = run_backtest(m5, signals, spec, costs, risk, blackout=blackout)
    summary = summarize(result)

    baseline = []
    for seed in range(RANDOM_RUNS):
        random_signals = random_matched_signals(m5, signals, seed, session_start, session_end)
        s = summarize(run_backtest(m5, random_signals, spec, costs, risk, blackout=blackout))
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
    folds = _yearly_folds(result)
    verdict = _verdict(summary, comparison, folds)
    funnel = setups["outcome"].value_counts().to_dict() if len(setups) else {}

    report_path = write_report(
        result,
        summary,
        strategy=args.strategy,
        params=params.as_dict(),
        data_info={"source": args.source, "from": str(m5.index[0]), "to": str(m5.index[-1]), "bars": len(m5)},
        extra={"random_baseline": comparison, "yearly_folds": folds, "setup_funnel": funnel, "verdict": verdict},
    )
    if len(setups):
        export = setups.copy()
        for column in export.select_dtypes(include="datetime").columns:
            export[f"{column}_thai"] = export[column] + THAI_OFFSET
        export.to_csv(report_path.with_name(report_path.stem + "_setups.csv"), index=False)

    _print(summary, comparison, folds, funnel, verdict, report_path)


def _compare(summary: dict, baseline: pd.DataFrame) -> dict:
    out = {"runs": len(baseline)}
    for metric in ("expectancy_r", "profit_factor", "win_rate", "return_pct"):
        values = baseline[metric].dropna().to_numpy(float)
        value = summary.get(metric)
        out[metric] = {
            "strategy": value,
            "random_median": float(np.median(values)) if len(values) else None,
            "random_p05": float(np.percentile(values, 5)) if len(values) else None,
            "random_p95": float(np.percentile(values, 95)) if len(values) else None,
            # สัดส่วนรอบสุ่มที่ทำได้ดีกว่าหรือเท่ากลยุทธ์ — ยิ่งต่ำยิ่งแปลว่ากลยุทธ์ต่างจากดวงจริง
            "share_random_at_least_as_good": float((values >= value).mean()) if len(values) and value is not None else None,
        }
    out["random_n_trades_median"] = float(baseline["n_trades"].median())
    return out


def _yearly_folds(result) -> list[dict]:
    if not result.trades:
        return []
    frame = pd.DataFrame(
        {
            "year": [t.entry_time.year for t in result.trades],
            "r": [t.r_multiple for t in result.trades],
            "pnl": [t.pnl_usd for t in result.trades],
        }
    )
    return [
        {
            "year": int(year),
            "n": int(len(group)),
            "expectancy_r": float(group["r"].mean()),
            "win_rate": float((group["pnl"] > 0).mean()),
            "pnl_usd": float(group["pnl"].sum()),
        }
        for year, group in frame.groupby("year")
    ]


def _verdict(summary: dict, comparison: dict, folds: list[dict]) -> dict:
    n = summary["n_trades"]
    expectancy = summary.get("expectancy_r")
    random_share = comparison["expectancy_r"]["share_random_at_least_as_good"]
    counted = [f for f in folds if f["n"] >= MIN_TRADES_PER_YEAR]
    positive_share = (sum(f["expectancy_r"] > 0 for f in counted) / len(counted)) if counted else None
    total_profit = sum(f["pnl_usd"] for f in folds)
    best_year_share = (max(f["pnl_usd"] for f in folds) / total_profit) if folds and total_profit > 0 else None
    drawdown = abs(summary.get("max_drawdown_pct") or 0.0)

    checks = {
        "trades_at_least_100": n >= MIN_TRADES,
        "expectancy_positive": expectancy is not None and expectancy > 0,
        "beats_random": random_share is not None and random_share <= MAX_RANDOM_SHARE,
        "positive_in_60pct_of_years": positive_share is not None and positive_share >= MIN_POSITIVE_YEAR_SHARE,
        "no_year_over_50pct_of_profit": best_year_share is not None and best_year_share <= MAX_SINGLE_YEAR_PROFIT_SHARE,
        "drawdown_within_25pct": drawdown <= MAX_DRAWDOWN_PCT,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "values": {
            "n_trades": n,
            "expectancy_r": expectancy,
            "random_share": random_share,
            "positive_year_share": positive_share,
            "best_year_profit_share": best_year_share,
            "max_drawdown_pct": drawdown,
        },
    }


def _print(summary, comparison, folds, funnel, verdict, report_path) -> None:
    print("\n=== ผลกลยุทธ์ ===")
    for key in ("n_trades", "win_rate", "expectancy_r", "profit_factor", "return_pct", "max_drawdown_pct", "avg_hold_minutes"):
        print(f"  {key}: {summary.get(key)}")
    print(f"  skipped: {summary['skipped_signals']}")
    print(f"  costs: {summary.get('costs_usd')}")
    for warning in summary["warnings"]:
        print(f"  ⚠ {warning}")

    print(f"\n=== เทียบเข้าไม้สุ่ม {comparison['runs']} รอบ (ไม้เฉลี่ย {comparison['random_n_trades_median']:.0f}) ===")
    for metric in ("expectancy_r", "profit_factor", "win_rate", "return_pct"):
        c = comparison[metric]
        print(
            f"  {metric:<14} กลยุทธ์ {c['strategy']}  | สุ่ม median {c['random_median']}  "
            f"[p5 {c['random_p05']}, p95 {c['random_p95']}]  | สุ่มดีกว่า/เท่า {c['share_random_at_least_as_good']}"
        )

    print("\n=== แยกรายปี ===")
    for fold in folds:
        print(f"  {fold['year']}  n={fold['n']:<4} expectancy {fold['expectancy_r']:+.3f}R  WR {fold['win_rate']:.0%}  ${fold['pnl_usd']:+.2f}")

    print(f"\n=== setup ที่เจอ → ผลลัพธ์ ===\n  {funnel}")
    print(f"\n=== เกณฑ์ผ่านขั้น dev: {'ผ่าน' if verdict['passed'] else 'ไม่ผ่าน'} ===")
    for name, ok in verdict["checks"].items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"  {verdict['values']}")
    print(f"\nรายงาน: {report_path}")


if __name__ == "__main__":
    main()
