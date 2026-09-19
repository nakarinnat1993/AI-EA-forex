import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import assert_causal
from research.strategies import PullbackParams, random_matched_signals
from research.strategies.pullback import generate_signals

PARAMS = PullbackParams(min_sl_distance=1.0)


@pytest.fixture(scope="module")
def market():
    rng = np.random.default_rng(5)
    index = pd.date_range("2026-01-05", periods=20 * 288, freq="5min")
    close = 4400 + rng.normal(0.02, 0.9, len(index)).cumsum()
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
    signals, setups = generate_signals(m5, h1, PARAMS)
    return m5, h1, signals, setups


def test_signals_follow_the_locked_rules(market):
    m5, _, signals, setups = market
    emitted = signals[signals["side"] != 0]
    assert len(emitted) > 0

    for time, row in emitted.iterrows():
        s = int(row["side"])
        risk = (row["entry"] - row["sl"]) * s
        room = (row["tp"] - row["entry"]) * s

        assert PARAMS.session_start_hour <= time.hour < PARAMS.session_end_hour
        assert risk >= PARAMS.min_sl_distance
        assert PARAMS.min_room_r * risk - 1e-9 <= room <= PARAMS.tp1_max_r * risk + 1e-9
        assert (row["tp2"] - row["entry"]) == pytest.approx(2 * (row["tp"] - row["entry"]))
        assert (m5.loc[time, "close"] - row["entry"]) * s > 0  # ราคายังไม่ย่อกลับมา
        assert (row["cancel_price"] - row["sl"]) * s > 0

    signal_setups = setups[setups["outcome"] == "signal"]
    assert np.allclose(signal_setups["level"].to_numpy(), emitted["entry"].to_numpy())


def test_pullback_never_looks_ahead(market):
    m5, h1, _, _ = market
    assert_causal(lambda frame: generate_signals(frame, h1, PARAMS)[0], m5, n_checks=3, min_bars=2000)


def test_random_baseline_keeps_both_targets(market):
    m5, _, signals, _ = market
    reference = signals[signals["side"] != 0]
    randomized = random_matched_signals(m5, signals, seed=2)
    emitted = randomized[randomized["side"] != 0]

    def distances(frame, column):
        return sorted(((frame[column] - frame["entry"]) * frame["side"]).round(6))

    assert distances(emitted, "tp") == distances(reference, "tp")
    assert distances(emitted, "tp2") == distances(reference, "tp2")
