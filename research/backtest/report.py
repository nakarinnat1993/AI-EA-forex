"""เขียนผล backtest ลง reports/ และนับจำนวน trial อัตโนมัติ

ทุกครั้งที่เรียก write_report จะต่อท้าย reports/runs.jsonl หนึ่งบรรทัด
จำนวน run ต่อกลยุทธ์คือ "จำนวนครั้งที่เราลองเสี่ยงดวง" ต้องใช้หักส่วนลดผลลัพธ์ (deflated Sharpe)
ห้ามลบบรรทัดใน runs.jsonl แม้ run นั้นผลแย่
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from .engine import BacktestResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]


def write_report(
    result: BacktestResult,
    summary: dict,
    strategy: str,
    params: dict,
    data_info: dict,
    out_dir: Path = DEFAULT_REPORTS_DIR,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}_{strategy}_{params_hash(params)}"

    report = {
        "run_id": run_id,
        "strategy": strategy,
        "params": params,
        "data": data_info,
        "summary": summary,
    }
    report_path = out_dir / f"{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    if result.trades:
        rows = [{**asdict(t), "pnl_usd": t.pnl_usd, "r_multiple": t.r_multiple} for t in result.trades]
        pd.DataFrame(rows).to_csv(out_dir / f"{run_id}_trades.csv", index=False)

    registry_line = {
        "run_id": run_id,
        "strategy": strategy,
        "params": params,
        "data_from": data_info.get("from"),
        "data_to": data_info.get("to"),
        "n_trades": summary.get("n_trades"),
        "expectancy_r": summary.get("expectancy_r"),
        "profit_factor": summary.get("profit_factor"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
    }
    with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(registry_line, ensure_ascii=False, default=str) + "\n")
    return report_path


def count_trials(strategy: str, out_dir: Path = DEFAULT_REPORTS_DIR) -> int:
    registry = out_dir / "runs.jsonl"
    if not registry.exists():
        return 0
    with registry.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip() and json.loads(line)["strategy"] == strategy)
