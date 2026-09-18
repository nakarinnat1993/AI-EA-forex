import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import assert_causal
from research.strategies import AsianBreakoutParams, random_matched_signals
from research.strategies.asian_breakout import generate_signals

PARAMS = AsianBreakoutParams(swing_len_h1=2, min_sl_distance=1.0)


def uptrend_h1():
    # swing high ที่ 14 ถูกปิดทะลุที่ 16 → bias ขาขึ้น แล้วขึ้นต่อ
    closes = [10, 11, 14, 11, 10, 11, 16, 17, 18, 19, 20, 21]
    index = pd.date_range("2026-09-13 00:00", periods=len(closes), freq="h")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c}, index=index)


def breakout_day(breakout_close: float):
    index = pd.date_range("2026-09-14 00:00", "2026-09-14 09:00", freq="5min")
    frame = pd.DataFrame({"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0}, index=index)
    after = frame.index.hour >= 7
    frame.loc[after, ["open", "high", "low", "close"]] = [101.5, 101.8, 101.2, 101.5]
    frame.loc["2026-09-14 07:30", ["high", "close"]] = [max(102.8, breakout_close), breakout_close]
    frame.loc["2026-09-14 07:30", "low"] = min(101.2, breakout_close)
    return frame


def test_first_close_outside_asian_range_with_bias_is_a_signal():
    m5 = breakout_day(102.6)
    signals, setups = generate_signals(m5, uptrend_h1(), PARAMS)

    emitted = signals[signals["side"] != 0]
    assert list(emitted.index) == [pd.Timestamp("2026-09-14 07:30")]
    row = emitted.iloc[0]
    assert row["side"] == 1
    assert row["sl"] == pytest.approx(101.0)  # กึ่งกลาง Asian range 100–102
    assert row["tp"] == pytest.approx(102.6 + 2 * 1.6)
    assert np.isnan(row["entry"])  # เข้าราคาตลาด


def test_first_breakout_against_bias_blocks_the_whole_day():
    m5 = breakout_day(99.0)  # ทะลุลงก่อน ขณะที่ bias ขาขึ้น
    m5.loc["2026-09-14 08:00", ["high", "close"]] = [103.0, 102.9]  # ทะลุขึ้นทีหลัง ต้องไม่นับ
    signals, setups = generate_signals(m5, uptrend_h1(), PARAMS)

    assert (signals["side"] == 0).all()
    assert setups["outcome"].tolist() == ["against_bias"]


def test_breakout_strategy_never_looks_ahead():
    rng = np.random.default_rng(21)
    index = pd.date_range("2026-01-05", periods=15 * 288, freq="5min")
    close = 4400 + rng.normal(0, 0.9, len(index)).cumsum()
    open_ = np.r_[close[0], close[:-1]]
    m5 = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + rng.uniform(0.1, 1.5, len(index)),
            "low": np.minimum(open_, close) - rng.uniform(0.1, 1.5, len(index)),
            "close": close,
        },
        index=index,
    )
    h1 = m5.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    params = AsianBreakoutParams(min_sl_distance=1.0)

    signals, _ = generate_signals(m5, h1, params)
    assert (signals["side"] != 0).any()
    assert_causal(lambda frame: generate_signals(frame, h1, params)[0], m5, n_checks=3, min_bars=1500)


def test_random_baseline_matches_market_order_geometry():
    m5 = breakout_day(102.6)
    signals, _ = generate_signals(m5, uptrend_h1(), PARAMS)
    randomized = random_matched_signals(m5, signals, seed=3, session_start_hour=7, session_end_hour=9)
    row = randomized[randomized["side"] != 0].iloc[0]
    close = m5.loc[row.name, "close"]
    s = row["side"]

    assert np.isnan(row["entry"])
    assert (close - row["sl"]) * s == pytest.approx(1.6)
    assert (row["tp"] - close) * s == pytest.approx(3.2)
