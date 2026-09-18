"""Asian range breakout v0 — คู่เทียบที่ไม่ใช่ SMC (DECISIONS 2026-09-15 และ 2026-09-17)

กลไก: ทองมักแกว่งแคบช่วงเอเชีย แล้วเริ่มมีทิศทางเมื่อ London เปิด

กฎ (ฝั่ง Buy, ฝั่ง Sell กลับด้าน):
  1. Asian range = high/low ของแท่ง 00:00–07:00 server ของวันนี้
  2. ระหว่าง 07:00–12:00 server หาแท่ง M5 แรกที่ **ปิด** นอก Asian range
  3. ถ้าทะลุขึ้นและ bias H1 เป็นขาขึ้น → Buy (ใช้ bias ตัวเดียวกับ SMC เพื่อให้เทียบกันได้)
  4. เข้าราคาตลาดที่แท่งถัดไป / SL = กึ่งกลาง Asian range / TP = tp_r × ระยะ SL นับจากราคาปิดแท่งที่ทะลุ
  5. breakout แรกของวันเท่านั้น — ถ้าแรกสุดสวน bias หรือ SL แคบเกิน วันนั้นไม่เทรด ไม่รอตัวถัดไป
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from research.strategies.smc_v0 import h1_bias

STRATEGY_NAME = "asian_breakout_v0"


@dataclass(frozen=True)
class AsianBreakoutParams:
    # ปรับได้ — 2 ตัว
    swing_len_h1: int = 5
    tp_r: float = 2.0
    # กฎคงที่
    asian_start_hour: int = 0
    asian_end_hour: int = 7
    window_end_hour: int = 12
    min_sl_distance: float = 3.0

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def signal_hours(self) -> tuple[int, int]:
        return self.asian_end_hour, self.window_end_hour


def generate_signals(
    m5: pd.DataFrame, h1: pd.DataFrame, params: AsianBreakoutParams = AsianBreakoutParams()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(m5)
    close = m5["close"].to_numpy(float)
    day = m5.index.normalize()
    hours = m5.index.hour.to_numpy()

    in_asian = (hours >= params.asian_start_hour) & (hours < params.asian_end_hour)
    asian = (
        m5.loc[in_asian]
        .groupby(day[in_asian])
        .agg(asian_high=("high", "max"), asian_low=("low", "min"))
    )
    # ใช้ได้เฉพาะหลัง Asian session ของวันนั้นจบ (ช่วงเทรดเริ่ม 07:00) จึงไม่มองอนาคต
    asian_high = asian["asian_high"].reindex(day).to_numpy()
    asian_low = asian["asian_low"].reindex(day).to_numpy()
    in_window = (hours >= params.asian_end_hour) & (hours < params.window_end_hour)
    bias = h1_bias(m5.index, h1, params.swing_len_h1)

    side = np.zeros(n, dtype=np.int64)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    setups: list[dict] = []
    decided_days: set[pd.Timestamp] = set()

    for j in range(n):
        if not in_window[j] or day[j] in decided_days:
            continue
        high_j, low_j = asian_high[j], asian_low[j]
        if not (np.isfinite(high_j) and np.isfinite(low_j)):
            continue
        if close[j] > high_j:
            direction = 1
        elif close[j] < low_j:
            direction = -1
        else:
            continue

        decided_days.add(day[j])
        mid = (high_j + low_j) / 2
        risk = abs(close[j] - mid)
        record = {
            "direction": direction,
            "break_time": m5.index[j],
            "asian_high": high_j,
            "asian_low": low_j,
            "sl": np.nan,
            "tp": np.nan,
        }
        if bias[j] != direction:
            record["outcome"] = "against_bias"
        elif risk < params.min_sl_distance:
            record["outcome"] = "sl_too_tight"
        else:
            side[j] = direction
            sl[j] = mid
            tp[j] = close[j] + direction * params.tp_r * risk
            record.update(sl=sl[j], tp=tp[j], outcome="signal")
        setups.append(record)

    signals = pd.DataFrame(
        {
            "side": side,
            "entry": np.nan,
            "sl": sl,
            "tp": tp,
            "expiry_bars": np.nan,
            "cancel_price": np.nan,
        },
        index=m5.index,
    )
    return signals, pd.DataFrame(setups)
