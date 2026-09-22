"""เทียบการตัดสินใจของ ForwardTestEA (Strategy Tester) กับโค้ด Python บนแท่งเดียวกัน

    .venv/bin/python -m research.experiments.ea_parity --magic 260921 --strategy pullback_v0 --timeframe M5 --bias-tf M15

EA เขียน log ที่แท่งใหม่เปิด (ประเมินแท่งที่เพิ่งปิด) → แท่ง signal = เวลาใน log ปัดลง − 1 แท่ง
EA ประเมินเฉพาะตอนไม่มีคำสั่งรอหรือไม้ค้าง จึงเทียบเฉพาะแท่งที่ EA ได้ตัดสินใจจริง
ข้อมูลฝั่ง Python = ไฟล์ Exness ที่ export จากเซิร์ฟเวอร์เดียวกับที่ Strategy Tester ใช้
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from research.data.loader import read_mt5_bars
from research.strategies import REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTER_FILES = (
    Path.home()
    / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5"
    / "Tester/Agent-127.0.0.1-3000/MQL5/Files/AI-EA"
)
EXNESS_M5 = REPO_ROOT / "data" / "mt5" / "XAUUSDc_M5.csv"
SETUP_OUTCOMES = {"signal", "signal_no_split", "no_room", "sl_too_tight", "price_inside_zone", "sl_on_wrong_side", "no_structure"}
PRICE_TOLERANCE = 0.01
_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--magic", type=int, required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--bias-tf", default="M15")
    args = parser.parse_args()

    bar = pd.Timedelta(minutes=_MINUTES[args.timeframe])
    ea = pd.read_csv(TESTER_FILES / f"forward_signals_{args.magic}.csv")
    ea["time"] = pd.to_datetime(ea["time_server"], format="%Y.%m.%d %H:%M:%S")
    ea["bar"] = ea["time"].dt.floor(f"{_MINUTES[args.timeframe]}min") - bar
    ea["outcome"] = ea["outcome"].replace({"signal_no_split": "signal"})
    decisions = ea[ea["outcome"].isin(SETUP_OUTCOMES)].copy()

    entry = _exness_bars(args.timeframe)
    bias = _exness_bars(args.bias_tf)
    print(f"ข้อมูล Python: entry {args.timeframe} {entry.index[0]} → | bias {args.bias_tf} {bias.index[0]} →")
    generate, params, _ = REGISTRY[args.strategy]
    _, setups = generate(entry, bias, params)
    time_col = "break_time" if "break_time" in setups else "gap_time"
    py = setups.set_index(time_col)
    py = py[~py.index.duplicated(keep="first")]

    first, last = decisions["bar"].min(), decisions["bar"].max()
    print(f"EA ตัดสินใจ {len(decisions)} ครั้ง ({first} → {last}) | signal {int((decisions.outcome == 'signal').sum())}")

    matched = decisions.join(py, on="bar", rsuffix="_py", how="left")
    found = matched["outcome_py"].notna()
    same_outcome = found & (matched["outcome"] == matched["outcome_py"])
    print(f"  Python มีการตัดสินใจที่แท่งเดียวกัน: {found.mean():.1%}")
    print(f"  ผลตรงกัน (signal/no_room/...): {same_outcome.sum()}/{len(matched)} = {same_outcome.mean():.1%}")

    both_signal = matched[(matched["outcome"] == "signal") & (matched["outcome_py"] == "signal")]
    if len(both_signal):
        for ea_col, py_col in (("entry", "level"), ("sl", "sl_py"), ("tp1", "tp1_py"), ("tp2", "tp2_py")):
            if py_col in both_signal:
                diff = (both_signal[ea_col] - both_signal[py_col]).abs()
                print(f"  {ea_col:<5} ต่างเฉลี่ย {diff.mean():.4f}  สูงสุด {diff.max():.4f}  ตรงกัน(±{PRICE_TOLERANCE}) {(diff <= PRICE_TOLERANCE).mean():.1%}")

    monthly = pd.DataFrame({"month": matched["bar"].dt.to_period("M"), "same": same_outcome})
    rate = monthly.groupby("month")["same"].agg(["mean", "size"])
    print("\n  ผลตรงกันรายเดือน:")
    print("   " + " | ".join(f"{m} {r['mean']:.0%} ({int(r['size'])})" for m, r in rate.iterrows()))

    mismatch = matched[~same_outcome]
    print("\n  ไม่ตรง — EA → Python:")
    print(mismatch.groupby(["outcome", "outcome_py"], dropna=False).size().to_string())
    print("\n  ตัวอย่าง 10 จุดที่ไม่ตรง:")
    cols = ["bar", "side", "outcome", "outcome_py", "entry", "level", "sl", "sl_py", "tp1", "tp1_py"]
    print(mismatch[[c for c in cols if c in mismatch]].head(10).to_string(index=False))

    window = py[(py.index >= first) & (py.index <= last)]
    py_signals = window[window["outcome"] == "signal"]
    ea_bars = set(decisions["bar"])
    unseen = py_signals[~py_signals.index.isin(ea_bars)]
    print(f"\n  signal ฝั่ง Python ในช่วงเดียวกัน {len(py_signals)} | EA ไม่ได้ประเมินแท่งนั้น {len(unseen)}"
          " (ส่วนใหญ่ควรเป็นช่วงที่ EA มีคำสั่งรอ/ไม้ค้างอยู่)")


def _exness_bars(timeframe: str) -> pd.DataFrame:
    """ใช้ไฟล์ที่ export จาก Exness ตรง ๆ ถ้ามี (ย้อนหลังยาวเท่าที่ EA เห็น) ไม่มีค่อยรวมจาก M5"""
    exported = REPO_ROOT / "data" / "mt5" / f"XAUUSDc_{timeframe}.csv"
    if exported.exists() and read_mt5_bars(exported).shape[0] > 0:
        return read_mt5_bars(exported)
    m5 = read_mt5_bars(EXNESS_M5)
    return m5[["open", "high", "low", "close"]].resample(f"{_MINUTES[timeframe]}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


if __name__ == "__main__":
    main()
