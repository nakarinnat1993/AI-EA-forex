import json

import pandas as pd

from research.backtest.news import blackout_for_bars, news_blackout
from research.data.calendar import load_calendar

CALENDAR_CSV = """time_server,currency,importance,time_mode,event_id,name
2026.09.04 12:30,USD,high,datetime,1,"Nonfarm Payrolls"
2026.09.04 12:30,USD,moderate,datetime,2,"Average Hourly Earnings, m/m"
2026.09.07 00:00,USD,high,date,3,"Labor Day"
2026.09.10 08:00,EUR,high,datetime,4,"ECB Interest Rate Decision"
"""


def bar_times(*hhmm, day="2026-09-04"):
    return pd.DatetimeIndex([f"{day} {t}" for t in hhmm])


def test_window_includes_start_and_excludes_end():
    bars = bar_times("11:55", "12:00", "12:25", "12:55", "13:00")
    mask = news_blackout(bars, ["2026-09-04 12:30"], minutes_before=30, minutes_after=30)

    assert mask.tolist() == [False, True, True, True, False]


def test_each_event_gets_its_own_window():
    bars = bar_times("13:05", "13:30", "14:25", "14:30")
    mask = news_blackout(bars, ["2026-09-04 14:00", "2026-09-04 12:30"], minutes_before=30, minutes_after=30)

    assert mask.tolist() == [False, True, True, False]


def test_no_events_means_no_blackout():
    assert not news_blackout(bar_times("12:30"), [], 30, 30).any()


def test_calendar_keeps_only_timed_events_of_chosen_currency_and_importance(tmp_path):
    csv = tmp_path / "calendar.csv"
    csv.write_text(CALENDAR_CSV)

    usd_high = load_calendar(csv)
    assert usd_high["name"].tolist() == ["Nonfarm Payrolls"]

    wider = load_calendar(csv, currencies=("USD", "EUR"), min_importance="moderate")
    assert "Labor Day" not in wider["name"].tolist()
    assert len(wider) == 3


def test_blackout_for_bars_reads_config(tmp_path):
    csv = tmp_path / "calendar.csv"
    csv.write_text(CALENDAR_CSV)
    config = tmp_path / "news_filter.json"
    config.write_text(json.dumps({"currencies": ["USD"], "min_importance": "high", "minutes_before": 10, "minutes_after": 5}))

    mask = blackout_for_bars(bar_times("12:15", "12:20", "12:30", "12:35"), csv, config)

    assert mask.tolist() == [False, True, True, False]
