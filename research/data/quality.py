"""รายงานคุณภาพข้อมูลแท่งราคาที่ export จาก MT5

    .venv/bin/python -m research.data.quality data/mt5/XAUUSDc_M5.csv

ตรวจ 4 เรื่อง: ความครบถ้วน, ความต่อเนื่อง, ช่วงพักรายวัน (ยืนยัน timezone),
และสเปรดจริงย้อนหลัง — โดยเฉพาะสเปรดช่วงข่าวแรง ซึ่งเป็นตัวเลขที่ชี้เป็นชี้ตายของกลยุทธ์
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.backtest.news import news_blackout
from research.data.calendar import load_calendar
from research.data.loader import read_mt5_bars

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALENDAR = REPO_ROOT / "data" / "mt5" / "calendar.csv"
_PERCENTILES = (50, 90, 99, 99.9)


def report(csv_path: str | Path, calendar_csv: str | Path = DEFAULT_CALENDAR) -> None:
    bars = read_mt5_bars(csv_path)
    meta = bars.attrs["meta"]
    index = bars.index

    print(f"=== {meta['symbol']} {meta['timeframe']} ===")
    print(f"  แท่ง: {len(bars):,}   {index[0]} → {index[-1]}")
    print(f"  server: {meta['server']} (GMT offset {meta['server_gmt_offset_seconds']}s)")

    per_year = bars.groupby(index.year).size()
    print("\n  แท่งต่อปี:")
    for year, count in per_year.items():
        print(f"    {year}: {count:>9,}")

    print("\n=== ความต่อเนื่อง ===")
    diffs = pd.Series(index[1:] - index[:-1])
    step = diffs.mode().iloc[0]
    gaps = diffs[diffs > step]
    weekend = gaps[gaps >= pd.Timedelta("1 day")]
    intraday = gaps[(gaps > step) & (gaps < pd.Timedelta("1 day"))]
    print(f"  ระยะห่างปกติ: {step}")
    print(f"  ช่องว่างข้ามวัน/สุดสัปดาห์: {len(weekend):,} ครั้ง (ปกติ)")
    print(f"  ช่องว่างระหว่างวัน: {len(intraday):,} ครั้ง")
    if len(intraday):
        big = intraday[intraday > pd.Timedelta("2 hours")]
        print(f"    เกิน 2 ชม.: {len(big)} ครั้ง — ถ้าเยอะผิดปกติแปลว่าข้อมูลขาด")

    print("\n=== แท่งต่อชั่วโมง (เวลา server) — ยืนยันช่วงพักรายวัน ===")
    per_hour = bars.groupby(index.hour).size()
    quiet = per_hour[per_hour < per_hour.max() * 0.5]
    for hour, count in per_hour.items():
        mark = "  ← พัก/เบาบาง" if hour in quiet.index else ""
        print(f"    {hour:02d}:00  {count:>8,}{mark}")

    print("\n=== สเปรด (USD ต่อออนซ์) ===")
    spread = bars["spread_price"]
    _print_percentiles("  ทั้งหมด", spread)

    calendar_path = Path(calendar_csv)
    if not calendar_path.exists():
        print(f"\n  (ไม่พบ {calendar_path} — ข้ามการเทียบช่วงข่าว)")
        return

    events = load_calendar(calendar_path, ("USD",), "high")
    in_news = news_blackout(index, events["time"], minutes_before=30, minutes_after=30)
    print(f"\n  ข่าว USD High ในช่วงข้อมูล: {int(events['time'].between(index[0], index[-1]).sum()):,} ครั้ง")
    print(f"  แท่งที่อยู่ในช่วงข่าว: {in_news.sum():,} ({in_news.mean():.1%} ของทั้งหมด)")
    _print_percentiles("  นอกช่วงข่าว", spread[~in_news])
    _print_percentiles("  ในช่วงข่าว  ", spread[in_news])

    worst = spread.nlargest(5)
    print("\n  5 แท่งที่สเปรดกว้างที่สุด:")
    for ts, value in worst.items():
        print(f"    {ts}  ${value:.3f}{'  (ช่วงข่าว)' if in_news[index.get_loc(ts)] else ''}")


def _print_percentiles(label: str, spread: pd.Series) -> None:
    if not len(spread):
        print(f"{label}: (ไม่มีข้อมูล)")
        return
    values = np.percentile(spread, _PERCENTILES)
    parts = " | ".join(f"p{p:g} ${v:.3f}" for p, v in zip(_PERCENTILES, values))
    print(f"{label}: ต่ำสุด ${spread.min():.3f} | {parts} | สูงสุด ${spread.max():.3f}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    report(sys.argv[1])


if __name__ == "__main__":
    main()
