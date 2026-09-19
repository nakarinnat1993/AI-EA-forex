"""Backtest engine แบบวิ่งทีละแท่ง

ข้อตกลงที่ต้องรู้ก่อนอ่านผล:
- OHLC ใน bars เป็นราคา BID (สเปก Exness: Chart mode = By bid price) และ ask = bid + spread
- signal ที่แท่ง i ใช้ข้อมูลถึงราคาปิดแท่ง i → คำสั่งเริ่มมีผลตั้งแต่แท่ง i+1
- Long เข้าที่ ask ออกที่ bid / Short เข้าที่ bid ออกที่ ask
- แท่งเดียวชนทั้ง SL และเป้า → ถือว่าโดน SL ทั้งไม้ (ไม่รู้ลำดับในแท่ง จึงเลือกกรณีแย่) และติดธง ambiguous
- ราคาเปิดแท่งกระโดดข้าม SL → ออกที่ราคาเปิด + stop slippage (จำลองเหตุการณ์ข่าวแรง)
- ราคาเปิดกระโดดข้ามเป้า → ออกที่เป้า (ไม่นับกำไรส่วนเกินจาก gap)
- ถือได้ครั้งละ 1 ไม้ และมีคำสั่งรอได้ครั้งละ 1 คำสั่ง / swap คิดเมื่อข้าม rollover
- news blackout: แท่งในช่วงข่าวห้ามเปิดไม้ใหม่ ยกเลิกคำสั่งรอ และไม้ที่ถืออยู่ปิดแบบ market
  ที่ราคาเปิดของแท่งแรกในช่วง (ถ้าราคาเปิดกระโดดข้าม SL/เป้าไปแล้ว ใช้กฎ gap ตามปกติ)

คำสั่งรอเข้าที่ราคา (limit) — ใส่คอลัมน์ entry ใน signals:
- Buy limit ถูกจับคู่เมื่อ **ask** ลงมาถึงราคาที่ตั้ง (= low + spread ≤ entry) ตามที่ MT5 ทำงานจริง
- ราคาที่ได้คือราคาที่ตั้งไว้เสมอ แม้แท่งจะ gap ลงไปต่ำกว่านั้น (อนุรักษ์นิยม)
- ยกเลิกเมื่อ: หมดอายุ (expiry_bars), ราคาไปถึง TP ก่อนได้เข้า (ตกรถ), ราคาปิดเลย cancel_price
  หรือเข้าช่วงข่าว

ปิดไม้ทีละส่วน — ใส่คอลัมน์ tp2 ใน signals (STRATEGY-PULLBACK-v0.md):
- ขนาดไม้รวมยังคิดจากความเสี่ยงเดิม แล้วแบ่งครึ่ง ปัดลงทั้งสองส่วน
- ครึ่งแรกปิดที่ tp (TP1) ส่วนที่เหลือปิดที่ tp2 หรือ SL เดิม
- ถ้าแบ่งแล้วส่วนใดต่ำกว่า min lot → ไม่ซอย ปิดทั้งไม้ที่ TP1
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .costs import CostModel, SymbolSpec
from .sizing import lots_for_risk

_HOUR_NS = 3_600 * 10**9
_DAY_NS = 24 * _HOUR_NS
_STOP_REASONS = ("sl", "sl_gap")
PARTIAL_FRACTION = 0.5


@dataclass(frozen=True)
class RiskConfig:
    initial_equity: float
    risk_pct: float
    # circuit breaker: ขาดทุนสะสมในวันเกิน % ของทุนต้นวัน → หยุดเปิดไม้ใหม่ถึงวันถัดไป
    daily_loss_limit_pct: float | None = None


def load_risk_config(path: str | Path) -> RiskConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return RiskConfig(
        initial_equity=raw["initial_equity"],
        risk_pct=raw["risk_pct"],
        daily_loss_limit_pct=raw.get("daily_loss_limit_pct"),
    )


@dataclass
class PendingOrder:
    signal_bar: int
    side: int
    entry: float  # NaN = เข้าราคาตลาดที่แท่งถัดไป
    sl: float
    tp: float
    tp2: float  # NaN = ไม่ซอยไม้
    expiry_bar: int
    cancel_price: float  # NaN = ไม่มีเงื่อนไขยกเลิกจากราคาปิด


@dataclass
class Trade:
    side: int
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    tp: float
    lots: float
    oz: float
    risk_usd: float
    commission_usd: float
    spread_cost_usd: float
    slippage_cost_usd: float
    tp2: float = np.nan
    tp1_oz: float = 0.0  # ส่วนที่ปิดที่ TP1 (0 = ไม่ซอย)
    tp1_filled: bool = False
    partial_pnl_usd: float = 0.0
    swap_usd: float = 0.0
    rollovers: int = 0
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    ambiguous: bool = False

    @property
    def split(self) -> bool:
        return self.tp1_oz > 0

    @property
    def open_oz(self) -> float:
        return self.oz - self.tp1_oz if self.tp1_filled else self.oz

    @property
    def target(self) -> float:
        return self.tp2 if self.tp1_filled else self.tp

    @property
    def pnl_usd(self) -> float:
        if self.exit_price is None:
            raise ValueError("trade is still open")
        price_pnl = (self.exit_price - self.entry_price) * self.side * self.open_oz
        return self.partial_pnl_usd + price_pnl + self.swap_usd - self.commission_usd

    @property
    def r_multiple(self) -> float:
        return self.pnl_usd / self.risk_usd


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity: pd.Series
    skipped: Counter
    initial_equity: float


def run_backtest(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    spec: SymbolSpec,
    costs: CostModel,
    risk: RiskConfig,
    blackout=None,
) -> BacktestResult:
    """bars: open/high/low/close (bid) + spread_price (ถ้ามี)
    signals: index เดียวกับ bars, ต้องมี side (1/-1/0), sl, tp เป็นราคา
             ใส่เพิ่มได้: entry (ราคาที่รอเข้า), expiry_bars, cancel_price, tp2 (ซอยไม้)
    blackout: bool หนึ่งค่าต่อแท่ง (จาก news.news_blackout) หรือ None"""
    _validate(bars, signals)

    n = len(bars)
    times = bars.index
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    bar_spread = bars["spread_price"].to_numpy(float) if "spread_price" in bars else np.zeros(n)
    spread = costs.effective_spread(bar_spread)
    news = np.zeros(n, dtype=bool) if blackout is None else np.asarray(blackout, dtype=bool)
    if news.shape != (n,):
        raise ValueError("blackout must have one flag per bar")

    def optional(column: str, default: float) -> np.ndarray:
        return signals[column].to_numpy(float) if column in signals else np.full(n, default)

    sig_side = signals["side"].to_numpy(int)
    sig_sl = signals["sl"].to_numpy(float)
    sig_tp = signals["tp"].to_numpy(float)
    sig_tp2 = optional("tp2", np.nan)
    sig_entry = optional("entry", np.nan)
    sig_expiry = optional("expiry_bars", 0.0)
    sig_cancel = optional("cancel_price", np.nan)

    # วันเทรดนับตาม rollover ไม่ใช่เที่ยงคืนตามปฏิทิน / 1970-01-01 เป็นวันพฤหัส (weekday 3)
    trading_day = (times.as_unit("ns").asi8 - costs.rollover_hour * _HOUR_NS) // _DAY_NS
    weekday = (trading_day + 3) % 7

    trades: list[Trade] = []
    skipped: Counter = Counter()
    equity = np.empty(n)

    balance = risk.initial_equity
    pos: Trade | None = None
    pending: PendingOrder | None = None
    day_start_balance = balance
    day_pnl = 0.0
    day_blocked = False

    def close_position(j: int, price: float, reason: str, ambiguous: bool = False) -> None:
        nonlocal pos, balance, day_pnl, day_blocked
        assert pos is not None
        pos.exit_time = times[j]
        pos.exit_price = float(price)
        pos.exit_reason = reason
        pos.ambiguous = ambiguous
        if pos.side < 0:
            pos.spread_cost_usd += spread[j] * pos.open_oz
        if reason in _STOP_REASONS:
            pos.slippage_cost_usd += abs(price - pos.sl) * pos.open_oz
        elif reason == "news_close":
            pos.slippage_cost_usd += costs.entry_slippage_price * pos.open_oz
        pnl = pos.pnl_usd
        balance += pnl
        day_pnl += pnl
        limit = risk.daily_loss_limit_pct
        if limit is not None and day_pnl <= -day_start_balance * limit / 100.0:
            day_blocked = True
        trades.append(pos)
        pos = None

    def take_partial(j: int) -> None:
        assert pos is not None and pos.split and not pos.tp1_filled
        pos.partial_pnl_usd += (pos.tp - pos.entry_price) * pos.side * pos.tp1_oz
        if pos.side < 0:
            pos.spread_cost_usd += spread[j] * pos.tp1_oz
        pos.tp1_filled = True

    def open_position(j: int, order: PendingOrder, price: float, slippage: float) -> None:
        nonlocal pos
        valid = order.sl < price < order.tp if order.side > 0 else order.tp < price < order.sl
        if not (np.isfinite(order.sl) and np.isfinite(order.tp) and valid):
            skipped["invalid_levels_at_entry"] += 1
            return
        lots = lots_for_risk(balance, risk.risk_pct, price, order.sl, spec)
        if lots == 0.0:
            skipped["below_min_lot"] += 1
            return
        tp1_oz = 0.0
        if np.isfinite(order.tp2):
            first = np.floor(lots * PARTIAL_FRACTION / spec.volume_step + 1e-9) * spec.volume_step
            rest = round(lots - first, 8)
            if first >= spec.volume_min - 1e-12 and rest >= spec.volume_min - 1e-12:
                tp1_oz = first * spec.contract_size
            else:
                skipped["too_small_to_split"] += 1
        oz = lots * spec.contract_size
        pos = Trade(
            side=order.side,
            signal_time=times[order.signal_bar],
            entry_time=times[j],
            entry_price=float(price),
            sl=order.sl,
            tp=order.tp,
            tp2=order.tp2 if tp1_oz > 0 else np.nan,
            tp1_oz=tp1_oz,
            lots=lots,
            oz=oz,
            risk_usd=abs(price - order.sl) * oz,
            commission_usd=costs.commission_per_lot_roundturn * lots,
            spread_cost_usd=spread[j] * oz if order.side > 0 else 0.0,
            slippage_cost_usd=slippage * oz,
        )

    def process_pending(j: int) -> None:
        nonlocal pending
        order = pending
        assert order is not None
        if news[j]:
            pending = None
            skipped["news_blackout"] += 1
            return
        if day_blocked:
            pending = None
            skipped["daily_loss_limit"] += 1
            return

        if not np.isfinite(order.entry):  # market
            pending = None
            slip = costs.entry_slippage_price
            price = o[j] + spread[j] + slip if order.side > 0 else o[j] - slip
            open_position(j, order, price, slip)
            return

        if j > order.expiry_bar:
            pending = None
            skipped["order_expired"] += 1
            return

        if order.side > 0:
            filled = l[j] + spread[j] <= order.entry
            missed = h[j] >= order.tp
            invalidated = np.isfinite(order.cancel_price) and c[j] < order.cancel_price
        else:
            filled = h[j] >= order.entry
            missed = l[j] + spread[j] <= order.tp
            invalidated = np.isfinite(order.cancel_price) and c[j] > order.cancel_price

        if filled:
            pending = None
            open_position(j, order, order.entry, 0.0)
        elif missed:
            pending = None
            skipped["missed_move"] += 1
        elif invalidated:
            pending = None
            skipped["order_invalidated"] += 1

    def check_exit(j: int, news_close: bool) -> None:
        assert pos is not None
        s = pos.side
        fresh = pos.entry_time == times[j]
        slip = costs.stop_slippage_price
        if s > 0:
            px_open, favorable, adverse = o[j], h[j], l[j]
        else:
            px_open, favorable, adverse = o[j] + spread[j], l[j] + spread[j], h[j] + spread[j]

        def beyond_sl(price: float) -> bool:
            return price <= pos.sl if s > 0 else price >= pos.sl

        def reached(price: float, target: float) -> bool:
            return price >= target if s > 0 else price <= target

        if not fresh:
            if beyond_sl(px_open):
                return close_position(j, px_open - s * slip, "sl_gap")
            if reached(px_open, pos.target):
                if pos.split and not pos.tp1_filled:
                    take_partial(j)
                else:
                    return close_position(j, pos.target, "tp2" if pos.tp1_filled else "tp")
        if news_close:
            return close_position(j, px_open - s * costs.entry_slippage_price, "news_close")

        if beyond_sl(adverse):
            return close_position(j, pos.sl - s * slip, "sl", ambiguous=reached(favorable, pos.target))
        if not reached(favorable, pos.target):
            return
        if pos.split and not pos.tp1_filled:
            take_partial(j)
            if reached(favorable, pos.tp2):
                close_position(j, pos.tp2, "tp2")
        else:
            close_position(j, pos.target, "tp2" if pos.tp1_filled else "tp")

    for j in range(n):
        if j > 0 and trading_day[j] != trading_day[j - 1]:
            if pos is not None:
                pos.swap_usd += costs.swap_usd(pos.side, pos.open_oz, spec.point, int(weekday[j - 1]))
                pos.rollovers += 1
            day_start_balance = balance
            day_pnl = 0.0
            day_blocked = False

        if pending is not None:
            process_pending(j)

        if pos is not None:
            check_exit(j, news_close=bool(news[j]))

        if pos is None:
            equity[j] = balance
        else:
            mark = c[j] if pos.side > 0 else c[j] + spread[j]
            open_pnl = (mark - pos.entry_price) * pos.side * pos.open_oz
            equity[j] = balance + pos.partial_pnl_usd + open_pnl + pos.swap_usd - pos.commission_usd

        if sig_side[j] != 0:
            if pos is not None:
                skipped["position_open"] += 1
            elif pending is not None:
                skipped["order_already_pending"] += 1
            else:
                expiry = int(sig_expiry[j]) if np.isfinite(sig_expiry[j]) else 0
                pending = PendingOrder(
                    signal_bar=j,
                    side=int(sig_side[j]),
                    entry=float(sig_entry[j]),
                    sl=float(sig_sl[j]),
                    tp=float(sig_tp[j]),
                    tp2=float(sig_tp2[j]),
                    expiry_bar=j + max(expiry, 1),
                    cancel_price=float(sig_cancel[j]),
                )

    if pos is not None:
        last = n - 1
        close_position(last, c[last] if pos.side > 0 else c[last] + spread[last], "end_of_data")
    if pending is not None:
        skipped["order_open_at_end"] += 1

    return BacktestResult(
        trades=trades,
        equity=pd.Series(equity, index=times, name="equity"),
        skipped=skipped,
        initial_equity=risk.initial_equity,
    )


def _validate(bars: pd.DataFrame, signals: pd.DataFrame) -> None:
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars index must be a DatetimeIndex")
    if bars.index.tz is not None:
        raise ValueError("bars index must be naive server time")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("bars index must be sorted and unique")
    missing = {"open", "high", "low", "close"} - set(bars.columns)
    if missing:
        raise ValueError(f"bars missing columns: {sorted(missing)}")
    if not signals.index.equals(bars.index):
        raise ValueError("signals must share the bars index")
    missing = {"side", "sl", "tp"} - set(signals.columns)
    if missing:
        raise ValueError(f"signals missing columns: {sorted(missing)}")
