"""สเปก symbol และโมเดลต้นทุน (spread / slippage / swap / commission)

หน่วย:
- spread และ slippage เป็น "หน่วยราคา" ($ ต่อออนซ์) ไม่ขึ้นกับ digits ของ symbol
  → ใช้ข้อมูลราคาจาก XAUUSD หรือ XAUUSDc ก็ได้ ราคาทองตัวเดียวกัน
- swap เป็น points ตามที่โบรกแจ้ง แปลงด้วย point ของ symbol ที่ใช้เทรดจริง
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SymbolSpec:
    """สเปกของ symbol ที่ EA จะเทรดจริง — ใช้คิดขนาดไม้และ swap"""

    name: str
    digits: int
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float

    @property
    def point(self) -> float:
        return 10.0**-self.digits


@dataclass(frozen=True)
class CostModel:
    min_spread_price: float = 0.0
    spread_multiplier: float = 1.0
    entry_slippage_price: float = 0.0
    stop_slippage_price: float = 0.0
    commission_per_lot_roundturn: float = 0.0
    swap_long_points: float = 0.0
    swap_short_points: float = 0.0
    swap_multipliers: dict[int, int] = field(default_factory=dict)  # weekday (จันทร์=0) → ตัวคูณ
    rollover_hour: int = 0

    def effective_spread(self, bar_spread_price: np.ndarray) -> np.ndarray:
        # สเปรดในแท่งจาก MT5 มักเป็นค่าต่ำสุดของแท่ง → ตั้งพื้นขั้นต่ำกันมองโลกแง่ดีเกินจริง
        return np.maximum(bar_spread_price, self.min_spread_price) * self.spread_multiplier

    def swap_usd(self, side: int, oz: float, point: float, weekday: int) -> float:
        points = self.swap_long_points if side > 0 else self.swap_short_points
        return points * point * oz * self.swap_multipliers.get(weekday, 0)


def load_cost_config(path: str | Path) -> tuple[SymbolSpec, CostModel]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    spec = SymbolSpec(**raw["symbol"])
    costs = dict(raw["costs"])
    costs["swap_multipliers"] = {int(k): int(v) for k, v in costs.get("swap_multipliers", {}).items()}
    return spec, CostModel(**costs)
