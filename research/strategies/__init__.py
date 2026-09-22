from . import asian_breakout, fvg, pullback, smc_v0
from .asian_breakout import AsianBreakoutParams
from .fvg import FvgParams
from .pullback import PullbackParams
from .random_matched import random_matched_signals
from .smc_v0 import SIGNAL_COLUMNS, STRATEGY_NAME, TUNABLE_PARAMS, SmcV0Params, generate_signals


def _smc_hours(p: SmcV0Params) -> tuple[int, int]:
    return p.session_start_hour, p.session_end_hour


# ชื่อกลยุทธ์ → (ฟังก์ชันสร้าง signal, พารามิเตอร์, ช่วงชั่วโมงที่ออก signal สำหรับคู่เทียบสุ่ม)
# ชุดนี้ลงทะเบียนไว้ล่วงหน้า (DECISIONS 2026-09-17) — ห้ามเพิ่มโดยไม่บันทึกเหตุผล
REGISTRY = {
    "smc_v0.1": (smc_v0.generate_signals, SmcV0Params(), _smc_hours),
    "smc_v0.1_sl_sweep": (smc_v0.generate_signals, SmcV0Params(sl_anchor="sweep"), _smc_hours),
    "smc_v0.1_choch_only": (smc_v0.generate_signals, SmcV0Params(require_choch=True), _smc_hours),
    "smc_v0.1_min_depth": (smc_v0.generate_signals, SmcV0Params(min_sweep_depth_atr=0.1), _smc_hours),
    asian_breakout.STRATEGY_NAME: (
        asian_breakout.generate_signals,
        AsianBreakoutParams(),
        lambda p: p.signal_hours,
    ),
    # ชุดที่สอง — ผู้ใช้ขอ (DECISIONS 2026-09-18)
    pullback.STRATEGY_NAME: (
        pullback.generate_signals,
        PullbackParams(),
        lambda p: (p.session_start_hour, p.session_end_hour),
    ),
    # รอบที่ 3 — ผู้ใช้ขอ (DECISIONS 2026-09-19, STRATEGY-ROUND3.md)
    "pullback_v0_volfilter": (
        pullback.generate_signals,
        PullbackParams(vol_filter=True),
        lambda p: (p.session_start_hour, p.session_end_hour),
    ),
    fvg.STRATEGY_NAME: (
        fvg.generate_signals,
        FvgParams(),
        lambda p: (p.session_start_hour, p.session_end_hour),
    ),
}

__all__ = [
    "REGISTRY",
    "SIGNAL_COLUMNS",
    "STRATEGY_NAME",
    "TUNABLE_PARAMS",
    "AsianBreakoutParams",
    "PullbackParams",
    "SmcV0Params",
    "generate_signals",
    "random_matched_signals",
]
