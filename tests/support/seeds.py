"""样题的稳定 ID：测试里按 key 引用题目。"""

from __future__ import annotations

from tutor_api.services.content_seed import seed_uuid


def qid(key: str) -> str:
    return seed_uuid("question", key)


# 带地区测试标签的样题（ADR-006 Q-09：标签只用于测试筛选，不代表官方命题规则）
SICHUAN_TAGGED = {"math-mono-quadratic", "phys-force-analysis"}  # CN-51，考试年份 2027–2029
SICHUAN_LATER_YEARS = {"chem-charge-conservation"}  # CN-51，考试年份 2030–2031
CHONGQING_TAGGED = {"math-ineq-rect", "phys-tape-accel", "chem-lab-operation"}  # CN-50，2027–2029
# 可以由服务端确定性判定的样题（单选、多选、填空）
OBJECTIVE_KEYS = {
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
# 解答题：不自动评分，作答后对照要点自查（PRD P0 第 3、4 条）。都没有地区标签，是通用题
WRITTEN_KEYS = {
    "math-quadratic-param-written",
    "phys-pull-friction-written",
    "chem-ion-equation-written",
}
ALL_KEYS = OBJECTIVE_KEYS | WRITTEN_KEYS  # 所有已发布的样题
GENERAL_KEYS = ALL_KEYS - SICHUAN_TAGGED - SICHUAN_LATER_YEARS - CHONGQING_TAGGED
KEY_BY_ID = {qid(key): key for key in ALL_KEYS}

# seed/drafts/ 里的待审样题：入库为 draft，学生看不到，审核后台里才有（PRD P0 第 9 条）
DRAFT_KEYS = {"math-abs-decreasing", "phys-friction-uniform", "chem-electrolyte-identify"}
DRAFT_IDS = {qid(key) for key in DRAFT_KEYS}
