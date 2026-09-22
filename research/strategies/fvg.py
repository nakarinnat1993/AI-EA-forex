"""FVG v0 — Fair Value Gap ตามกฎใน journal/STRATEGY-ROUND3.md (ล็อกไว้ก่อนเขียนโค้ด)

ห้ามแก้กฎในไฟล์นี้โดยไม่แก้เอกสารกฎและบันทึกใน journal/ITERATIONS.md

ฝั่ง Buy (ฝั่ง Sell กลับด้าน) ตรวจที่แท่ง i ที่เพิ่งปิด:
  1. low[i] > high[i-2] และแท่ง i-1 เป็นแท่งเขียว → ช่องว่าง high[i-2] ถึง low[i]
  2. เทรนด์ timeframe ใหญ่เป็นขาขึ้น / แท่ง i อยู่ใน 07:00–16:00 server
  3. Buy Limit ที่ขอบบนของช่องว่าง (low[i])
  4. SL ใต้ min(low[i-2], low[i-1]) − buffer
  5. TP1/TP2 แบบเดียวกับ pullback v0 / ยกเลิกเมื่อปิดหลุดขอบล่างของช่องว่าง
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from research.strategies.pullback import _h1_zones, _levels
from research.strategies.smc_v0 import average_true_range, bar_duration, h1_bias

STRATEGY_NAME = "fvg_v0"


@dataclass(frozen=True)
class FvgParams:
    # ปรับได้ — 4 ตัว (ค่าเดียวกับ pullback v0)
    swing_len_h1: int = 5
    order_expiry: int = 36
    sl_buffer_atr: float = 0.1
    tp1_max_r: float = 2.0
    # กฎคงที่
    session_start_hour: int = 7
    session_end_hour: int = 16
    min_sl_distance: float = 3.0
    min_room_r: float = 1.0
    atr_period: int = 14

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def generate_signals(
    bars: pd.DataFrame, htf: pd.DataFrame, params: FvgParams = FvgParams()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(bars)
    open_ = bars["open"].to_numpy(float)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    close = bars["close"].to_numpy(float)
    hours = bars.index.hour.to_numpy()
    in_session = (hours >= params.session_start_hour) & (hours < params.session_end_hour)
    decided_at = (bars.index + bar_duration(bars.index)).as_unit("ns").asi8

    bias = h1_bias(bars.index, htf, params.swing_len_h1)
    zones = {1: _h1_zones(htf, params.swing_len_h1, "high"), -1: _h1_zones(htf, params.swing_len_h1, "low")}
    atr = average_true_range(bars, params.atr_period)

    side = np.zeros(n, dtype=np.int64)
    entry = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    tp2 = np.full(n, np.nan)
    expiry = np.full(n, np.nan)
    cancel = np.full(n, np.nan)
    setups: list[dict] = []

    for i in range(2, n):
        if not in_session[i]:
            continue
        if low[i] > high[i - 2] and close[i - 1] > open_[i - 1]:
            direction, gap_edge, far_edge = 1, low[i], high[i - 2]
            origin = min(low[i - 2], low[i - 1])
        elif high[i] < low[i - 2] and close[i - 1] < open_[i - 1]:
            direction, gap_edge, far_edge = -1, high[i], low[i - 2]
            origin = max(high[i - 2], high[i - 1])
        else:
            continue

        record = {"direction": direction, "gap_time": bars.index[i], "gap_edge": gap_edge, "gap_far_edge": far_edge}
        if bias[i] != direction:
            record["outcome"] = "against_bias"
            setups.append(record)
            continue
        outcome = _levels(gap_edge, origin, atr[i], close[i], direction, zones[direction], decided_at[i], params)
        if isinstance(outcome, str):
            record["outcome"] = outcome
        else:
            side[i] = direction
            entry[i], sl[i], tp[i], tp2[i] = gap_edge, outcome["sl"], outcome["tp1"], outcome["tp2"]
            cancel[i] = far_edge
            expiry[i] = params.order_expiry
            record.update(sl=sl[i], tp1=tp[i], tp2=tp2[i], outcome="signal")
        setups.append(record)

    signals = pd.DataFrame(
        {
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "tp2": tp2,
            "expiry_bars": expiry,
            "cancel_price": cancel,
        },
        index=bars.index,
    )
    return signals, pd.DataFrame(setups)
