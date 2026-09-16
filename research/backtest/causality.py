"""ตัวตรวจ look-ahead bias แบบกลไก

หลักการ: signal ของแท่ง k ต้องคำนวณได้จากข้อมูลถึงแท่ง k เท่านั้น
ดังนั้นถ้าตัดข้อมูลทิ้งหลังแท่ง k แล้วคำนวณใหม่ ผลของแท่ง 0..k ต้องเหมือนเดิมทุกค่า
ถ้าไม่เหมือน = กลยุทธ์แอบใช้ข้อมูลอนาคต

รันกับทุกกลยุทธ์ก่อน backtest — ห้ามข้าม
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], pd.DataFrame]


class LookAheadError(AssertionError):
    pass


def assert_causal(
    signal_fn: SignalFn,
    bars: pd.DataFrame,
    n_checks: int = 5,
    min_bars: int = 500,
    seed: int = 0,
) -> None:
    if len(bars) <= min_bars:
        raise ValueError(f"need more than {min_bars} bars to check causality")
    full = signal_fn(bars)
    rng = np.random.default_rng(seed)
    cuts = sorted(set(rng.integers(min_bars, len(bars), size=n_checks).tolist()))
    for k in cuts:
        partial = signal_fn(bars.iloc[:k])
        expected = full.iloc[:k]
        if not partial.index.equals(expected.index) or list(partial.columns) != list(expected.columns):
            raise LookAheadError(f"signal shape changed when data was cut at bar {k}")
        mismatch = ~np.isclose(
            partial.to_numpy(float), expected.to_numpy(float), rtol=0.0, atol=1e-9, equal_nan=True
        )
        if mismatch.any():
            row, col = np.argwhere(mismatch)[0]
            raise LookAheadError(
                f"look-ahead detected: column '{expected.columns[col]}' at {expected.index[row]} "
                f"is {expected.iat[row, col]} with full data but {partial.iat[row, col]} "
                f"when data ends at {bars.index[k - 1]}"
            )
