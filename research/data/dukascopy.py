"""ดึงแท่งราคาทองย้อนหลังฟรีจาก Dukascopy แล้วแปลงเป็นไฟล์รูปแบบเดียวกับ ExportBars.mq5

    .venv/bin/python -m research.data.dukascopy 2017-01-01 2026-09-16

เหตุผลที่ต้องใช้: เซิร์ฟเวอร์ Exness ส่ง M5 ได้แค่ 100,000 แท่ง (17 เดือน) ซึ่งให้ไม้น้อยเกินตัดสิน
ตรวจแล้วว่าใช้แทนกันได้ (2025-05-22): เวลา UTC ตรงกัน, correlation ราคาปิด 0.99999,
ช่วงแท่งเฉลี่ยต่างกัน $0.01, ราคา Exness สูงกว่าคงที่ ~$0.24 (ไม่ปรับ เพราะกลยุทธ์ดูรูปทรงราคา)

สเปรด: Dukascopy มีสเปรดของตัวเองซึ่งไม่ใช่ของ Exness → ใช้ **median สเปรดรายชั่วโมงของ Exness**
จากข้อมูลช่วง dev (ไม่แตะ holdout) ใส่ลงคอลัมน์ spread แทน

ไฟล์ดิบเก็บ cache ไว้ใน data/dukascopy/raw — ถ้าโดนบล็อกกลางทาง รันคำสั่งเดิมซ้ำจะโหลดต่อจากที่ค้าง
"""

from __future__ import annotations

import json
import lzma
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from research.data.loader import DEFAULT_SPLIT, read_mt5_bars

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "dukascopy" / "raw"
OUT_DIR = REPO_ROOT / "data" / "dukascopy"
EXNESS_M5 = REPO_ROOT / "data" / "mt5" / "XAUUSDc_M5.csv"
URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
PRICE_SCALE = 1000.0
POINT = 0.001
WORKERS = 2
REQUEST_DELAY_SECONDS = 0.25
# User-Agent ปกติของ Python โดน Dukascopy ตอบ 429 ทุกครั้ง และยิงพร้อมกัน 4 เส้นโดน 503 (ตรวจแล้ว 2026-09-17)
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_THROTTLED = (429, 500, 502, 503, 504)


def download_day(day: pd.Timestamp, retries: int = 6) -> Path | None:
    """เก็บไฟล์ดิบไว้ใน cache — รันซ้ำจะไม่โหลดซ้ำ / คืน None ถ้าวันนั้นไม่มีข้อมูล"""
    path = RAW_DIR / f"{day:%Y}" / f"{day:%Y%m%d}_BID_m1.bi5"
    empty_marker = path.with_suffix(".empty")
    if path.exists():
        return path
    if empty_marker.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    # เดือนใน URL ของ Dukascopy นับจาก 0
    url = URL.format(y=day.year, m=day.month - 1, d=day.day)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            time.sleep(REQUEST_DELAY_SECONDS)
            if not payload:
                empty_marker.touch()
                return None
            path.write_bytes(payload)
            return path
        except urllib.error.HTTPError as error:
            if error.code == 404:
                empty_marker.touch()
                return None
            last_error = error
            if error.code in _THROTTLED:
                retry_after = error.headers.get("Retry-After") if error.headers else None
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 5 * 2**attempt)
                time.sleep(wait)
                continue
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
        time.sleep(min(60, 2 ** (attempt + 1)))
    raise RuntimeError(f"download failed after {retries} attempts: {url} ({last_error})")


def download_day_or_failed(day: pd.Timestamp) -> Path | None | str:
    """เหมือน download_day แต่คืน "failed" แทนการโยน error เพื่อให้วันอื่นโหลดต่อได้"""
    try:
        return download_day(day)
    except RuntimeError:
        return "failed"


def decode_day(path: Path, day: pd.Timestamp) -> pd.DataFrame:
    """ระเบียนละ 24 ไบต์ big-endian: วินาทีจากเที่ยงคืน, open, close, low, high (×1000), volume (float)"""
    raw = lzma.decompress(path.read_bytes())
    records = np.frombuffer(raw, dtype=">u4").reshape(-1, 6)
    return pd.DataFrame(
        {
            "open": records[:, 1] / PRICE_SCALE,
            "high": records[:, 4] / PRICE_SCALE,
            "low": records[:, 3] / PRICE_SCALE,
            "close": records[:, 2] / PRICE_SCALE,
        },
        index=day + pd.to_timedelta(records[:, 0].astype(np.int64), unit="s"),
    )


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Dukascopy เติมนาทีที่ไม่มีการซื้อขายด้วยแท่งแบน (O=H=L=C) → ตัดทิ้งก่อนรวมแท่ง"""
    traded = m1[~((m1["open"] == m1["high"]) & (m1["high"] == m1["low"]) & (m1["low"] == m1["close"]))]
    bars = traded.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    return bars.dropna()


def exness_hourly_spread_points() -> pd.Series:
    """median สเปรดของ Exness แยกตามชั่วโมง (points) — เฉพาะช่วงก่อน holdout"""
    holdout_start = pd.Timestamp(json.loads(Path(DEFAULT_SPLIT).read_text(encoding="utf-8"))["holdout_start"])
    exness = read_mt5_bars(EXNESS_M5)
    dev = exness[exness.index < holdout_start]
    return dev.groupby(dev.index.hour)["spread"].median().reindex(range(24)).ffill().bfill()


def write_export(bars: pd.DataFrame, timeframe: str, spread_by_hour: pd.Series) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(
        {
            "time": bars.index.strftime("%Y.%m.%d %H:%M"),
            "open": bars["open"].round(3),
            "high": bars["high"].round(3),
            "low": bars["low"].round(3),
            "close": bars["close"].round(3),
            "tick_volume": 0,
            "spread": spread_by_hour.reindex(bars.index.hour).to_numpy().round().astype(int),
            "real_volume": 0,
        }
    )
    path = OUT_DIR / f"XAUUSD_{timeframe}.csv"
    out.to_csv(path, index=False)
    meta = {
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "digits": 3,
        "point": POINT,
        "contract_size": 1.0,
        "price_side": "bid",
        "server": "dukascopy",
        "server_gmt_offset_seconds": 0,
        "spread_source": "Exness XAUUSDc hourly median (dev period only)",
        "bars": int(len(bars)),
        "first_bar": str(bars.index[0]),
        "last_bar": str(bars.index[-1]),
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    days = [d for d in pd.date_range(sys.argv[1], sys.argv[2], freq="D") if d.weekday() != 5]
    print(f"ดาวน์โหลด {len(days):,} วัน (ข้ามวันเสาร์) ด้วย {WORKERS} เส้น ...", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(download_day_or_failed, days))

    failed = [day for day, result in zip(days, results) if result == "failed"]
    if failed:
        print(f"รอบแรกล้มเหลว {len(failed)} วัน → รอ 60 วินาทีแล้วลองใหม่ทีละวัน", flush=True)
        time.sleep(60)
        for day in failed:
            results[days.index(day)] = download_day_or_failed(day)
    still_failed = [day for day, result in zip(days, results) if result == "failed"]
    if still_failed:
        sample = ", ".join(f"{d:%Y-%m-%d}" for d in still_failed[:10])
        raise SystemExit(
            f"ยังโหลดไม่ได้ {len(still_failed)} วัน (เช่น {sample}) — ไฟล์ที่โหลดแล้วอยู่ใน cache "
            "รันคำสั่งเดิมซ้ำเพื่อโหลดต่อ ไม่สร้างไฟล์ M5/H1 จากข้อมูลที่ขาด"
        )

    frames = [decode_day(path, day) for path, day in zip(results, days) if path is not None]
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="first")]
    print(f"M1: {len(m1):,} แท่ง  {m1.index[0]} → {m1.index[-1]}", flush=True)

    spread = exness_hourly_spread_points()
    for rule, name in (("5min", "M5"), ("1h", "H1")):
        bars = resample(m1, rule)
        path = write_export(bars, name, spread)
        print(f"{name}: {len(bars):,} แท่ง → {path}", flush=True)


if __name__ == "__main__":
    main()
