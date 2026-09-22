import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import assert_causal
from research.strategies import FvgParams, PullbackParams
from research.strategies.fvg import generate_signals as fvg_signals
from research.strategies.pullback import generate_signals as pullback_signals
from research.strategies.pullback import high_volatility


def uptrend_htf():
    closes = [10, 11, 14, 11, 10, 11, 16, 17, 18, 19, 20, 21]
    index = pd.date_range("2026-09-13 00:00", periods=len(closes), freq="h")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c}, index=index)


def test_bullish_gap_gives_buy_limit_at_gap_top():
    index = pd.date_range("2026-09-14 06:00", periods=24, freq="15min")
    bars = pd.DataFrame({"open": 100.0, "high": 100.3, "low": 99.7, "close": 100.0}, index=index)
    i = 20  # 11:00 — ในช่วงเทรด
    bars.iloc[i - 2] = [99.5, 100.0, 98.0, 99.8]  # high 100.0 / low 98.0
    bars.iloc[i - 1] = [100.0, 104.5, 99.5, 104.0]  # แท่งเขียวที่พุ่ง
    bars.iloc[i] = [104.0, 104.8, 101.0, 103.0]  # low 101 > high[i-2] 100 → ช่องว่าง 100–101
    params = FvgParams(swing_len_h1=2, min_sl_distance=1.0)

    signals, setups = fvg_signals(bars, uptrend_htf(), params)

    row = signals.iloc[i]
    assert row["side"] == 1
    assert row["entry"] == pytest.approx(101.0)
    assert row["cancel_price"] == pytest.approx(100.0)
    assert row["sl"] < 98.0
    assert (row["tp2"] - row["entry"]) == pytest.approx(2 * (row["tp"] - row["entry"]))
    assert (signals["side"] != 0).sum() == 1


def test_fvg_never_looks_ahead():
    rng = np.random.default_rng(9)
    index = pd.date_range("2026-01-05", periods=40 * 96, freq="15min")
    close = 4400 + rng.normal(0, 2.0, len(index)).cumsum()
    open_ = np.r_[close[0], close[:-1]]
    bars = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + rng.uniform(0.2, 2.5, len(index)),
            "low": np.minimum(open_, close) - rng.uniform(0.2, 2.5, len(index)),
            "close": close,
        },
        index=index,
    )
    htf = bars.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    params = FvgParams(min_sl_distance=1.0)

    signals, _ = fvg_signals(bars, htf, params)
    assert (signals["side"] != 0).any()
    assert_causal(lambda frame: fvg_signals(frame, htf, params)[0], bars, n_checks=3, min_bars=1000)


def calm_then_wild_htf():
    index = pd.date_range("2024-01-01", periods=800 * 24, freq="h")
    ranges = np.where(index < pd.Timestamp("2025-05-15"), 1.0, 3.0)
    return pd.DataFrame(
        {"open": 100.0, "high": 100.0 + ranges / 2, "low": 100.0 - ranges / 2, "close": 100.0}, index=index
    )


def test_volatility_filter_needs_a_full_year_and_beats_the_trailing_median():
    htf = calm_then_wild_htf()

    def flag_at(day: str) -> bool:
        m5_index = pd.date_range(f"{day} 10:00", periods=3, freq="5min")
        return bool(high_volatility(m5_index, htf, atr_period=14)[-1])

    assert not flag_at("2024-06-01")  # ยังมีประวัติไม่ครบปี
    assert not flag_at("2025-03-01")  # ความผันผวนเท่า median
    assert flag_at("2025-08-01")  # สูงกว่า median ย้อนหลัง 365 วัน


def test_volatility_filter_never_looks_ahead():
    htf = calm_then_wild_htf()
    index = pd.date_range("2025-05-10", periods=4000, freq="5min")

    def flags(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"high": high_volatility(frame.index, htf, 14).astype(float)}, index=frame.index)

    bars = pd.DataFrame({"close": 100.0}, index=index)
    assert_causal(flags, bars, n_checks=3, min_bars=500)
    assert flags(bars)["high"].iloc[0] == 0.0 and flags(bars)["high"].iloc[-1] == 1.0


def test_volatility_filter_only_removes_pullback_signals():
    rng = np.random.default_rng(5)
    index = pd.date_range("2024-01-01", periods=420 * 96, freq="15min")
    close = 2000 + rng.normal(0, 1.5, len(index)).cumsum()
    open_ = np.r_[close[0], close[:-1]]
    m15 = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + rng.uniform(0.2, 3.0, len(index)),
            "low": np.minimum(open_, close) - rng.uniform(0.2, 3.0, len(index)),
            "close": close,
        },
        index=index,
    )
    h1 = m15.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    base, _ = pullback_signals(m15, h1, PullbackParams(min_sl_distance=1.0))
    filtered, _ = pullback_signals(m15, h1, PullbackParams(min_sl_distance=1.0, vol_filter=True))

    assert set(filtered.index[filtered["side"] != 0]) <= set(base.index[base["side"] != 0])
