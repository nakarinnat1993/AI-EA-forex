import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import assert_causal
from research.smc import find_order_block, market_structure, reference_levels, sweeps, swing_points
from tests.helpers import make_bars


def bars_from_closes(closes, start="2026-09-14 00:00", freq="5min", wick=0.5):
    index = pd.date_range(start, periods=len(closes), freq=freq)
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + wick, "low": close - wick, "close": close}, index=index
    )


def test_swing_high_is_only_known_after_the_confirming_bars():
    # high สูงสุดอยู่ที่แท่ง 3 โดยมี length=2 → ต้องรู้ที่แท่ง 5 เท่านั้น
    bars = bars_from_closes([10, 11, 12, 15, 12, 11, 10, 9], wick=0.0)
    swings = swing_points(bars, length=2)

    assert bool(swings["is_swing_high"].iloc[3])
    assert np.isnan(swings["swing_high"].iloc[4])
    assert swings["swing_high"].iloc[5] == pytest.approx(15.0)
    assert swings["swing_high_bar"].iloc[5] == 3


def test_equal_highs_are_not_swings():
    bars = bars_from_closes([10, 12, 12, 12, 10, 9, 8], wick=0.0)
    assert not swing_points(bars, length=2)["is_swing_high"].any()


def test_structure_marks_bos_then_choch():
    #        0   1   2   3   4   5   6   7   8   9  10  11  12
    closes = [10, 11, 14, 11, 10, 11, 16, 13, 12, 11, 10, 8, 7]
    bars = bars_from_closes(closes, wick=0.0)
    swings = swing_points(bars, length=2)
    structure = market_structure(bars, swings)

    events = structure.loc[structure["event"].notna(), "event"].tolist()
    assert events[0] == "bos"  # ปิดทะลุ swing high แรกขึ้นไป
    assert "choch" in events  # แล้วกลับมาปิดทะลุ swing low ลงมา
    assert structure["trend"].iloc[-1] == -1


def test_structure_ignores_wick_only_breaks():
    closes = [10, 11, 14, 11, 10, 11, 12, 12]
    bars = bars_from_closes(closes, wick=0.0)
    bars.loc[bars.index[6], "high"] = 99.0  # ไส้ทะลุแต่ปิดต่ำกว่า
    structure = market_structure(bars, swing_points(bars, length=2))

    assert structure["event"].isna().all()


def test_session_levels_use_yesterday_until_todays_session_ends():
    index = pd.date_range("2026-09-14 00:00", periods=48, freq="h")
    close = np.full(len(index), 100.0)
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=index)
    bars.loc["2026-09-14 03:00", "high"] = 120.0  # Asian วันแรก
    bars.loc["2026-09-14 04:00", "low"] = 80.0
    bars.loc["2026-09-15 03:00", "high"] = 130.0  # Asian วันที่สอง

    levels = reference_levels(bars, session_start_hour=0, session_end_hour=7)

    assert np.isnan(levels["session_high"].loc["2026-09-14 03:00"])  # วันแรกยังไม่มีของเมื่อวาน
    assert levels["session_high"].loc["2026-09-14 08:00"] == pytest.approx(120.0)
    assert levels["session_low"].loc["2026-09-14 08:00"] == pytest.approx(80.0)
    # ระหว่าง Asian ของวันที่สอง ต้องยังใช้ค่าเมื่อวาน ไม่ใช่ 130
    assert levels["session_high"].loc["2026-09-15 03:00"] == pytest.approx(120.0)
    assert levels["session_high"].loc["2026-09-15 08:00"] == pytest.approx(130.0)
    assert levels["prev_day_high"].loc["2026-09-15 08:00"] == pytest.approx(120.0)


def test_sweep_confirms_on_the_bar_that_closes_back_above():
    bars = make_bars([
        ("2026-09-14 10:00", 101.0, 101.5, 100.5, 101.0),
        ("2026-09-14 10:05", 100.5, 100.8, 99.0, 99.5),  # ทะลุลงใต้ 100 ยังไม่ปิดกลับ
        ("2026-09-14 10:10", 99.5, 100.9, 99.2, 100.8),  # ปิดกลับเหนือ 100 → ยืนยัน
    ])
    level = pd.Series(100.0, index=bars.index)
    result = sweeps(bars, level, reclaim_bars=3, side="low")

    assert not result["confirmed"].iloc[1]
    assert result["confirmed"].iloc[2]
    assert result["sweep_extreme"].iloc[2] == pytest.approx(99.0)
    assert result["sweep_start_bar"].iloc[2] == 1


def test_real_breakdown_is_not_a_sweep():
    bars = make_bars([
        ("2026-09-14 10:00", 101.0, 101.5, 100.5, 101.0),
        ("2026-09-14 10:05", 100.5, 100.8, 99.0, 99.5),
        ("2026-09-14 10:10", 99.5, 99.6, 98.0, 98.2),
        ("2026-09-14 10:15", 98.2, 98.4, 97.0, 97.2),
        ("2026-09-14 10:20", 97.2, 101.0, 97.0, 100.9),  # กลับมาช้าเกิน reclaim_bars
    ])
    level = pd.Series(100.0, index=bars.index)
    assert not sweeps(bars, level, reclaim_bars=2, side="low")["confirmed"].any()


def test_price_already_below_the_level_climbing_back_is_not_a_sweep():
    # IT-001 กราฟ 3: ราคาอยู่ใต้ Asian low มาหลายชั่วโมง แล้วค่อยปิดกลับขึ้นมา
    bars = make_bars([
        ("2026-09-14 10:00", 99.0, 99.4, 98.8, 99.0),
        ("2026-09-14 10:05", 99.0, 99.5, 98.5, 99.2),
        ("2026-09-14 10:10", 99.2, 100.8, 99.1, 100.5),
    ])
    level = pd.Series(100.0, index=bars.index)
    assert not sweeps(bars, level, reclaim_bars=3, side="low")["confirmed"].any()


def test_liquidity_can_only_be_swept_once_per_level():
    bars = make_bars([
        ("2026-09-14 10:00", 101.0, 101.5, 100.5, 101.0),
        ("2026-09-14 10:05", 101.0, 101.2, 99.0, 100.5),  # ทิ่มลงแล้วปิดกลับในแท่งเดียว → sweep
        ("2026-09-14 10:10", 100.5, 101.3, 100.4, 101.0),
        ("2026-09-14 10:15", 101.0, 101.1, 99.2, 100.6),  # level เดิมถูกเก็บไปแล้ว → ไม่นับซ้ำ
    ])
    level = pd.Series(100.0, index=bars.index)
    result = sweeps(bars, level, reclaim_bars=3, side="low")

    assert result["confirmed"].tolist() == [False, True, False, False]
    assert result["sweep_extreme"].iloc[1] == pytest.approx(99.0)


def test_order_block_is_the_last_opposite_candle_before_the_move():
    bars = pd.DataFrame(
        {
            "open": [100.0, 99.0, 98.0, 99.5, 101.0],
            "close": [99.0, 98.0, 99.4, 101.0, 103.0],
            "high": [100.5, 99.5, 99.6, 101.2, 103.5],
            "low": [98.8, 97.5, 97.8, 99.3, 100.8],
        },
        index=pd.date_range("2026-09-14 10:00", periods=5, freq="5min"),
    )
    block = find_order_block(bars, start_bar=0, end_bar=4, direction=1)

    assert block == {"top": pytest.approx(99.5), "bottom": pytest.approx(97.5), "bar": 1}
    assert find_order_block(bars, start_bar=3, end_bar=4, direction=1) is None


def test_primitives_never_look_ahead():
    rng = np.random.default_rng(3)
    close = 4400 + rng.normal(0, 1.0, 900).cumsum()
    index = pd.date_range("2026-01-05", periods=len(close), freq="5min")
    bars = pd.DataFrame(
        {"open": close, "high": close + 0.8, "low": close - 0.8, "close": close}, index=index
    )

    def features(frame: pd.DataFrame) -> pd.DataFrame:
        swings = swing_points(frame, length=3)
        structure = market_structure(frame, swings)
        levels = reference_levels(frame)
        sweep = sweeps(frame, levels["session_low"], reclaim_bars=3, side="low")
        return pd.DataFrame(
            {
                "swing_high": swings["swing_high"],
                "swing_low": swings["swing_low"],
                "trend": structure["trend"],
                "session_low": levels["session_low"],
                "prev_day_high": levels["prev_day_high"],
                "sweep": sweep["confirmed"].astype(float),
            }
        )

    assert_causal(features, bars, min_bars=300)
