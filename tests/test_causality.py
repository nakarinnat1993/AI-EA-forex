import numpy as np
import pandas as pd
import pytest

from research.backtest.causality import LookAheadError, assert_causal


def random_walk_bars(n: int = 600, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 4400 + rng.normal(0, 0.5, n).cumsum()
    index = pd.date_range("2026-01-05", periods=n, freq="5min")
    return pd.DataFrame({"open": close, "high": close + 0.3, "low": close - 0.3, "close": close}, index=index)


def causal_signals(bars: pd.DataFrame) -> pd.DataFrame:
    side = (bars["close"] > bars["close"].rolling(20).mean()).astype(int)
    return pd.DataFrame({"side": side, "sl": bars["close"] - 5, "tp": bars["close"] + 10})


def peeking_signals(bars: pd.DataFrame) -> pd.DataFrame:
    side = np.sign(bars["close"].shift(-1) - bars["close"]).fillna(0).astype(int)
    return pd.DataFrame({"side": side, "sl": bars["close"] - 5, "tp": bars["close"] + 10})


def test_causal_strategy_passes():
    assert_causal(causal_signals, random_walk_bars(), min_bars=100)


def test_strategy_using_next_bar_is_caught():
    with pytest.raises(LookAheadError, match="look-ahead detected"):
        assert_causal(peeking_signals, random_walk_bars(), min_bars=100)
