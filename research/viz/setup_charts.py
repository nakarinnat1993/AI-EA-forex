"""วาดกราฟ setup ที่กลยุทธ์เจอ เพื่อตรวจด้วยตาว่าโค้ดทำงานตรงกับกฎที่เขียนไว้

    .venv/bin/python -m research.viz.setup_charts <setups.csv> "2026-04-21 07:15" ["..."]

อาร์กิวเมนต์เวลาคือ break_time (เวลา server) ของ setup ที่ต้องการดู
รูปถูกบันทึกไว้ที่ reports/charts/ — ป้ายในรูปเป็นภาษาอังกฤษ เพราะฟอนต์ของ matplotlib ไม่มีอักษรไทย
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research.data.loader import load_research_bars
from research.smc import market_structure, reference_levels, swing_points
from research.strategies import SmcV0Params

REPO_ROOT = Path(__file__).resolve().parents[2]
M5_PATH = REPO_ROOT / "data" / "mt5" / "XAUUSDc_M5.csv"
OUT_DIR = REPO_ROOT / "reports" / "charts"


def render(
    setups_csv: str | Path,
    break_times: list[str],
    m5_path: str | Path = M5_PATH,
    bars_before: int = 60,
    bars_after: int = 40,
) -> list[Path]:
    setups = pd.read_csv(setups_csv, parse_dates=["sweep_time", "break_time", "block_time"])
    m5 = load_research_bars(m5_path)
    params = SmcV0Params()
    swings = swing_points(m5, params.swing_len_m5)
    structure = market_structure(m5, swings)
    levels = reference_levels(m5, params.asian_start_hour, params.asian_end_hour)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    paths = []
    for text in break_times:
        when = pd.Timestamp(text)
        rows = setups[setups["break_time"] == when]
        if rows.empty:
            print(f"no setup with break_time = {when}")
            continue
        paths.append(_render_one(m5, swings, structure, levels, rows.iloc[0], bars_before, bars_after))
    return paths


def _render_one(m5, swings, structure, levels, setup, bars_before, bars_after) -> Path:
    j = m5.index.get_loc(setup["break_time"])
    lo = max(0, j - bars_before)
    hi = min(len(m5), j + bars_after)
    window = m5.iloc[lo:hi]
    x = np.arange(len(window))

    fig, ax = plt.subplots(figsize=(16, 8))
    up = window["close"] >= window["open"]
    ax.vlines(x, window["low"], window["high"], color="black", linewidth=0.7)
    body_low = np.minimum(window["open"], window["close"])
    body_height = np.maximum(np.abs(window["close"] - window["open"]), 0.02)
    ax.bar(x, body_height, bottom=body_low, width=0.6, color=np.where(up, "#2e9e5b", "#d9534f"), edgecolor="black", linewidth=0.4)

    def mark_time(ts, color, label):
        if pd.notna(ts) and ts in window.index:
            ax.axvline(window.index.get_loc(ts), color=color, linestyle="--", linewidth=1, label=label)

    mark_time(setup["sweep_time"], "purple", "sweep confirmed")
    mark_time(setup["break_time"], "blue", "structure break")

    session_col, day_col = ("session_low", "prev_day_low") if setup["direction"] == 1 else ("session_high", "prev_day_high")
    at_sweep = levels.loc[setup["sweep_time"]]
    ax.axhline(at_sweep[session_col], color="orange", linewidth=1.2, label=f"asian {session_col.split('_')[1]} {at_sweep[session_col]:.2f}")
    if np.isfinite(at_sweep[day_col]):
        ax.axhline(at_sweep[day_col], color="brown", linewidth=1.2, linestyle=":", label=f"prev day {day_col.split('_')[2]} {at_sweep[day_col]:.2f}")

    broken = structure["level"].iloc[j]
    if np.isfinite(broken):
        ax.axhline(broken, color="blue", linewidth=0.8, linestyle="-.", label=f"broken swing {broken:.2f}")

    pivot_highs = swings["is_swing_high"].iloc[lo:hi].to_numpy()
    pivot_lows = swings["is_swing_low"].iloc[lo:hi].to_numpy()
    ax.scatter(x[pivot_highs], window["high"][pivot_highs] + 0.5, marker="v", color="blue", s=18, label="swing high")
    ax.scatter(x[pivot_lows], window["low"][pivot_lows] - 0.5, marker="^", color="blue", s=18, label="swing low")

    if pd.notna(setup["block_time"]) and setup["block_time"] in window.index:
        b = window.index.get_loc(setup["block_time"])
        ax.add_patch(
            plt.Rectangle(
                (b - 0.5, setup["block_bottom"]),
                hi - lo - b,
                setup["block_top"] - setup["block_bottom"],
                color="gold",
                alpha=0.25,
                label="order block",
            )
        )
    for name, color in (("entry", "black"), ("sl", "red"), ("tp", "green")):
        if np.isfinite(setup[name]):
            ax.axhline(setup[name], color=color, linewidth=1, label=f"{name} {setup[name]:.2f}")

    ticks = x[:: max(1, len(x) // 12)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([window.index[i].strftime("%m-%d %H:%M") for i in ticks], rotation=30)
    side = "BUY" if setup["direction"] == 1 else "SELL"
    ax.set_title(f"{side} setup - break {setup['break_time']} (server UTC) - outcome: {setup['outcome']} - source: {setup['sweep_source']}")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)

    path = OUT_DIR / f"setup_{setup['break_time']:%Y%m%d_%H%M}_{side.lower()}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)
    return path


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    for path in render(sys.argv[1], sys.argv[2:]):
        print(path)


if __name__ == "__main__":
    main()
