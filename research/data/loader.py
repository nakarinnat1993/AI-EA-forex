"""โหลดแท่งราคาที่ส่งออกจาก MT5 (ExportBars.mq5) พร้อมตัวล็อก holdout

ใช้ load_research_bars() สำหรับงานวิจัยทุกครั้ง — มันตัดช่วง holdout ทิ้งให้อัตโนมัติ
open_holdout() เปิดดูช่วง holdout ได้ครั้งเดียวตลอดโปรเจกต์ และบันทึกเหตุผลลง journal
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPLIT = REPO_ROOT / "config" / "data_split.json"
DEFAULT_HOLDOUT_LOG = REPO_ROOT / "journal" / "HOLDOUT_LOG.md"
_OPENED_MARKER = "## OPENED"


class HoldoutNotSetError(RuntimeError):
    pass


class HoldoutAlreadyOpenedError(RuntimeError):
    pass


def read_mt5_bars(csv_path: str | Path) -> pd.DataFrame:
    """อ่านไฟล์ดิบ — ไม่ตัด holdout ห้ามใช้ตรง ๆ ในงานวิจัย"""
    csv_path = Path(csv_path)
    meta_path = csv_path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise FileNotFoundError(f"missing {meta_path.name} — export again with ExportBars.mq5")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("price_side") != "bid":
        raise ValueError(f"engine assumes bid prices, export says price_side={meta.get('price_side')!r}")

    bars = pd.read_csv(csv_path)
    bars["time"] = pd.to_datetime(bars["time"], format="%Y.%m.%d %H:%M")
    bars = bars.set_index("time").sort_index()
    if bars.index.has_duplicates:
        raise ValueError(f"{csv_path.name} has duplicate bar times")
    bars["spread_price"] = bars["spread"] * float(meta["point"])
    bars.attrs["meta"] = meta
    return bars


def load_research_bars(csv_path: str | Path, split_path: str | Path = DEFAULT_SPLIT) -> pd.DataFrame:
    holdout_start = _holdout_start(split_path)
    bars = read_mt5_bars(csv_path)
    research = bars[bars.index < holdout_start]
    research.attrs["meta"] = bars.attrs["meta"]
    return research


def open_holdout(
    csv_path: str | Path,
    reason: str,
    split_path: str | Path = DEFAULT_SPLIT,
    log_path: str | Path = DEFAULT_HOLDOUT_LOG,
) -> pd.DataFrame:
    if not reason.strip():
        raise ValueError("opening the holdout requires a written reason")
    log_path = Path(log_path)
    if log_path.exists() and _OPENED_MARKER in log_path.read_text(encoding="utf-8"):
        raise HoldoutAlreadyOpenedError(
            f"holdout was already opened — see {log_path}. It cannot be used for validation again."
        )
    holdout_start = _holdout_start(split_path)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{_OPENED_MARKER} {datetime.now():%Y-%m-%d %H:%M}\n\n- file: {Path(csv_path).name}\n- reason: {reason}\n")
    bars = read_mt5_bars(csv_path)
    holdout = bars[bars.index >= holdout_start]
    holdout.attrs["meta"] = bars.attrs["meta"]
    return holdout


def _holdout_start(split_path: str | Path) -> pd.Timestamp:
    split = json.loads(Path(split_path).read_text(encoding="utf-8"))
    if split.get("holdout_start") is None:
        raise HoldoutNotSetError(
            f"set holdout_start in {split_path} before loading any research data "
            "(pick it once from the first export and never move it)"
        )
    return pd.Timestamp(split["holdout_start"])
