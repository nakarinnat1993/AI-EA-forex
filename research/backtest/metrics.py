from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .engine import BacktestResult, Trade

AMBIGUOUS_WARN_SHARE = 0.05
MIN_TRADES_FOR_CONCLUSION = 100


def summarize(result: BacktestResult) -> dict:
    trades = result.trades
    equity = result.equity
    final_equity = float(equity.iloc[-1]) if len(equity) else result.initial_equity
    summary: dict = {
        "initial_equity": result.initial_equity,
        "final_equity": final_equity,
        "return_pct": (final_equity / result.initial_equity - 1) * 100,
        "n_trades": len(trades),
        "skipped_signals": dict(result.skipped),
        "warnings": [],
    }
    if not trades:
        summary["warnings"].append("no trades")
        return summary

    pnl = np.array([t.pnl_usd for t in trades])
    r = np.array([t.r_multiple for t in trades])
    gross_win = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    ambiguous = sum(t.ambiguous for t in trades)

    daily_equity = equity.groupby(equity.index.normalize()).last()
    daily_returns = daily_equity.pct_change().dropna()
    std = daily_returns.std()

    summary.update(
        {
            "win_rate": float((pnl > 0).mean()),
            "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else None,
            "expectancy_usd": float(pnl.mean()),
            "expectancy_r": float(r.mean()),
            "avg_win_r": float(r[r > 0].mean()) if (r > 0).any() else None,
            "avg_loss_r": float(r[r < 0].mean()) if (r < 0).any() else None,
            "total_pnl_usd": float(pnl.sum()),
            "max_drawdown_pct": float((equity / equity.cummax() - 1).min() * 100),
            "sharpe_daily_annualized": float(daily_returns.mean() / std * math.sqrt(252))
            if len(daily_returns) > 1 and std > 0
            else None,
            "avg_hold_minutes": float(np.mean([_hold_minutes(t) for t in trades])),
            "trades_per_active_day": float(len(trades) / len({t.entry_time.normalize() for t in trades})),
            "ambiguous_exits": int(ambiguous),
            "costs_usd": {
                "spread": float(sum(t.spread_cost_usd for t in trades)),
                "slippage_and_gaps": float(sum(t.slippage_cost_usd for t in trades)),
                "swap": float(sum(t.swap_usd for t in trades)),
                "commission": float(sum(t.commission_usd for t in trades)),
            },
            "by_side": _group(trades, lambda t: "long" if t.side > 0 else "short"),
            "by_exit_reason": _group(trades, lambda t: t.exit_reason),
            "by_year": _group(trades, lambda t: str(t.entry_time.year)),
            "by_month": _group(trades, lambda t: t.entry_time.strftime("%Y-%m")),
        }
    )

    if len(trades) < MIN_TRADES_FOR_CONCLUSION:
        summary["warnings"].append(f"only {len(trades)} trades — too few to conclude anything")
    if ambiguous / len(trades) > AMBIGUOUS_WARN_SHARE:
        summary["warnings"].append(
            f"{ambiguous / len(trades):.1%} of exits hit SL and TP in the same bar — "
            "results depend on bar resolution, re-check with M1"
        )
    if result.skipped.get("below_min_lot"):
        summary["warnings"].append(
            f"{result.skipped['below_min_lot']} signals skipped because size fell below min lot"
        )
    return summary


def _hold_minutes(trade: Trade) -> float:
    return (trade.exit_time - trade.entry_time).total_seconds() / 60


def _group(trades: list[Trade], key) -> dict:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    out = {}
    for name in sorted(groups):
        items = groups[name]
        pnl = np.array([t.pnl_usd for t in items])
        out[name] = {
            "n": len(items),
            "pnl_usd": float(pnl.sum()),
            "win_rate": float((pnl > 0).mean()),
            "expectancy_r": float(np.mean([t.r_multiple for t in items])),
        }
    return out
