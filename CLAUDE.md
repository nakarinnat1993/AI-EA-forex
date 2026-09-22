# AI-EA-forex

สร้าง Expert Advisor (EA) สำหรับ XAUUSD บน MT5 โดยใช้ Claude เป็น research loop
คอยวิเคราะห์และปรับปรุงไปเรื่อย ๆ

## บริบทผู้ใช้

- นักพัฒนาซอฟต์แวร์ มีพื้นฐานโปรแกรมมิ่ง
- เทรด XAUUSD ด้วยมือบน MT5 อยู่แล้ว (บัญชี FBS-Real, hedge, USD)
- ขาดทุนสะสม -$2,029 จาก 3,460 ไม้ (ต.ค. 2025 – ก.ย. 2026) — ดู `journal/ANALYSIS-001-trade-history.md`
- เครื่องหลัก: macOS (MT5 รันผ่าน Wine) + มีเครื่อง Windows แยกสำหรับ live

## สถานะปัจจุบัน

**Phase 0 เสร็จแล้ว** — วิเคราะห์ประวัติเทรด 3,460 ไม้

ข้อสรุป: ผู้ใช้**ไม่เคยมีแผนการเทรดที่ชัดเจน** ทั้งหมดเป็นการเรียนรู้แบบ discretionary
และผู้ใช้ระบุเองว่าปัญหาหลักคือ **อารมณ์ล้วน ๆ** — แพ้แล้วเข้าแก้แค้น, ตกรถแล้วไล่ราคา
ซึ่งตรงกับข้อมูลที่วัดได้ (ไม้หลังขาดทุน: avg -$1.24 WR 34% | ไม้ไม่ตั้ง TP 776 ไม้ WR 22%)

→ ทิศทาง: **ออกแบบกลยุทธ์ใหม่บนฐาน SMC** แล้วให้ EA รันอัตโนมัติเพื่อตัดอารมณ์ออก

**Phase 1 (ฐานวิจัย) พร้อมใช้** — backtester, cost model จากข้อมูลจริง, ตัวกันกติกา overfitting,
ข้อมูล XAUUSDc (M5 17 เดือน, H1/H4 ถึง 2017), ปฏิทินข่าว, holdout ตั้งแล้วที่ 2026-05-01

**ทดสอบกลยุทธ์ครบแล้ว (2026-09-18): ไม่มีตัวไหนผ่าน** — 13 trial บนข้อมูล Dukascopy 2017 → 2026-04
(SMC กลับตัว 4 แบบ, Asian breakout, trend pullback เทรนด์ H1 และ M15)
ใกล้ที่สุด: pullback เทรนด์ M15 เข้า M5 (+0.20R ชนะการสุ่มทุกรอบ) แต่กำไร 94% มาจากปี 2025 และไม่มีไม้
4 ปี → ไม่ผ่านเกณฑ์ความสม่ำเสมอ (IT-009) / รอบ 3 (FVG, pullback+ตัวกรอง) ตกข้อเดียวกัน (IT-011, 012)
**holdout ถูกเปิดแล้ว 2026-09-19 (ผู้ใช้เลือก) ผล 0 ไม้ = ไม่ผ่าน** (IT-013) — ไม่มีข้อมูลทดสอบที่ยังไม่เคยเห็นเหลือ
การยืนยันกลยุทธ์ใหม่ต้องใช้ข้อมูลหลัง 2026-09-16 เท่านั้น
**ยังไม่มี EA ที่ควรรันด้วยเงินจริง** holdout ยังไม่ถูกเปิด ดู `journal/ITERATIONS.md` และ DECISIONS 2026-09-18

ข้อมูล Dukascopy: `.venv/bin/python -m research.data.dukascopy 2017-01-01 <วันที่>` (M5/M15/H1, cache ใน data/dukascopy/raw)
pandas 3: คอลัมน์ข้อความเก็บค่าว่างเป็น NaN — ใช้ `structure["is_break"]` ห้ามเช็ค `event is not None`

**ขั้นปัจจุบัน: forward test บน demo เริ่มแล้ว 2026-09-22** — `ea/experts/ForwardTestEA.mq5` รัน 3 ค่าตั้ง
(pullback M5/M15 magic 260921, pullback M1/M15 magic 260922, fvg M15/H1 magic 260923)
บน demo 416358379 @ Exness-MT5Trial14 แผนและเกณฑ์: `journal/FORWARD-TEST-PLAN.md` ทบทวน 2026-12-22
parity กับ Python ผ่านแล้ว (99.5–100%) ตัวเทียบ: `research/experiments/ea_parity.py`
**ระหว่างรัน: รายงานอย่างเดียว ห้ามแก้กฎหรือพารามิเตอร์**

รันการทดลอง: `.venv/bin/python -m research.experiments.compare_random --strategy smc_v0.1 --source dukascopy`
(กลยุทธ์ที่มี: `smc_v0.1`, `asian_breakout_v0` / แหล่งข้อมูล: `dukascopy` 2017 →, `exness` 17 เดือน)
เกณฑ์ผ่านขั้น dev ล็อกไว้ใน `journal/DECISIONS.md` 2026-09-17 — ตัวรันตัดสินให้อัตโนมัติ

## ข้อควรระวังที่สำคัญที่สุดของโปรเจกต์นี้

EA ตัดอารมณ์ออกจาก *การเข้าไม้* ได้ แต่ย้ายปัญหาไปที่ *การปล่อยให้ EA ทำงาน*
โหมดพังที่พบบ่อยที่สุด: ปิด EA หลังขาดทุน, เข้าไม้มือแทรก, แก้พารามิเตอร์ระหว่าง drawdown
→ ต้องมีบัญชีแยกสำหรับ EA, magic number, และช่วงประเมินที่ตกลงไว้ล่วงหน้า

## โครงสร้าง

```
config/
  costs_exness_xauusdc.json   สเปก + ต้นทุน (spread/slippage ยังเป็น placeholder)
  data_split.json             holdout_start — ตั้งครั้งเดียวเมื่อได้ข้อมูลชุดแรก
  news_filter.json            ช่วงห้ามเทรดรอบข่าว USD High (ค่าคงที่ ไม่ optimize)
data/raw/                     รายงานเทรดจาก MT5 (มีข้อมูลบัญชี — gitignored)
data/mt5/                     ไฟล์ที่ MQL5 scripts ส่งออก (gitignored)
ea/scripts/                   ExportBars.mq5, ExportSymbolSpec.mq5, ExportCalendar.mq5
ea/experts/                   SpreadLogger.mq5 (บันทึกสเปรด ไม่เทรด)
research/backtest/            engine, costs, sizing, metrics, report, causality, news
research/smc/                 ตัวตรวจจับ SMC: swing, BOS/CHoCH, liquidity, sweep, order block
research/data/                loader (ล็อก holdout), calendar, sync_mt5
research/*.py                 สคริปต์วิเคราะห์ประวัติเทรด Phase 0 (stdlib ล้วน)
reports/                      ผล backtest + runs.jsonl (นับ trial — ห้ามลบบรรทัด)
journal/                      DECISIONS, ANALYSIS-*, ITERATIONS, HOLDOUT_LOG
reference/                    สเปกโบรก
tests/                        pytest
```

## คำสั่ง

```bash
.venv/bin/python -m pytest              # รัน tests
.venv/bin/python -m research.data.sync_mt5   # ดึงไฟล์ที่ MT5 export มาไว้ data/mt5/
```

## ข้อตกลงของ backtest engine (อย่าแก้โดยไม่บันทึกใน DECISIONS)

- OHLC = ราคา bid, ask = bid + spread / Long ออกที่ bid, Short ออกที่ ask
- signal แท่ง i → เข้าที่ open แท่ง i+1
- แท่งเดียวชนทั้ง SL และ TP → นับเป็น SL (ติดธง ambiguous; ถ้าเกิน 5% ต้องเช็คด้วย M1)
- เปิดแท่งทะลุ SL → ออกที่ open + stop slippage
- ขนาดไม้ปัดลงเสมอ ต่ำกว่า min lot = ข้ามไม้ (ห้ามบังคับ min lot)
- ทุกกลยุทธ์ต้องผ่าน `assert_causal` ก่อน backtest
- news blackout (`config/news_filter.json`): ในช่วงข่าวห้ามเปิดไม้ และไม้ที่ถืออยู่ปิดที่ราคาเปิดของแท่งแรกในช่วง
- limit order: Buy limit ถูกจับคู่เมื่อ **ask** ถึงราคาที่ตั้ง (low + spread ≤ entry) ตามที่ MT5 ทำจริง
  ได้ราคาที่ตั้งไว้เสมอแม้แท่งจะ gap ข้ามไป / ยกเลิกเมื่อหมดอายุ, ราคาไปถึง TP ก่อน (ตกรถ),
  ปิดเลย cancel_price หรือเข้าช่วงข่าว
- ความเสี่ยง: `config/risk.json` (1%/ไม้, daily loss limit 3% — ผู้ใช้ยืนยันแล้ว ไม่ optimize)

## MQL5 บน Mac

ไฟล์ .mq5 ต้นฉบับอยู่ใน `ea/` และคัดลอกไปไว้ที่ `MQL5/Scripts/AI-EA/` กับ `MQL5/Experts/AI-EA/`
ใน Wine prefix — การคอมไพล์ผ่าน command line ด้วย Wine ที่มากับแอปยังใช้ไม่ได้
ให้คอมไพล์ใน MetaEditor (F7) แทน

## สถาปัตยกรรมที่ตกลงกันแล้ว

วิจัยด้วย Python บน Mac (วนเร็ว อ่าน report ได้ตรง) → พิสูจน์ผ่านแล้วค่อย port เป็น
**MQL5 EA ตัวเดียวจบ** รันบน MT5 บนเครื่อง Windows

ห้ามใช้ Python bridge ตอน live — ถ้า bridge หลุด ออเดอร์จะค้าง

## กติกากัน overfitting (สำคัญที่สุด — ห้ามข้าม)

การวนลูป "backtest → ให้ AI ปรับ → backtest ใหม่" คือเครื่องจักรผลิต overfitting
กติกาที่ต้องรักษา:

1. **Holdout ปิดผนึก** — แบ่งข้อมูลตั้งแต่วันแรก ช่วงที่กันไว้ห้ามรันจนกว่าจะประกาศเวอร์ชันสุดท้าย
   เปิดได้ครั้งเดียว ถ้าไม่ผ่านคือกลับไปคิดใหม่ ไม่ใช่ปรับให้ผ่าน
2. **Walk-forward เป็นตัวตัดสิน** ไม่ใช่ backtest ก้อนเดียว
3. **บันทึกทุก iteration** ลง `journal/ITERATIONS.md` — ยิ่งวนเยอะยิ่งต้องหักส่วนลดผลลัพธ์
4. **แก้ต้องมีเหตุผลเชิงกลไกตลาด** ไม่รับ "ลองแล้วเลข 14 ดีกว่าเลข 12"
5. **พารามิเตอร์ปรับได้ < 10 ตัว**

## บัญชีที่ใช้

| | บัญชีเทรดมือ | **บัญชี EA** |
|---|---|---|
| โบรก | FBS-Real 28642802 | **Exness-MT5Real25** (login 184143514) |
| Symbol | XAUUSD | **XAUUSDc** (บัญชีเซนต์) |
| Contract size | 100 oz | **1 oz** |
| **Server TZ** | **GMT+3** | **GMT+0 (UTC)** |
| ทุน | — | **$50** |

⚠️ **สอง timezone ไม่เท่ากัน** — การวิเคราะห์รายชั่วโมงจากประวัติ FBS ใช้กับบัญชี Exness ไม่ได้
สเปกเต็ม: `reference/XAUUSDc-exness-spec.md`

แพลตฟอร์ม: **MT5 ทั้งคู่** แยกด้วยบัญชี ไม่ใช่แพลตฟอร์ม (ตัดสินใจไม่ใช้ MT4 — ดู DECISIONS.md)

ขนาดไม้ที่ทุน $50 เสี่ยง 1%: SL $6→0.08 / $8→0.06 / $10→0.05 / $12→0.04 lot

## ข้อมูลที่ยังขาด

- [ ] **ความลึกของ M5** — ได้ 17 เดือน (2025-04 →) ชนเพดาน 100,000 แท่ง ทั้งที่ H1/H4 ถึงปี 2017
      → ต้องลองดึงเพิ่มหรือปรับแผน ดู `journal/DATA-STATUS.md`
- [x] สเปรดจริง: p50 $0.160, p99 $0.360 — คอลัมน์ spread ในไฟล์แท่งตรงกับที่วัดสด ใช้ได้เลย
- [x] server timezone: **UTC คงที่ทั้งปี ไม่ขยับตาม DST** (ยืนยัน 2026-09-16 จาก 140 ข่าว NFP)
- [ ] ผู้ใช้ตรวจ setup ที่โค้ดเจอด้วยตาบน TradingView (ไฟล์ `reports/*_setups.csv` มีเวลาไทย)
- [x] ความเสี่ยง 1%/ไม้ และ daily loss limit 3% — ผู้ใช้ยืนยันแล้ว

## หมายเหตุสภาพแวดล้อม

- Python 3.13.5 + `.venv` (numpy 2.5.3, pandas 3.0.5, pytest 9.1.1 — ดู requirements.txt)
- MT5 บน Mac เซฟไฟล์ลง Wine prefix ไม่ใช่ Desktop จริง:
  `~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/Desktop/`
