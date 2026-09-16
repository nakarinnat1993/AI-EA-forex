from dataclasses import replace

import pytest

from research.backtest.sizing import lots_for_risk
from tests.helpers import CENT_SPEC


@pytest.mark.parametrize(
    "sl_distance, expected_lots",
    [(6.0, 0.08), (8.0, 0.06), (10.0, 0.05), (12.0, 0.04)],
)
def test_matches_spec_table_for_50_usd_at_1_pct(sl_distance, expected_lots):
    # ตารางใน reference/XAUUSDc-exness-spec.md
    assert lots_for_risk(50.0, 1.0, 4400.0, 4400.0 - sl_distance, CENT_SPEC) == pytest.approx(expected_lots)


def test_rounds_down_never_up():
    # 0.50 / 7.16 = 0.0698 → ต้องได้ 0.06 ไม่ใช่ 0.07
    assert lots_for_risk(50.0, 1.0, 4400.0, 4392.84, CENT_SPEC) == pytest.approx(0.06)


def test_returns_zero_instead_of_forcing_min_lot():
    # 0.50 / 60 = 0.0083 < 0.01 → ข้ามไม้ ไม่ใช่ใช้ 0.01 ซึ่งเสี่ยง 1.2%
    assert lots_for_risk(50.0, 1.0, 4400.0, 4340.0, CENT_SPEC) == 0.0


def test_standard_contract_cannot_size_a_50_usd_account():
    standard = replace(CENT_SPEC, name="XAUUSD", contract_size=100.0)
    assert lots_for_risk(50.0, 1.0, 4400.0, 4392.0, standard) == 0.0
