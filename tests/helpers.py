from __future__ import annotations

import numpy as np
import pandas as pd

from research.backtest.costs import SymbolSpec

CENT_SPEC = SymbolSpec(
    name="XAUUSDc", digits=3, contract_size=1.0, volume_min=0.01, volume_step=0.01, volume_max=200.0
)


def make_bars(rows, spread: float = 0.2) -> pd.DataFrame:
    """rows: (time, open, high, low, close)"""
    index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
    bars = pd.DataFrame([r[1:] for r in rows], index=index, columns=["open", "high", "low", "close"], dtype=float)
    bars["spread_price"] = spread
    return bars


def make_signals(bars: pd.DataFrame, entries: dict) -> pd.DataFrame:
    """เข้าราคาตลาดที่แท่งถัดไป — entries: {time: (side, sl, tp)}"""
    signals = pd.DataFrame({"side": 0.0, "sl": np.nan, "tp": np.nan}, index=bars.index)
    for ts, (side, sl, tp) in entries.items():
        signals.loc[pd.Timestamp(ts), ["side", "sl", "tp"]] = [side, sl, tp]
    signals["side"] = signals["side"].astype(int)
    return signals


def make_limit_signals(bars: pd.DataFrame, entries: dict) -> pd.DataFrame:
    """คำสั่งรอเข้าที่ราคา — entries: {time: (side, entry, sl, tp, expiry_bars, cancel_price)}"""
    columns = ["side", "entry", "sl", "tp", "expiry_bars", "cancel_price"]
    signals = pd.DataFrame(
        {"side": 0.0, "entry": np.nan, "sl": np.nan, "tp": np.nan, "expiry_bars": 0.0, "cancel_price": np.nan},
        index=bars.index,
    )
    for ts, values in entries.items():
        signals.loc[pd.Timestamp(ts), columns] = list(values)
    signals["side"] = signals["side"].astype(int)
    return signals
