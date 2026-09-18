"""คู่เทียบ: เข้าไม้สุ่มแต่คงรูปทรงของไม้ไว้เหมือนกลยุทธ์อ้างอิงทุกอย่าง

ทุก signal ของกลยุทธ์อ้างอิง → signal สุ่มหนึ่งอัน ที่
- เกิดที่แท่งสุ่มในช่วงเวลาเทรดเดียวกัน ทิศสุ่ม
- ระยะ SL, ระยะ TP และ (ถ้าเป็นคำสั่งรอ) ระยะรอย่อ, ระยะ cancel, อายุคำสั่ง **เท่าเดิมทุกอย่าง**
  คำสั่ง market วัดระยะจากราคาปิดของแท่ง signal / คำสั่งรอวัดจากราคาที่รอเข้า

ต่างจากกลยุทธ์อ้างอิงแค่ "เข้าตรงไหน" อย่างเดียว ถ้ากลยุทธ์ชนะคู่เทียบนี้ไม่ขาด
แปลว่าผลของมันมาจากรูปทรง SL/TP หรือดวง ไม่ใช่จากการเลือกจุดเข้า
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def random_matched_signals(
    bars: pd.DataFrame,
    reference: pd.DataFrame,
    seed: int,
    session_start_hour: int = 7,
    session_end_hour: int = 16,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(bars)
    close = bars["close"].to_numpy(float)
    hours = bars.index.hour.to_numpy()
    eligible = np.flatnonzero((hours >= session_start_hour) & (hours < session_end_hour))

    side = np.zeros(n, dtype=np.int64)
    entry = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    expiry = np.full(n, np.nan)
    cancel = np.full(n, np.nan)

    ref_positions = np.flatnonzero(reference["side"].to_numpy() != 0)
    if len(ref_positions) > len(eligible):
        raise ValueError("more reference signals than eligible bars")

    for pos in ref_positions:
        row = reference.iloc[pos]
        ref_side = int(row["side"])
        is_limit = np.isfinite(row["entry"])
        anchor = row["entry"] if is_limit else close[pos]
        sl_distance = (anchor - row["sl"]) * ref_side
        tp_distance = (row["tp"] - anchor) * ref_side

        k = int(rng.choice(eligible))
        while side[k] != 0:
            k = int(rng.choice(eligible))
        s = int(rng.choice((1, -1)))
        side[k] = s

        if is_limit:
            pullback = (close[pos] - row["entry"]) * ref_side
            cancel_distance = (row["cancel_price"] - row["sl"]) * ref_side
            entry[k] = close[k] - s * pullback
            new_anchor = entry[k]
            cancel[k] = new_anchor - s * sl_distance + s * cancel_distance
            expiry[k] = row["expiry_bars"]
        else:
            new_anchor = close[k]
        sl[k] = new_anchor - s * sl_distance
        tp[k] = new_anchor + s * tp_distance

    return pd.DataFrame(
        {"side": side, "entry": entry, "sl": sl, "tp": tp, "expiry_bars": expiry, "cancel_price": cancel},
        index=bars.index,
    )
