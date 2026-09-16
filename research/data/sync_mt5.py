"""คัดลอกไฟล์ที่ MQL5 scripts ส่งออก จาก Wine prefix มาไว้ใน data/mt5/

    .venv/bin/python -m research.data.sync_mt5
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MT5_FILES = (
    Path.home()
    / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files/AI-EA"
)
DEST = REPO_ROOT / "data" / "mt5"


def main() -> None:
    if not MT5_FILES.exists():
        raise SystemExit(f"not found: {MT5_FILES}\nrun ExportBars / ExportSymbolSpec in MT5 first")
    DEST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(MT5_FILES.iterdir()):
        dst = DEST / src.name
        if src.is_file() and (not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime):
            shutil.copy2(src, dst)
            print(f"copied {src.name} ({src.stat().st_size / 1e6:.1f} MB)")
            copied += 1
    print(f"{copied} file(s) updated in {DEST}")


if __name__ == "__main__":
    main()
