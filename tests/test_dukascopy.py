import lzma

import numpy as np
import pandas as pd
import pytest

from research.data.dukascopy import decode_day, resample


def write_bi5(path, rows):
    """rows: (seconds, open, close, low, high) เป็นราคาจริง"""
    records = bytearray()
    for seconds, open_, close, low, high in rows:
        ints = np.array([seconds, open_ * 1000, close * 1000, low * 1000, high * 1000], dtype=">u4")
        records += ints.tobytes() + np.array([1.0], dtype=">f4").tobytes()
    path.write_bytes(lzma.compress(bytes(records), format=lzma.FORMAT_ALONE))


def test_decodes_field_order_open_close_low_high(tmp_path):
    path = tmp_path / "day.bi5"
    write_bi5(path, [(0, 3320.075, 3320.725, 3319.925, 3321.465)])

    bars = decode_day(path, pd.Timestamp("2025-05-22"))

    assert bars.index[0] == pd.Timestamp("2025-05-22 00:00")
    row = bars.iloc[0]
    assert (row.open, row.high, row.low, row.close) == pytest.approx((3320.075, 3321.465, 3319.925, 3320.725))


def test_resample_drops_flat_filler_minutes():
    index = pd.date_range("2025-05-22 07:00", periods=6, freq="1min")
    m1 = pd.DataFrame(
        {
            "open": [100, 101, 102, 102, 103, 104],
            "high": [101, 102, 103, 102, 104, 105],
            "low": [99, 100, 101, 102, 102, 103],
            "close": [101, 102, 102, 102, 104, 104],
        },
        index=index,
        dtype=float,
    )
    bars = resample(m1, "5min")

    assert list(bars.index) == [pd.Timestamp("2025-05-22 07:00"), pd.Timestamp("2025-05-22 07:05")]
    first = bars.iloc[0]
    assert (first.open, first.high, first.low, first.close) == (100, 104, 99, 104)
