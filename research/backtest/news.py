"""News blackout: ช่วงรอบข่าวแรงที่ห้ามเปิดไม้และต้องปิดไม้ที่ถืออยู่ (DECISIONS 2026-09-15)"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.data.calendar import load_calendar

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NEWS_CONFIG = REPO_ROOT / "config" / "news_filter.json"
_MINUTE_NS = 60 * 10**9


def news_blackout(
    bar_times: pd.DatetimeIndex, event_times, minutes_before: int, minutes_after: int
) -> np.ndarray:
    """True สำหรับแท่งที่เวลาเริ่มแท่งอยู่ในช่วง [ข่าว − before, ข่าว + after)"""
    t = bar_times.as_unit("ns").asi8
    events = np.sort(pd.DatetimeIndex(event_times).as_unit("ns").asi8)
    if events.size == 0:
        return np.zeros(len(t), dtype=bool)
    # อยู่ในช่วง ⇔ t − after < ข่าว ≤ t + before → พอดูข่าวแรกที่เกิดหลัง t − after
    first_after = np.searchsorted(events, t - minutes_after * _MINUTE_NS, side="right")
    candidate = events[np.minimum(first_after, events.size - 1)]
    return (first_after < events.size) & (candidate <= t + minutes_before * _MINUTE_NS)


def blackout_for_bars(
    bar_times: pd.DatetimeIndex, calendar_csv: str | Path, config_path: str | Path = DEFAULT_NEWS_CONFIG
) -> np.ndarray:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    events = load_calendar(calendar_csv, config["currencies"], config["min_importance"])
    return news_blackout(bar_times, events["time"], config["minutes_before"], config["minutes_after"])
