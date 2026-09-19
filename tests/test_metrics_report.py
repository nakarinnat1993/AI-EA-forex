import json

import pytest

from research.backtest.costs import CostModel
from research.backtest.engine import RiskConfig, run_backtest
from research.backtest.metrics import summarize
from research.backtest.report import count_trials, write_report
from tests.helpers import CENT_SPEC, make_bars, make_signals


def sample_result():
    bars = make_bars([
        ("2026-09-14 10:00", 100.0, 101.0, 99.0, 100.5),
        ("2026-09-14 10:05", 101.0, 101.5, 100.8, 101.2),
        ("2026-09-14 10:10", 101.2, 111.0, 101.0, 110.0),
        ("2026-09-15 10:00", 110.0, 110.5, 109.5, 110.0),
        ("2026-09-15 10:05", 110.0, 110.5, 109.8, 110.2),
        ("2026-09-15 10:10", 110.2, 110.4, 104.0, 104.5),
    ])
    signals = make_signals(bars, {"2026-09-14 10:00": (1, 96.0, 110.0), "2026-09-15 10:00": (1, 105.0, 120.0)})
    return run_backtest(bars, signals, CENT_SPEC, CostModel(), RiskConfig(50.0, 1.0))


def test_summary_is_json_serializable_and_consistent():
    result = sample_result()
    summary = summarize(result)
    json.dumps(summary)

    assert summary["n_trades"] == 2
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["total_pnl_usd"] == pytest.approx(sum(t.pnl_usd for t in result.trades))
    assert summary["by_exit_reason"]["tp"]["n"] == 1
    assert any("too few" in w for w in summary["warnings"])


def test_every_report_is_counted_as_a_trial(tmp_path):
    result = sample_result()
    summary = summarize(result)
    for params in ({"lookback": 5}, {"lookback": 7}):
        write_report(result, summary, "demo", params, {"from": "2026-09-14", "to": "2026-09-15"}, out_dir=tmp_path)

    assert count_trials("demo", out_dir=tmp_path) == 2

    write_report(result, summary, "demo@M1/biasM15", {"lookback": 5}, {}, out_dir=tmp_path)
    assert count_trials("demo@M1/biasM15", out_dir=tmp_path) == 1
    assert count_trials("other", out_dir=tmp_path) == 0
    assert len(list(tmp_path.glob("*_trades.csv"))) == 3
