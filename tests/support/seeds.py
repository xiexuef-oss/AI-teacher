"""样题的稳定 ID：测试里按 key 引用题目。"""

from __future__ import annotations

from tutor_api.services.content_seed import seed_uuid


def qid(key: str) -> str:
    return seed_uuid("question", key)


# 带地区测试标签的样题（ADR-006 Q-09：标签只用于测试筛选，不代表官方命题规则）
SICHUAN_TAGGED = {"math-mono-quadratic", "phys-force-analysis"}  # CN-51，考试年份 2027–2029
SICHUAN_LATER_YEARS = {"chem-charge-conservation"}  # CN-51，考试年份 2030–2031
CHONGQING_TAGGED = {"math-ineq-rect", "phys-tape-accel", "chem-lab-operation"}  # CN-50，2027–2029
ALL_KEYS = {
    "math-mono-quadratic",
    "math-mono-quadratic-v1",
    "math-mono-judge",
    "math-ineq-min",
    "math-ineq-rect",
    "math-ineq-product-v1",
    "phys-incline-accel",
    "phys-incline-accel-v1",
    "phys-newton2-force",
    "phys-force-analysis",
    "phys-vt-displacement",
    "phys-tape-accel",
    "chem-conservation-co2",
    "chem-conservation-h2",
    "chem-charge-conservation",
    "chem-ion-inference",
    "chem-lab-operation",
}
GENERAL_KEYS = ALL_KEYS - SICHUAN_TAGGED - SICHUAN_LATER_YEARS - CHONGQING_TAGGED
KEY_BY_ID = {qid(key): key for key in ALL_KEYS}
