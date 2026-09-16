"""ตัวตรวจจับองค์ประกอบ SMC — นิยามตาม journal/STRATEGY-SMC-v0.md

กฎเหล็กของทั้งไฟล์: **ทุกค่าที่คืนที่แท่ง i ต้องคำนวณจากข้อมูลถึงราคาปิดแท่ง i เท่านั้น**

จุดที่คนมักพลาดคือ swing point — แท่งจะเป็น swing high ได้ต้องรู้ว่าอีก L แท่งข้างหน้าไม่สูงกว่า
ซึ่งแปลว่า "รู้" ได้ก็ต่อเมื่อผ่านไปแล้ว L แท่ง ฟังก์ชันที่นี่จึงคืนค่าที่แท่ง i+L ไม่ใช่แท่ง i
ถ้าใช้ที่แท่ง i จะเป็นการมองอนาคต และ backtest จะสวยเกินจริง
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def swing_points(bars: pd.DataFrame, length: int) -> pd.DataFrame:
    """หา swing high/low แบบ fractal: สูง/ต่ำกว่า `length` แท่งทั้งซ้ายและขวา

    คืน DataFrame:
      is_swing_high/low  — True ที่ "แท่งที่เป็น swing" (ใช้ตอนวาดกราฟ/ตรวจสอบ)
      swing_high/low     — ราคาของ swing ล่าสุดที่ **ยืนยันแล้ว ณ แท่งนั้น**
      swing_high/low_bar — ตำแหน่งแท่งของ swing นั้น (-1 = ยังไม่มี)
    """
    if length < 1:
        raise ValueError("length must be at least 1")
    n = len(bars)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)

    if n >= 2 * length + 1:
        # sw_max[k] = max(high[k : k+length])
        sw_max = sliding_window_view(high, length).max(axis=1)
        sw_min = sliding_window_view(low, length).min(axis=1)
        center = slice(length, n - length)
        left_max = sw_max[0 : n - 2 * length]
        right_max = sw_max[length + 1 : n - length + 1]
        left_min = sw_min[0 : n - 2 * length]
        right_min = sw_min[length + 1 : n - length + 1]
        is_high[center] = (high[center] > left_max) & (high[center] > right_max)
        is_low[center] = (low[center] > 0) & (low[center] < left_min) & (low[center] < right_min)

    out = pd.DataFrame(
        {"is_swing_high": is_high, "is_swing_low": is_low},
        index=bars.index,
    )
    out["swing_high"], out["swing_high_bar"] = _known_after(high, is_high, length, n)
    out["swing_low"], out["swing_low_bar"] = _known_after(low, is_low, length, n)
    return out


def _known_after(price: np.ndarray, is_pivot: np.ndarray, length: int, n: int):
    """เลื่อนค่าไปปรากฏที่แท่งที่ยืนยันได้ (pivot + length) แล้ว forward fill"""
    value = np.full(n, np.nan)
    bar = np.full(n, -1, dtype=np.int64)
    for i in np.flatnonzero(is_pivot):
        confirmed_at = i + length
        if confirmed_at < n:
            value[confirmed_at] = price[i]
            bar[confirmed_at] = i
    value = pd.Series(value).ffill().to_numpy()
    bar_series = pd.Series(np.where(bar < 0, np.nan, bar)).ffill()
    return value, bar_series.fillna(-1).astype(np.int64).to_numpy()


def market_structure(bars: pd.DataFrame, swings: pd.DataFrame) -> pd.DataFrame:
    """BOS / CHoCH — นับเมื่อ **ราคาปิด** ทะลุ swing ล่าสุดที่ยืนยันแล้ว (ไส้ทะลุไม่นับ)

    BOS   = ทะลุไปทางเดียวกับเทรนด์ปัจจุบัน
    CHoCH = ทะลุสวนเทรนด์ปัจจุบัน (แท่งแรกที่กลับทิศ)
    swing เดิมที่ถูกทะลุไปแล้วจะไม่ถูกนับซ้ำ จนกว่าจะมี swing ใหม่ยืนยัน

    คืน: trend (1/-1/0), event ('bos'/'choch'/None), level (ราคาที่ถูกทะลุ)
    """
    n = len(bars)
    close = bars["close"].to_numpy(float)
    swing_high = swings["swing_high"].to_numpy(float)
    swing_low = swings["swing_low"].to_numpy(float)
    high_bar = swings["swing_high_bar"].to_numpy(np.int64)
    low_bar = swings["swing_low_bar"].to_numpy(np.int64)

    trend = np.zeros(n, dtype=np.int64)
    event = np.full(n, None, dtype=object)
    level = np.full(n, np.nan)

    current = 0
    broken_high_bar = -1
    broken_low_bar = -1
    for i in range(n):
        if np.isfinite(swing_high[i]) and close[i] > swing_high[i] and high_bar[i] != broken_high_bar:
            event[i] = "choch" if current < 0 else "bos"
            level[i] = swing_high[i]
            broken_high_bar = high_bar[i]
            current = 1
        elif np.isfinite(swing_low[i]) and close[i] < swing_low[i] and low_bar[i] != broken_low_bar:
            event[i] = "choch" if current > 0 else "bos"
            level[i] = swing_low[i]
            broken_low_bar = low_bar[i]
            current = -1
        trend[i] = current

    return pd.DataFrame({"trend": trend, "event": event, "level": level}, index=bars.index)


def reference_levels(
    bars: pd.DataFrame, session_start_hour: int = 0, session_end_hour: int = 7
) -> pd.DataFrame:
    """ระดับ liquidity ที่ใช้: ช่วง Asian ที่ **จบแล้ว** และ high/low ของ **วันก่อนหน้า**

    ระหว่างที่ Asian session ของวันนี้ยังไม่จบ จะใช้ของวันก่อนหน้า (ไม่มองอนาคต)
    """
    index = bars.index
    day = index.normalize()
    hour = index.hour + index.minute / 60.0

    in_session = (hour >= session_start_hour) & (hour < session_end_hour)
    session = (
        bars.loc[in_session]
        .groupby(day[in_session])
        .agg(session_high=("high", "max"), session_low=("low", "min"))
    )

    daily = bars.groupby(day).agg(prev_day_high=("high", "max"), prev_day_low=("low", "min"))
    previous_day = daily.shift(1)

    if len(session):
        calendar = pd.date_range(session.index.min(), day.max(), freq="D")
        session_available = session.reindex(calendar).ffill()
        # ก่อน session ของวันนี้จบ ให้ใช้ของเมื่อวาน
        key = pd.DatetimeIndex(np.where(hour >= session_end_hour, day, day - pd.Timedelta(days=1)))
        session_values = session_available.reindex(key)
    else:
        session_values = pd.DataFrame(
            {"session_high": np.nan, "session_low": np.nan}, index=range(len(bars))
        )

    out = pd.DataFrame(index=index)
    out["session_high"] = session_values["session_high"].to_numpy()
    out["session_low"] = session_values["session_low"].to_numpy()
    out["prev_day_high"] = previous_day["prev_day_high"].reindex(day).to_numpy()
    out["prev_day_low"] = previous_day["prev_day_low"].reindex(day).to_numpy()
    return out


def sweeps(bars: pd.DataFrame, level: pd.Series, reclaim_bars: int, side: str) -> pd.DataFrame:
    """กวาด liquidity แล้วราคากลับเข้ามา

    side="low"  : ราคาลงไปต่ำกว่า level แล้ว **ปิด** กลับขึ้นมาเหนือ level ภายใน reclaim_bars แท่ง
    side="high" : กลับด้าน

    ยืนยันที่ "แท่งที่ปิดกลับเข้ามา" ไม่ใช่แท่งที่ทะลุ (ตอนทะลุยังไม่รู้ว่าจะกลับหรือไปต่อ)
    ถ้าเกิน reclaim_bars แล้วยังไม่กลับ = ทะลุจริง ไม่ใช่ sweep → ทิ้ง

    คืน: confirmed (bool), sweep_level, sweep_extreme (จุดสุดของการกวาด), sweep_start_bar
    """
    if side not in ("low", "high"):
        raise ValueError("side must be 'low' or 'high'")
    n = len(bars)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    close = bars["close"].to_numpy(float)
    levels = level.to_numpy(float)

    confirmed = np.zeros(n, dtype=bool)
    out_level = np.full(n, np.nan)
    out_extreme = np.full(n, np.nan)
    out_start = np.full(n, -1, dtype=np.int64)

    active_start = -1
    active_level = np.nan
    active_extreme = np.nan
    for i in range(n):
        if active_start < 0:
            lv = levels[i]
            if np.isfinite(lv) and ((side == "low" and low[i] < lv) or (side == "high" and high[i] > lv)):
                active_start = i
                active_level = lv
                active_extreme = low[i] if side == "low" else high[i]
            continue

        active_extreme = min(active_extreme, low[i]) if side == "low" else max(active_extreme, high[i])
        reclaimed = close[i] > active_level if side == "low" else close[i] < active_level
        if reclaimed:
            confirmed[i] = True
            out_level[i] = active_level
            out_extreme[i] = active_extreme
            out_start[i] = active_start
            active_start = -1
        elif i - active_start >= reclaim_bars:
            active_start = -1

    return pd.DataFrame(
        {
            "confirmed": confirmed,
            "sweep_level": out_level,
            "sweep_extreme": out_extreme,
            "sweep_start_bar": out_start,
        },
        index=bars.index,
    )


def find_order_block(bars: pd.DataFrame, start_bar: int, end_bar: int, direction: int):
    """หา order block: แท่งตรงข้ามแท่งสุดท้ายก่อนราคาพุ่งไปทำ CHoCH

    direction = 1  (setup ฝั่ง buy)  → หาแท่งแดงแท่งสุดท้าย (close < open)
    direction = -1 (setup ฝั่ง sell) → หาแท่งเขียวแท่งสุดท้าย (close > open)
    โซน = ทั้งแท่ง (high ถึง low)

    คืน dict(top, bottom, bar) หรือ None ถ้าไม่เจอในช่วงนั้น
    """
    if direction not in (1, -1):
        raise ValueError("direction must be 1 or -1")
    start = max(start_bar, 0)
    end = min(end_bar, len(bars) - 1)
    if start > end:
        return None

    open_ = bars["open"].to_numpy(float)
    close = bars["close"].to_numpy(float)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)

    for k in range(end, start - 1, -1):
        is_opposite = close[k] < open_[k] if direction == 1 else close[k] > open_[k]
        if is_opposite:
            return {"top": float(high[k]), "bottom": float(low[k]), "bar": k}
    return None
