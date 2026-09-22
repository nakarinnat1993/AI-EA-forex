import numpy as np
import pandas as pd
import pytest

from research.backtest.costs import CostModel
from research.backtest.engine import RiskConfig, run_backtest
from tests.helpers import CENT_SPEC, make_bars

NO_COSTS = CostModel()
RISK_1PCT = RiskConfig(initial_equity=50.0, risk_pct=1.0)


def split_signal(bars, time, side, sl, tp, tp2):
    signals = pd.DataFrame({"side": 0, "sl": np.nan, "tp": np.nan, "tp2": np.nan}, index=bars.index)
    signals.loc[pd.Timestamp(time), ["side", "sl", "tp", "tp2"]] = [side, sl, tp, tp2]
    signals["side"] = signals["side"].astype(int)
    return signals


ENTRY_ROWS = [
    ("2026-09-16 10:00", 100.0, 100.5, 99.5, 100.0),
    ("2026-09-16 10:05", 100.0, 100.5, 99.8, 100.2),  # เข้า 100.2 (ask) → 0.09 lot แบ่งเป็น 0.04 + 0.05
]


def test_first_half_at_tp1_rest_at_tp2():
    bars = make_bars(ENTRY_ROWS + [
        ("2026-09-16 10:10", 100.2, 110.5, 100.0, 110.0),  # TP1
        ("2026-09-16 10:15", 110.0, 120.5, 109.8, 120.0),  # TP2
    ])
    (trade,) = run_backtest(bars, split_signal(bars, "2026-09-16 10:00", 1, 95.0, 110.0, 120.0), CENT_SPEC, NO_COSTS, RISK_1PCT).trades

    assert trade.lots == pytest.approx(0.09)
    assert trade.tp1_oz == pytest.approx(0.04)
    assert trade.tp1_filled
    assert trade.exit_reason == "tp2"
    assert trade.pnl_usd == pytest.approx((110.0 - 100.2) * 0.04 + (120.0 - 100.2) * 0.05)


def test_runner_stopped_after_tp1_keeps_the_partial_profit():
    bars = make_bars(ENTRY_ROWS + [
        ("2026-09-16 10:10", 100.2, 110.5, 100.0, 110.0),  # TP1
        ("2026-09-16 10:15", 110.0, 110.2, 94.0, 95.0),  # ส่วนที่เหลือโดน SL เดิม
    ])
    (trade,) = run_backtest(bars, split_signal(bars, "2026-09-16 10:00", 1, 95.0, 110.0, 120.0), CENT_SPEC, NO_COSTS, RISK_1PCT).trades

    assert trade.exit_reason == "sl"
    assert trade.tp1_filled
    assert trade.pnl_usd == pytest.approx((110.0 - 100.2) * 0.04 + (95.0 - 100.2) * 0.05)


def test_bar_touching_sl_and_tp1_loses_the_whole_position():
    bars = make_bars(ENTRY_ROWS + [("2026-09-16 10:10", 100.2, 111.0, 94.0, 100.0)])
    (trade,) = run_backtest(bars, split_signal(bars, "2026-09-16 10:00", 1, 95.0, 110.0, 120.0), CENT_SPEC, NO_COSTS, RISK_1PCT).trades

    assert trade.exit_reason == "sl"
    assert trade.ambiguous
    assert not trade.tp1_filled
    assert trade.pnl_usd == pytest.approx((95.0 - 100.2) * 0.09)


def test_position_too_small_to_split_exits_fully_at_tp1():
    # เสี่ยง $0.50 กับ SL ห่าง ~$50 → 0.01 lot แบ่งไม่ได้
    bars = make_bars(ENTRY_ROWS + [("2026-09-16 10:10", 100.2, 110.5, 100.0, 110.0)])
    result = run_backtest(bars, split_signal(bars, "2026-09-16 10:00", 1, 50.2, 110.0, 120.0), CENT_SPEC, NO_COSTS, RISK_1PCT)
    (trade,) = result.trades

    assert trade.lots == pytest.approx(0.01)
    assert trade.tp1_oz == 0
    assert trade.exit_reason == "tp"
    assert result.skipped["too_small_to_split"] == 1


def test_breakeven_moves_stop_to_entry_after_tp1():
    bars = make_bars(ENTRY_ROWS + [
        ("2026-09-16 10:10", 100.2, 110.5, 100.0, 110.0),  # TP1 ปิดครึ่งแรก
        ("2026-09-16 10:15", 110.0, 110.2, 94.0, 95.0),  # ย้อนลงมา — SL อยู่ที่ราคาเข้าแล้ว
    ])
    signals = split_signal(bars, "2026-09-16 10:00", 1, 95.0, 110.0, 120.0)
    risk = RiskConfig(initial_equity=50.0, risk_pct=1.0, breakeven_after_tp1=True)
    (trade,) = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, risk).trades

    assert trade.exit_reason == "sl"
    assert trade.exit_price == pytest.approx(100.2)  # ราคาเข้า ไม่ใช่ 95
    assert trade.pnl_usd == pytest.approx((110.0 - 100.2) * 0.04)


def test_short_partial_uses_ask_prices():
    bars = make_bars([
        ("2026-09-16 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-16 10:05", 100.0, 100.5, 99.5, 100.0),  # short ที่ bid 100.0, SL 105 → 0.10 lot
        ("2026-09-16 10:10", 99.0, 99.5, 94.7, 95.0),  # ask ต่ำสุด 94.9 ≤ TP1 95
        ("2026-09-16 10:15", 95.0, 95.2, 89.7, 90.0),  # ask ต่ำสุด 89.9 ≤ TP2 90
    ])
    (trade,) = run_backtest(bars, split_signal(bars, "2026-09-16 10:00", -1, 105.0, 95.0, 90.0), CENT_SPEC, NO_COSTS, RISK_1PCT).trades

    assert trade.exit_reason == "tp2"
    assert trade.pnl_usd == pytest.approx((100.0 - 95.0) * 0.05 + (100.0 - 90.0) * 0.05)
