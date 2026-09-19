"""SMC v0.1 — ตามกฎใน journal/STRATEGY-SMC-v0.md

ห้ามแก้กฎในไฟล์นี้โดยไม่แก้เอกสารกฎและบันทึกใน journal/ITERATIONS.md

ลำดับของ setup ฝั่ง Buy (ฝั่ง Sell กลับด้าน):
  1. bias H1 ขาขึ้น (จากแท่ง H1 ที่ปิดแล้วเท่านั้น)
  2. sweep: ราคามาจากด้านบน ทิ่มลงกวาดใต้ Asian low หรือ low ของเมื่อวาน แล้วปิดกลับขึ้นมา
  3. ภายใน choch_window แท่ง ราคาปิดทะลุ swing high ล่าสุดที่ยืนยันแล้ว
  4. order block = แท่งแดงแท่งสุดท้าย **ก่อนราคาเริ่มพุ่ง** (ที่หรือก่อนจุดต่ำสุดของการกวาด)
  5. ตั้ง Buy Limit ที่ขอบบนของ OB / SL ใต้ OB − buffer / TP = tp_r × ระยะ SL

v0 → v0.1 (IT-002): แก้ sweep ปลอม (ต้องเข้าหา level จากอีกฝั่ง, liquidity เก็บได้ครั้งเดียว) และ
ย้ายช่วงค้นหา OB ให้ตรงกับตารางนิยาม — v0 ค้นระหว่างจุดต่ำสุดกับแท่งที่ทะลุ ทำให้หา OB ไม่เจอ 41%

variant ที่ลงทะเบียนไว้ล่วงหน้า (STRATEGY-SMC-v0.md) เปิดผ่านสวิตช์ใน SmcV0Params — ค่าเริ่มต้น = v0.1

หมายเหตุการตีความ: ข้อ 3 รับการทะลุทั้งแบบ CHoCH และ BOS ของโครงสร้าง M5
(ตามที่เอกสารกฎเขียนว่า "ปิดทะลุ swing high ล่าสุด") — variant 2 รับเฉพาะ CHoCH
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from research.smc import find_order_block, market_structure, reference_levels, sweeps, swing_points

STRATEGY_NAME = "smc_v0.1"
SIGNAL_COLUMNS = ["side", "entry", "sl", "tp", "expiry_bars", "cancel_price"]
TUNABLE_PARAMS = (
    "swing_len_h1",
    "swing_len_m5",
    "reclaim_bars",
    "choch_window",
    "order_expiry",
    "sl_buffer_atr",
    "tp_r",
)
_M5 = pd.Timedelta(minutes=5)
_H1 = pd.Timedelta(hours=1)


@dataclass(frozen=True)
class SmcV0Params:
    # ปรับได้ — 7 ตัว
    swing_len_h1: int = 5
    swing_len_m5: int = 3
    reclaim_bars: int = 3
    choch_window: int = 24
    order_expiry: int = 36
    sl_buffer_atr: float = 0.1
    tp_r: float = 2.0
    # กฎคงที่ — ไม่ใช่พารามิเตอร์ให้จูน
    session_start_hour: int = 7
    session_end_hour: int = 16
    asian_start_hour: int = 0
    asian_end_hour: int = 7
    min_sl_distance: float = 3.0
    atr_period: int = 14
    # สวิตช์ variant ที่ลงทะเบียนไว้ล่วงหน้า (2026-09-17) — ค่าเริ่มต้นคือ v0.1
    sl_anchor: str = "block"  # variant 1: "sweep" = SL ใต้จุดสุดของการกวาด
    require_choch: bool = False  # variant 2: รับเฉพาะ CHoCH ไม่รับ BOS
    min_sweep_depth_atr: float = 0.0  # variant 3: ทิ่มเกินระดับอย่างน้อยกี่เท่าของ ATR

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def generate_signals(
    m5: pd.DataFrame, h1: pd.DataFrame, params: SmcV0Params = SmcV0Params()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """คืน (signals สำหรับ engine, ตาราง setup ทุกอันที่เจอพร้อมผลว่าออก signal หรือถูกตัดเพราะอะไร)"""
    n = len(m5)
    high = m5["high"].to_numpy(float)
    low = m5["low"].to_numpy(float)
    close = m5["close"].to_numpy(float)
    hours = m5.index.hour.to_numpy()
    in_session = (hours >= params.session_start_hour) & (hours < params.session_end_hour)

    bias = h1_bias(m5.index, h1, params.swing_len_h1)
    levels = reference_levels(m5, params.asian_start_hour, params.asian_end_hour)
    sweep_by_direction = {
        1: _combined_sweeps(m5, levels, params.reclaim_bars, "low"),
        -1: _combined_sweeps(m5, levels, params.reclaim_bars, "high"),
    }
    structure = market_structure(m5, swing_points(m5, params.swing_len_m5))
    event = structure["event"].to_numpy()
    is_break = structure["is_break"].to_numpy()
    trend = structure["trend"].to_numpy()
    atr = average_true_range(m5, params.atr_period)

    side = np.zeros(n, dtype=np.int64)
    entry = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    expiry = np.full(n, np.nan)
    cancel = np.full(n, np.nan)

    armed: dict[int, dict | None] = {1: None, -1: None}
    used_blocks: set[int] = set()
    setups: list[dict] = []

    for j in range(n):
        for direction, sweep in sweep_by_direction.items():
            if not (sweep["confirmed"][j] and in_session[j] and bias[j] == direction):
                continue
            if params.min_sweep_depth_atr > 0 and not (
                np.isfinite(atr[j]) and sweep["depth"][j] >= params.min_sweep_depth_atr * atr[j]
            ):
                continue
            armed[direction] = {
                "sweep_bar": j,
                "start": int(sweep["start"][j]),
                "extreme": float(sweep["extreme"][j]),
                "source": sweep["source"][j],
                "until": j + params.choch_window,
            }

        for direction in (1, -1):
            setup = armed[direction]
            if setup is None:
                continue
            if j > setup["until"]:
                armed[direction] = None
                continue
            if not (in_session[j] and is_break[j] and trend[j] == direction):
                continue
            if params.require_choch and event[j] != "choch":
                continue
            armed[direction] = None

            window = slice(setup["start"], j + 1)
            extreme_bar = setup["start"] + int(np.argmin(low[window]) if direction == 1 else np.argmax(high[window]))
            extreme_price = low[extreme_bar] if direction == 1 else high[extreme_bar]
            # OB = แท่งสีตรงข้ามแท่งสุดท้าย ที่หรือก่อนจุดสุดของการกวาด (ต้นทางของแรงกลับตัว)
            block = find_order_block(m5, max(0, extreme_bar - params.choch_window), extreme_bar, direction)
            record = {
                "direction": direction,
                "sweep_time": m5.index[setup["sweep_bar"]],
                "sweep_source": setup["source"],
                "sweep_extreme": setup["extreme"],
                "break_time": m5.index[j],
                "block_time": m5.index[block["bar"]] if block else pd.NaT,
                "block_top": block["top"] if block else np.nan,
                "block_bottom": block["bottom"] if block else np.nan,
                "entry": np.nan,
                "sl": np.nan,
                "tp": np.nan,
            }

            outcome = _order_levels(block, used_blocks, atr[j], close[j], extreme_price, direction, params)
            if isinstance(outcome, str):
                record["outcome"] = outcome
            elif side[j] != 0:
                record["outcome"] = "opposite_signal_same_bar"
            else:
                side[j] = direction
                entry[j], sl[j], tp[j] = outcome["entry"], outcome["sl"], outcome["tp"]
                cancel[j] = outcome["cancel"]
                expiry[j] = params.order_expiry
                used_blocks.add(block["bar"])
                record.update(entry=entry[j], sl=sl[j], tp=tp[j], outcome="signal")
            setups.append(record)

    signals = pd.DataFrame(
        {"side": side, "entry": entry, "sl": sl, "tp": tp, "expiry_bars": expiry, "cancel_price": cancel},
        index=m5.index,
    )
    return signals, pd.DataFrame(setups)


def _order_levels(block, used_blocks, atr_now, close_now, extreme_price, direction, params) -> dict | str:
    if block is None:
        return "no_order_block"
    if block["bar"] in used_blocks:
        return "order_block_used"
    if not np.isfinite(atr_now):
        return "atr_not_ready"
    buffer = params.sl_buffer_atr * atr_now
    by_sweep = params.sl_anchor == "sweep"
    if direction == 1:
        entry = block["top"]
        cancel = block["bottom"]
        anchor = min(cancel, extreme_price) if by_sweep else cancel
        sl = anchor - buffer
        risk = entry - sl
        tp = entry + params.tp_r * risk
        waiting_for_pullback = close_now > entry
    else:
        entry = block["bottom"]
        cancel = block["top"]
        anchor = max(cancel, extreme_price) if by_sweep else cancel
        sl = anchor + buffer
        risk = sl - entry
        tp = entry - params.tp_r * risk
        waiting_for_pullback = close_now < entry
    if not waiting_for_pullback:
        return "price_inside_zone"
    if risk < params.min_sl_distance:
        return "sl_too_tight"
    return {"entry": entry, "sl": sl, "tp": tp, "cancel": cancel}


def bar_duration(index: pd.DatetimeIndex) -> pd.Timedelta:
    """ความยาวแท่ง = ระยะห่างที่พบบ่อยที่สุด (ช่องว่างสุดสัปดาห์และวันหยุดไม่กระทบ)"""
    if len(index) < 2:
        return _M5
    return pd.Series(index[1:] - index[:-1]).mode().iloc[0]


def h1_bias(m5_index: pd.DatetimeIndex, h1: pd.DataFrame, swing_len: int) -> np.ndarray:
    """ทิศทางของ timeframe ใหญ่ (H1 หรือ M15) ณ เวลาที่แท่งเข้าไม้ปิด — ใช้เฉพาะแท่งที่ปิดไปแล้ว"""
    structure = market_structure(h1, swing_points(h1, swing_len))
    available = pd.DataFrame({"at": h1.index + bar_duration(h1.index), "trend": structure["trend"].to_numpy()})
    decisions = pd.DataFrame({"at": m5_index + bar_duration(m5_index)})
    merged = pd.merge_asof(decisions, available, on="at", direction="backward")
    return merged["trend"].fillna(0).astype(np.int64).to_numpy()


def average_true_range(bars: pd.DataFrame, period: int) -> np.ndarray:
    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - previous_close).abs(),
            (bars["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean().to_numpy()


def _combined_sweeps(m5: pd.DataFrame, levels: pd.DataFrame, reclaim_bars: int, side: str) -> dict:
    names = ("session_low", "prev_day_low") if side == "low" else ("session_high", "prev_day_high")
    first, second = (sweeps(m5, levels[name], reclaim_bars, side) for name in names)
    a = first["confirmed"].to_numpy()
    b = second["confirmed"].to_numpy()
    pick = np.fmin if side == "low" else np.fmax
    sign = 1.0 if side == "low" else -1.0
    never = np.iinfo(np.int64).max
    # ความลึกของการทิ่มเกินระดับ (บวกเสมอ)
    depth_a = (first["sweep_level"].to_numpy() - first["sweep_extreme"].to_numpy()) * sign
    depth_b = (second["sweep_level"].to_numpy() - second["sweep_extreme"].to_numpy()) * sign
    return {
        "confirmed": a | b,
        "extreme": pick(first["sweep_extreme"].to_numpy(), second["sweep_extreme"].to_numpy()),
        "depth": np.fmax(depth_a, depth_b),
        "start": np.minimum(
            np.where(a, first["sweep_start_bar"].to_numpy(), never),
            np.where(b, second["sweep_start_bar"].to_numpy(), never),
        ),
        "source": np.where(a, "asian", np.where(b, "prev_day", "")),
    }
