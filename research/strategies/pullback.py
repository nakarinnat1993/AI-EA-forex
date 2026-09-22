"""Trend pullback v0 — ตามกฎใน journal/STRATEGY-PULLBACK-v0.md (ล็อกไว้ก่อนเขียนโค้ด)

ห้ามแก้กฎในไฟล์นี้โดยไม่แก้เอกสารกฎและบันทึกใน journal/ITERATIONS.md

ฝั่ง Buy (ฝั่ง Sell กลับด้าน):
  1. เทรนด์ H1 ขาขึ้น
  2. M5 ปิดทะลุ swing high ล่าสุดที่ยืนยันแล้ว → ระดับ L
  3. Buy Limit ที่ L (รอ retest)
  4. SL ใต้ swing low ล่าสุดของ M5 − buffer
  5. TP1 (ครึ่งหนึ่ง) ก่อน swing high ของ H1 ที่ใกล้ที่สุดเหนือ L ไม่เกิน tp1_max_r
     ถ้าโซนใกล้กว่า 1R → ไม่เทรด / ไม่มีโซน → tp1_max_r
  6. TP2 (อีกครึ่ง) = 2 เท่าของระยะ TP1
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from research.smc import market_structure, swing_points
from research.strategies.smc_v0 import average_true_range, bar_duration, h1_bias

STRATEGY_NAME = "pullback_v0"
_H1 = pd.Timedelta(hours=1)


@dataclass(frozen=True)
class PullbackParams:
    # ปรับได้ — 5 ตัว
    swing_len_h1: int = 5
    swing_len_m5: int = 3
    order_expiry: int = 36
    sl_buffer_atr: float = 0.1
    tp1_max_r: float = 2.0
    # กฎคงที่
    session_start_hour: int = 7
    session_end_hour: int = 16
    min_sl_distance: float = 3.0
    min_room_r: float = 1.0
    atr_period: int = 14
    # รอบ 3 (STRATEGY-ROUND3.md): เทรดเฉพาะเมื่อ ATR/ราคา บน timeframe เทรนด์ > median 365 วัน
    vol_filter: bool = False

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def generate_signals(
    m5: pd.DataFrame, h1: pd.DataFrame, params: PullbackParams = PullbackParams()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(m5)
    close = m5["close"].to_numpy(float)
    hours = m5.index.hour.to_numpy()
    in_session = (hours >= params.session_start_hour) & (hours < params.session_end_hour)
    decided_at = (m5.index + bar_duration(m5.index)).as_unit("ns").asi8

    bias = h1_bias(m5.index, h1, params.swing_len_h1)
    zones = {1: _h1_zones(h1, params.swing_len_h1, "high"), -1: _h1_zones(h1, params.swing_len_h1, "low")}
    swings = swing_points(m5, params.swing_len_m5)
    structure = market_structure(m5, swings)
    is_break = structure["is_break"].to_numpy()
    trend = structure["trend"].to_numpy()
    broken = structure["level"].to_numpy(float)
    swing_low = swings["swing_low"].to_numpy(float)
    swing_high = swings["swing_high"].to_numpy(float)
    atr = average_true_range(m5, params.atr_period)
    active = high_volatility(m5.index, h1, params.atr_period) if params.vol_filter else np.ones(n, dtype=bool)

    side = np.zeros(n, dtype=np.int64)
    entry = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    tp2 = np.full(n, np.nan)
    expiry = np.full(n, np.nan)
    cancel = np.full(n, np.nan)
    setups: list[dict] = []

    for j in range(n):
        if not (in_session[j] and is_break[j]):
            continue
        direction = int(trend[j])
        if bias[j] != direction or not active[j]:
            continue
        level = broken[j]
        structure_edge = swing_low[j] if direction == 1 else swing_high[j]
        record = {"direction": direction, "break_time": m5.index[j], "level": level, "zone": np.nan}
        outcome = _levels(level, structure_edge, atr[j], close[j], direction, zones[direction], decided_at[j], params)
        record["zone"] = outcome.pop("zone", np.nan) if isinstance(outcome, dict) else np.nan
        if isinstance(outcome, str):
            record["outcome"] = outcome
        else:
            side[j] = direction
            entry[j], sl[j], tp[j], tp2[j] = level, outcome["sl"], outcome["tp1"], outcome["tp2"]
            cancel[j] = structure_edge
            expiry[j] = params.order_expiry
            record.update(sl=sl[j], tp1=tp[j], tp2=tp2[j], outcome="signal")
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
        index=m5.index,
    )
    return signals, pd.DataFrame(setups)


def _levels(level, structure_edge, atr_now, close_now, direction, zones, decided_at, params) -> dict | str:
    if not (np.isfinite(level) and np.isfinite(structure_edge)):
        return "no_structure"
    if not np.isfinite(atr_now):
        return "atr_not_ready"
    buffer = params.sl_buffer_atr * atr_now
    sl = structure_edge - direction * buffer
    risk = (level - sl) * direction
    if risk <= 0:
        return "sl_on_wrong_side"
    if (close_now - level) * direction <= 0:
        return "price_inside_zone"
    if risk < params.min_sl_distance:
        return "sl_too_tight"

    available_at, price = zones
    known = price[available_at <= decided_at]
    ahead = known[(known - level) * direction > 0]
    tp1_cap = level + direction * params.tp1_max_r * risk
    zone = np.nan
    if len(ahead):
        zone = ahead.min() if direction == 1 else ahead.max()
        before_zone = zone - direction * buffer
        if (before_zone - level) * direction < params.min_room_r * risk:
            return "no_room"
        tp1 = min(before_zone, tp1_cap) if direction == 1 else max(before_zone, tp1_cap)
    else:
        tp1 = tp1_cap
    tp2 = level + 2 * (tp1 - level)
    return {"sl": sl, "tp1": tp1, "tp2": tp2, "zone": zone}


def high_volatility(index: pd.DatetimeIndex, htf: pd.DataFrame, atr_period: int) -> np.ndarray:
    """True เมื่อ ATR/ราคา ของ timeframe ใหญ่ สูงกว่า median ย้อนหลัง 365 วัน (ใช้แท่งที่ปิดแล้วเท่านั้น)
    ปีแรกของข้อมูลยังมีประวัติไม่ครบ 365 วัน → False"""
    ratio = pd.Series(average_true_range(htf, atr_period) / htf["close"].to_numpy(float), index=htf.index)
    median = ratio.rolling("365D").median()
    full_year = htf.index - htf.index[0] >= pd.Timedelta(days=365)
    high = ((ratio > median) & full_year).to_numpy()
    available = pd.DataFrame({"at": htf.index + bar_duration(htf.index), "high": high})
    decisions = pd.DataFrame({"at": index + bar_duration(index)})
    merged = pd.merge_asof(decisions, available, on="at", direction="backward")
    return merged["high"].eq(True).to_numpy()


def _h1_zones(h1: pd.DataFrame, swing_len: int, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """swing ของ H1 ทุกจุด พร้อมเวลาที่ "รู้" ได้จริง (แท่งยืนยันปิดแล้ว)"""
    swings = swing_points(h1, swing_len)
    flags = swings["is_swing_high" if kind == "high" else "is_swing_low"].to_numpy()
    pivots = np.flatnonzero(flags)
    confirmed = pivots + swing_len
    keep = confirmed < len(h1)
    pivots, confirmed = pivots[keep], confirmed[keep]
    price = h1["high" if kind == "high" else "low"].to_numpy(float)[pivots]
    available_at = (h1.index[confirmed] + bar_duration(h1.index)).as_unit("ns").asi8
    return available_at, price
