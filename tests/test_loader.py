import json

import pytest

from research.data.loader import (
    HoldoutAlreadyOpenedError,
    HoldoutNotSetError,
    load_research_bars,
    open_holdout,
)

CSV = """time,open,high,low,close,tick_volume,spread,real_volume
2026.01.05 00:00,4400.100,4401.000,4399.500,4400.500,10,250,0
2026.06.01 00:00,4500.100,4501.000,4499.500,4500.500,12,300,0
2026.09.01 00:00,4600.100,4601.000,4599.500,4600.500,15,200,0
"""


def write_export(tmp_path, price_side="bid"):
    csv = tmp_path / "XAUUSDc_M5.csv"
    csv.write_text(CSV)
    meta = {"symbol": "XAUUSDc", "timeframe": "M5", "digits": 3, "point": 0.001, "price_side": price_side}
    (tmp_path / "XAUUSDc_M5.meta.json").write_text(json.dumps(meta))
    return csv


def write_split(tmp_path, holdout_start):
    split = tmp_path / "data_split.json"
    split.write_text(json.dumps({"holdout_start": holdout_start}))
    return split


def test_refuses_to_load_until_holdout_is_set(tmp_path):
    with pytest.raises(HoldoutNotSetError):
        load_research_bars(write_export(tmp_path), write_split(tmp_path, None))


def test_research_data_excludes_holdout(tmp_path):
    bars = load_research_bars(write_export(tmp_path), write_split(tmp_path, "2026-06-01"))

    assert len(bars) == 1
    assert bars.index[-1].month == 1
    assert bars["spread_price"].iloc[0] == pytest.approx(0.25)


def test_holdout_can_be_opened_only_once(tmp_path):
    csv = write_export(tmp_path)
    split = write_split(tmp_path, "2026-06-01")
    log = tmp_path / "HOLDOUT_LOG.md"

    holdout = open_holdout(csv, "final validation of v1", split, log)
    assert len(holdout) == 2
    assert "final validation of v1" in log.read_text()

    with pytest.raises(HoldoutAlreadyOpenedError):
        open_holdout(csv, "one more look", split, log)


def test_rejects_exports_not_priced_by_bid(tmp_path):
    with pytest.raises(ValueError, match="bid"):
        load_research_bars(write_export(tmp_path, price_side="last"), write_split(tmp_path, "2026-06-01"))
