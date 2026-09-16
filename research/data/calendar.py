"""โหลดปฏิทินข่าวที่ส่งออกจาก MT5 (ExportCalendar.mq5) — เวลาเป็นเวลา trade server"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

IMPORTANCE_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}


def load_calendar(
    csv_path: str | Path,
    currencies: tuple[str, ...] | list[str] = ("USD",),
    min_importance: str = "high",
) -> pd.DataFrame:
    """คืนเฉพาะข่าวที่มีเวลาแน่นอน — ข่าวแบบทั้งวันหรือยังไม่กำหนดเวลาถูกตัดทิ้ง"""
    events = pd.read_csv(csv_path)
    events["time"] = pd.to_datetime(events["time_server"], format="%Y.%m.%d %H:%M")
    keep = (
        events["currency"].isin(list(currencies))
        & (events["importance"].map(IMPORTANCE_RANK) >= IMPORTANCE_RANK[min_importance])
        & (events["time_mode"] == "datetime")
    )
    columns = ["time", "currency", "importance", "name"]
    return events.loc[keep, columns].sort_values("time").reset_index(drop=True)
