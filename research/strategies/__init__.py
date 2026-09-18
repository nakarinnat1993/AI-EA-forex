from . import asian_breakout, smc_v0
from .asian_breakout import AsianBreakoutParams
from .random_matched import random_matched_signals
from .smc_v0 import SIGNAL_COLUMNS, STRATEGY_NAME, TUNABLE_PARAMS, SmcV0Params, generate_signals

# ชื่อกลยุทธ์ → (ฟังก์ชันสร้าง signal, คลาสพารามิเตอร์, ช่วงชั่วโมงที่ออก signal สำหรับคู่เทียบสุ่ม)
REGISTRY = {
    smc_v0.STRATEGY_NAME: (
        smc_v0.generate_signals,
        SmcV0Params,
        lambda p: (p.session_start_hour, p.session_end_hour),
    ),
    asian_breakout.STRATEGY_NAME: (
        asian_breakout.generate_signals,
        AsianBreakoutParams,
        lambda p: p.signal_hours,
    ),
}

__all__ = [
    "REGISTRY",
    "SIGNAL_COLUMNS",
    "STRATEGY_NAME",
    "TUNABLE_PARAMS",
    "AsianBreakoutParams",
    "SmcV0Params",
    "generate_signals",
    "random_matched_signals",
]
