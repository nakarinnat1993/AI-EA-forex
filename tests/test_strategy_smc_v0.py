import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import assert_causal
from research.strategies import SmcV0Params, generate_signals, random_matched_signals

PARAMS = SmcV0Params(min_sl_distance=1.0)
KNOWN_OUTCOMES = {
    "signal",
    "no_order_block",
    "order_block_used",
    "atr_not_ready",
    "price_inside_zone",
    "sl_too_tight",
    "opposite_signal_same_bar",
}


@pytest.fixture(scope="module")
def market():
    rng = np.random.default_rng(11)
    index = pd.date_range("2026-01-05", periods=20 * 288, freq="5min")
    close = 4400 + rng.normal(0, 0.9, len(index)).cumsum()
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.5, len(index))
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.5, len(index))
    m5 = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)
    h1 = m5.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    signals, setups = generate_signals(m5, h1, PARAMS)
    return m5, h1, signals, setups


def test_emits_signals_that_follow_the_written_rules(market):
    m5, _, signals, setups = market
    emitted = signals[signals["side"] != 0]
    assert len(emitted) > 0, "synthetic market should produce at least one setup"
    assert set(setups["outcome"]) <= KNOWN_OUTCOMES

    for time, row in emitted.iterrows():
        j = m5.index.get_loc(time)
        s = int(row["side"])
        risk = (row["entry"] - row["sl"]) * s

        assert PARAMS.session_start_hour <= time.hour < PARAMS.session_end_hour
        assert risk >= PARAMS.min_sl_distance
        assert (row["tp"] - row["entry"]) * s == pytest.approx(PARAMS.tp_r * risk)
        assert row["expiry_bars"] == PARAMS.order_expiry
        # SL อยู่เลยขอบโซนอีกฝั่ง, ราคาปัจจุบันยังไม่ย่อเข้าโซน
        assert (row["cancel_price"] - row["sl"]) * s > 0
        assert (row["entry"] - row["cancel_price"]) * s > 0
        assert (m5["close"].iloc[j] - row["entry"]) * s > 0

        # จุดเข้าและ cancel ต้องเป็นขอบของแท่งสีตรงข้ามจริง ที่เกิดก่อนหรือที่แท่ง signal
        past = m5.iloc[: j + 1]
        opposite = past["close"] < past["open"] if s == 1 else past["close"] > past["open"]
        top, bottom = (row["entry"], row["cancel_price"]) if s == 1 else (row["cancel_price"], row["entry"])
        match = opposite & np.isclose(past["high"], top) & np.isclose(past["low"], bottom)
        assert match.any()


def test_bias_from_m15_waits_for_the_m15_bar_to_close():
    from research.strategies.smc_v0 import h1_bias

    # โครงสร้าง M15 ทะลุขึ้นที่แท่ง 6 (09-14 01:30) ซึ่งปิดตอน 01:45
    closes = [10, 11, 14, 11, 10, 11, 16, 17]
    m15_index = pd.date_range("2026-09-14 00:00", periods=len(closes), freq="15min")
    c = np.asarray(closes, dtype=float)
    m15 = pd.DataFrame({"open": c, "high": c, "low": c, "close": c}, index=m15_index)
    m5_index = pd.date_range("2026-09-14 01:30", periods=4, freq="5min")

    bias = h1_bias(m5_index, m15, swing_len=2)

    # แท่ง M5 01:30 และ 01:35 ปิดก่อน 01:45 → ยังไม่รู้ / แท่ง 01:40 ปิดตอน 01:45 → รู้แล้ว
    assert bias.tolist() == [0, 0, 1, 1]


def test_strategy_never_looks_ahead(market):
    m5, h1, _, _ = market
    assert_causal(lambda frame: generate_signals(frame, h1, PARAMS)[0], m5, n_checks=3, min_bars=2000)


def test_random_baseline_keeps_trade_geometry(market):
    m5, _, signals, _ = market
    reference = signals[signals["side"] != 0]
    randomized = random_matched_signals(m5, signals, seed=1)
    emitted = randomized[randomized["side"] != 0]

    assert len(emitted) == len(reference)
    ref_risk = sorted(((reference["entry"] - reference["sl"]) * reference["side"]).round(6))
    new_risk = sorted(((emitted["entry"] - emitted["sl"]) * emitted["side"]).round(6))
    assert ref_risk == new_risk
    assert emitted.index.hour.min() >= 7 and emitted.index.hour.max() < 16


def test_random_baseline_is_reproducible_per_seed(market):
    m5, _, signals, _ = market
    first = random_matched_signals(m5, signals, seed=5)
    again = random_matched_signals(m5, signals, seed=5)
    other = random_matched_signals(m5, signals, seed=6)

    pd.testing.assert_frame_equal(first, again)
    assert not first.equals(other)
