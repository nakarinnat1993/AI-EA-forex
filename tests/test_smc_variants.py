from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from research.strategies import SmcV0Params, generate_signals

BASE = SmcV0Params(min_sl_distance=1.0)


@pytest.fixture(scope="module")
def market():
    rng = np.random.default_rng(11)
    index = pd.date_range("2026-01-05", periods=20 * 288, freq="5min")
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
    return m5, h1


def signal_rows(m5, h1, params):
    signals, setups = generate_signals(m5, h1, params)
    return signals[signals["side"] != 0], setups


def test_sl_by_sweep_is_never_tighter_than_sl_by_block(market):
    m5, h1 = market
    block, _ = signal_rows(m5, h1, BASE)
    sweep, _ = signal_rows(m5, h1, replace(BASE, sl_anchor="sweep"))
    common = block.index.intersection(sweep.index)

    assert len(common) > 0
    risk_block = (block.loc[common, "entry"] - block.loc[common, "sl"]) * block.loc[common, "side"]
    risk_sweep = (sweep.loc[common, "entry"] - sweep.loc[common, "sl"]) * sweep.loc[common, "side"]
    assert (risk_sweep >= risk_block - 1e-9).all()


def test_choch_only_and_min_depth_only_remove_setups(market):
    m5, h1 = market
    _, base_setups = signal_rows(m5, h1, BASE)
    for variant in (replace(BASE, require_choch=True), replace(BASE, min_sweep_depth_atr=0.1)):
        _, setups = signal_rows(m5, h1, variant)
        assert len(setups) <= len(base_setups)
        assert set(setups["break_time"]) <= set(base_setups["break_time"])
