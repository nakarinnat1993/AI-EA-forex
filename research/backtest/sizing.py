from __future__ import annotations

import math

from .costs import SymbolSpec


def lots_for_risk(equity: float, risk_pct: float, entry: float, sl: float, spec: SymbolSpec) -> float:
    """ขนาดไม้จาก % ความเสี่ยงของทุน

    ปัดลงตาม volume step เสมอ — ปัดขึ้นเท่ากับเสี่ยงเกินที่ตั้งไว้
    คืน 0.0 เมื่อไม้ที่คำนวณได้ต่ำกว่า min lot → ผู้เรียกต้องข้ามไม้นั้น
    ห้ามบังคับใช้ min lot แทน เพราะจะเสี่ยงเกินเพดาน
    """
    distance = abs(entry - sl)
    if distance <= 0 or equity <= 0 or risk_pct <= 0:
        return 0.0
    raw_lots = (equity * risk_pct / 100.0) / (distance * spec.contract_size)
    steps = math.floor(raw_lots / spec.volume_step + 1e-9)
    lots = min(steps * spec.volume_step, spec.volume_max)
    if lots < spec.volume_min - 1e-12:
        return 0.0
    return round(lots, 8)
