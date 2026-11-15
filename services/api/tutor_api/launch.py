"""首发范围的固定选项（DECISIONS_PENDING 的 D-01、D-04 已冻结）。

地区只能由用户手动选择，这里没有、也不应该有任何从定位或 IP 推断地区的逻辑。
"""

from __future__ import annotations

# D-01：首发地区
REGIONS: list[tuple[str, str]] = [("CN-51", "四川"), ("CN-50", "重庆")]
REGION_NAMES: dict[str, str] = dict(REGIONS)

# (代码, 名称, 年级数)
GRADES: list[tuple[str, str, int]] = [("G10", "高一", 10), ("G11", "高二", 11), ("G12", "高三", 12)]
GRADE_NUMBERS: dict[str, int] = {code: number for code, _, number in GRADES}

# D-04：首发学科
SUBJECTS: list[tuple[str, str]] = [("math", "数学"), ("physics", "物理"), ("chemistry", "化学")]
SUBJECT_NAMES: dict[str, str] = dict(SUBJECTS)
SUBJECT_ORDER: dict[str, int] = {code: index for index, (code, _) in enumerate(SUBJECTS)}

# Q-08 未冻结：教材选项是供学生手动选择的占位清单，与省份没有任何对应关系，
# 也还没有用于题目推荐。不清楚时资料里保持为空。
CURRICULUM_OPTIONS: list[tuple[str, str]] = [
    ("PEP", "人教版"),
    ("BNUP", "北师大版"),
    ("JSEP", "苏教版"),
    ("SDSTP", "鲁科版"),
    ("ESPH", "教科版"),
    ("OTHER", "其他版本"),
]
CURRICULUM_CODES: frozenset[str] = frozenset(code for code, _ in CURRICULUM_OPTIONS)

# 学年以 9 月为起点（ADR-006 Q-08）
SCHOOL_YEAR_START_MONTH = 9
# 可手动设置的考试年份范围：今年起往后 4 年
EXAM_YEAR_WINDOW = 4

ANSWER_MODE_NAMES: dict[str, str] = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "fill": "填空题",
    "written": "解答题",
    "experiment": "实验题",
}
