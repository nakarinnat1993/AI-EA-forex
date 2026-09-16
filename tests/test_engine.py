from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from research.backtest.costs import CostModel
from research.backtest.engine import RiskConfig, run_backtest
from tests.helpers import CENT_SPEC, make_bars, make_limit_signals, make_signals

NO_COSTS = CostModel()
RISK_1PCT = RiskConfig(initial_equity=50.0, risk_pct=1.0)


def run(bars, entries, costs=NO_COSTS, risk=RISK_1PCT):
    return run_backtest(bars, make_signals(bars, entries), CENT_SPEC, costs, risk)


def test_enters_at_next_bar_open_not_on_signal_bar():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 101.0, 99.0, 100.5),
        ("2026-09-14 10:05", 101.0, 101.5, 100.8, 101.2),
        ("2026-09-14 10:10", 101.2, 111.0, 101.0, 110.0),
    ])
    result = run(bars, {"2026-09-14 10:00": (1, 96.0, 110.0)})

    (trade,) = result.trades
    assert trade.entry_time == pd.Timestamp("2026-09-14 10:05")
    assert trade.entry_price == pytest.approx(101.2)  # open 101.0 + spread 0.2 (ซื้อที่ ask)
    assert trade.lots == pytest.approx(0.09)  # 0.50 / 5.2 = 0.096 → ปัดลง
    assert trade.exit_reason == "tp"
    assert trade.pnl_usd == pytest.approx((110.0 - 101.2) * 0.09)
    assert result.equity.iloc[-1] == pytest.approx(50.0 + trade.pnl_usd)


def test_bar_touching_both_sl_and_tp_counts_as_sl():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.8, 100.2),
        ("2026-09-14 10:10", 100.2, 111.0, 94.0, 100.0),
    ])
    (trade,) = run(bars, {"2026-09-14 10:00": (1, 95.0, 110.0)}).trades

    assert trade.exit_reason == "sl"
    assert trade.ambiguous
    assert trade.exit_price == pytest.approx(95.0)


def test_gap_through_stop_fills_at_open_and_loses_more_than_planned():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.8, 100.2),
        ("2026-09-14 10:10", 93.0, 94.0, 92.0, 93.5),
    ])
    costs = replace(NO_COSTS, stop_slippage_price=0.1)
    (trade,) = run(bars, {"2026-09-14 10:00": (1, 95.0, 110.0)}, costs=costs).trades

    assert trade.exit_reason == "sl_gap"
    assert trade.exit_price == pytest.approx(92.9)
    assert -trade.pnl_usd > trade.risk_usd


def test_short_take_profit_needs_ask_to_reach_target():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0),  # เข้า short ที่ bid 100.0
        ("2026-09-14 10:10", 99.0, 99.5, 95.0, 96.0),  # bid แตะ 95 แต่ ask ต่ำสุด 95.2 → ยังไม่ถึง TP
        ("2026-09-14 10:15", 96.0, 96.5, 94.7, 95.0),  # ask ต่ำสุด 94.9 → TP
    ])
    (trade,) = run(bars, {"2026-09-14 10:00": (-1, 105.0, 95.0)}).trades

    assert trade.entry_price == pytest.approx(100.0)
    assert trade.exit_time == pd.Timestamp("2026-09-14 10:15")
    assert trade.exit_reason == "tp"
    assert trade.pnl_usd == pytest.approx(5.0 * 0.1)


def test_short_stop_is_triggered_by_ask_not_bid():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:10", 100.0, 104.9, 99.5, 100.0),  # bid สูงสุด 104.9 แต่ ask 105.1 ≥ SL
    ])
    (trade,) = run(bars, {"2026-09-14 10:00": (-1, 105.0, 95.0)}).trades

    assert trade.exit_reason == "sl"


@pytest.mark.parametrize("day, multiplier", [("2026-09-15", 1), ("2026-09-16", 3)])
def test_swap_charged_at_rollover_with_wednesday_triple(day, multiplier):
    d0 = pd.Timestamp(day)
    d1 = d0 + pd.Timedelta(days=1)
    bars = make_bars([
        (d0 + pd.Timedelta("23:50:00"), 100.0, 100.5, 99.5, 100.0),
        (d0 + pd.Timedelta("23:55:00"), 100.0, 100.5, 99.8, 100.2),
        (d1, 100.2, 100.6, 100.0, 100.4),
        (d1 + pd.Timedelta("00:05:00"), 100.4, 121.0, 100.3, 120.5),
    ])
    costs = replace(NO_COSTS, swap_long_points=-534.9, swap_multipliers={0: 1, 1: 1, 2: 3, 3: 1, 4: 1})
    (trade,) = run(bars, {d0 + pd.Timedelta("23:50:00"): (1, 95.0, 120.0)}, costs=costs).trades

    assert trade.rollovers == 1
    assert trade.swap_usd == pytest.approx(-534.9 * 0.001 * 0.09 * multiplier)


def test_skips_signal_when_size_falls_below_min_lot():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0),
    ])
    result = run(bars, {"2026-09-14 10:00": (1, 40.0, 200.0)})

    assert result.trades == []
    assert result.skipped["below_min_lot"] == 1


def test_skips_signal_when_gap_puts_entry_beyond_target():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 101.0, 101.5, 100.5, 101.0),  # ask เปิดที่ 101.2 เลย TP ไปแล้ว
    ])
    result = run(bars, {"2026-09-14 10:00": (1, 95.0, 100.9)})

    assert result.trades == []
    assert result.skipped["invalid_levels_at_entry"] == 1


def test_holds_one_position_at_a_time():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:10", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-14 10:15", 100.0, 100.5, 99.5, 100.0),
    ])
    entries = {f"2026-09-14 10:{m:02d}": (1, 90.0, 200.0) for m in (0, 5, 10)}
    result = run(bars, entries)

    (trade,) = result.trades
    assert trade.exit_reason == "end_of_data"
    assert result.skipped["position_open"] == 2


def test_daily_loss_limit_blocks_rest_of_day_then_resets():
    bars = make_bars(
        [
            ("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0),
            ("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0),  # เข้า 0.20 lot เสี่ยง $1.00 (2%)
            ("2026-09-14 10:10", 100.0, 100.0, 94.0, 94.5),  # โดน SL -$1.00 เกินเพดาน 1.5%
            ("2026-09-14 10:15", 94.5, 95.0, 94.0, 94.8),  # signal จากแท่งก่อนถูกบล็อก
            ("2026-09-15 10:00", 95.0, 95.5, 94.5, 95.0),
            ("2026-09-15 10:05", 95.0, 95.5, 94.5, 95.0),  # วันใหม่ เข้าได้อีก
        ],
        spread=0.0,
    )
    entries = {
        "2026-09-14 10:00": (1, 95.0, 120.0),
        "2026-09-14 10:10": (1, 89.5, 110.0),
        "2026-09-15 10:00": (1, 90.0, 105.0),
    }
    risk = RiskConfig(initial_equity=50.0, risk_pct=2.0, daily_loss_limit_pct=1.5)
    result = run(bars, entries, risk=risk)

    assert len(result.trades) == 2
    assert result.trades[0].pnl_usd == pytest.approx(-1.0)
    assert result.skipped["daily_loss_limit"] == 1
    assert result.trades[1].entry_time == pd.Timestamp("2026-09-15 10:05")
    assert result.trades[1].lots == pytest.approx(0.19)  # 2% ของ $49 / 5 = 0.196 → 0.19


NEWS_BARS_ROWS = [
    ("2026-09-15 11:50", 100.0, 100.5, 99.5, 100.0),
    ("2026-09-15 11:55", 100.0, 100.5, 99.8, 100.2),
    ("2026-09-15 12:00", 101.0, 101.5, 100.5, 101.0),  # แท่งแรกในช่วงข่าว
    ("2026-09-15 12:05", 101.0, 130.0, 90.0, 101.0),
]
NEWS_WINDOW = [False, False, True, True]


def test_news_window_closes_open_long_at_bid_open():
    bars = make_bars(NEWS_BARS_ROWS)
    signals = make_signals(bars, {"2026-09-15 11:50": (1, 95.0, 120.0)})
    (trade,) = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT, blackout=NEWS_WINDOW).trades

    assert trade.exit_reason == "news_close"
    assert trade.exit_time == pd.Timestamp("2026-09-15 12:00")
    assert trade.exit_price == pytest.approx(101.0)


def test_news_window_closes_open_short_at_ask_open():
    bars = make_bars(NEWS_BARS_ROWS)
    signals = make_signals(bars, {"2026-09-15 11:50": (-1, 105.0, 90.0)})
    (trade,) = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT, blackout=NEWS_WINDOW).trades

    assert trade.exit_reason == "news_close"
    assert trade.exit_price == pytest.approx(101.2)


def test_no_entries_inside_news_window():
    bars = make_bars(NEWS_BARS_ROWS[1:])
    signals = make_signals(bars, {"2026-09-15 11:55": (1, 95.0, 120.0)})
    result = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT, blackout=NEWS_WINDOW[1:])

    assert result.trades == []
    assert result.skipped["news_blackout"] == 1


LIMIT_BARS_ROWS = [
    ("2026-09-16 10:00", 100.0, 100.5, 99.5, 100.0),  # ตั้ง Buy Limit ที่ 99.0
    ("2026-09-16 10:05", 100.0, 100.2, 99.2, 99.5),  # ask ต่ำสุด 99.4 → ยังไม่ถึง
    ("2026-09-16 10:10", 99.5, 99.6, 98.7, 99.0),  # ask ต่ำสุด 98.9 → ได้เข้าที่ 99.0
    ("2026-09-16 10:15", 99.0, 105.5, 99.0, 105.0),
]


def test_buy_limit_fills_when_ask_reaches_the_price():
    bars = make_bars(LIMIT_BARS_ROWS)
    signals = make_limit_signals(bars, {"2026-09-16 10:00": (1, 99.0, 97.0, 105.0, 5, 96.9)})
    (trade,) = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT).trades

    assert trade.entry_time == pd.Timestamp("2026-09-16 10:10")
    assert trade.entry_price == pytest.approx(99.0)
    assert trade.lots == pytest.approx(0.25)  # 0.50 / 2.0
    assert trade.exit_reason == "tp"


def test_pending_order_expires_if_price_never_comes_back():
    bars = make_bars(LIMIT_BARS_ROWS)
    signals = make_limit_signals(bars, {"2026-09-16 10:00": (1, 90.0, 88.0, 200.0, 2, np.nan)})
    result = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT)

    assert result.trades == []
    assert result.skipped["order_expired"] == 1


def test_pending_order_is_cancelled_when_price_runs_to_target_first():
    # ราคาไปถึง TP โดยไม่ย่อกลับมา = ตกรถ ต้องไม่ไล่ราคา
    bars = make_bars([
        ("2026-09-16 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-16 10:05", 100.0, 101.2, 100.0, 101.0),
    ])
    signals = make_limit_signals(bars, {"2026-09-16 10:00": (1, 99.0, 97.0, 101.0, 5, np.nan)})
    result = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT)

    assert result.trades == []
    assert result.skipped["missed_move"] == 1


def test_pending_order_is_cancelled_when_close_breaks_the_zone():
    bars = make_bars([
        ("2026-09-16 10:00", 100.0, 100.5, 99.5, 100.0),
        ("2026-09-16 10:05", 99.5, 99.6, 98.9, 98.92),  # ask ต่ำสุด 99.1 → ยังไม่เข้า แต่ปิดหลุดโซน
    ])
    signals = make_limit_signals(bars, {"2026-09-16 10:00": (1, 99.0, 97.0, 105.0, 5, 98.95)})
    result = run_backtest(bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT)

    assert result.trades == []
    assert result.skipped["order_invalidated"] == 1


def test_pending_order_is_cancelled_by_news_window():
    bars = make_bars(LIMIT_BARS_ROWS)
    signals = make_limit_signals(bars, {"2026-09-16 10:00": (1, 99.0, 97.0, 105.0, 5, np.nan)})
    result = run_backtest(
        bars, signals, CENT_SPEC, NO_COSTS, RISK_1PCT, blackout=[False, True, True, True]
    )

    assert result.trades == []
    assert result.skipped["news_blackout"] == 1


def test_rejects_signals_with_mismatched_index():
    bars = make_bars([("2026-09-14 10:00", 100.0, 100.5, 99.5, 100.0)])
    other = make_bars([("2026-09-14 10:05", 100.0, 100.5, 99.5, 100.0)])
    with pytest.raises(ValueError, match="share the bars index"):
        run_backtest(bars, make_signals(other, {}), CENT_SPEC, NO_COSTS, RISK_1PCT)
