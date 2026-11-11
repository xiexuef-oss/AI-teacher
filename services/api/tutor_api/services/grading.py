"""客观题的确定性判定（单选、多选、填空）。

三种结论：
- verified：规则能确定对错；
- uncertain：格式认不出、单位认不出、或确认不了等价——不算对也不算错，标记待复核；
- pending：主观题，本阶段不评分。

这里给出的是练习反馈，不是官方阅卷分数。多选题的判定方式来自每道题自己的 rubric，
不写死任何地区的评分办法。
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from tutor_api.services import mathparse

MULTI_CHOICE_RULES = ("all_or_nothing", "partial_no_wrong")
RULE_TYPES = ("numeric", "expression", "interval")

_SAMPLES = 6
_MIN_VALID_SAMPLES = 4
_LEADING_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:/(?:\d+\.?\d*|\.\d+))?")
_POSITIVE_INFINITY = {"+∞", "∞", "+inf", "inf", "+oo", "oo", "正无穷", "正无穷大", "+正无穷"}
_NEGATIVE_INFINITY = {"-∞", "-inf", "-oo", "负无穷", "负无穷大"}


class AnswerShapeError(ValueError):
    """提交的答案与题目的作答方式不匹配（API 层转成 422）。"""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class Feedback:
    target: str
    code: str
    message: str


@dataclass(frozen=True)
class GradeResult:
    state: Literal["verified", "uncertain", "pending"]
    outcome: Literal["correct", "partially_correct", "incorrect", "undetermined"]
    is_correct: bool | None
    feedback: tuple[Feedback, ...]
    message: str
    review_required: bool = False
    uncertainty_reason: str | None = None


@dataclass(frozen=True)
class _BlankResult:
    status: Literal["correct", "incorrect", "uncertain"]
    code: str
    message: str


_CORRECT = _BlankResult("correct", "correct", "回答正确。")


def fold(text: str) -> str:
    """比较用的规范形式：上标改写、全半角统一、去空白、小写。"""
    normalized = unicodedata.normalize("NFKC", mathparse.expand_superscripts(text))
    return "".join(normalized.split()).lower().replace("−", "-").replace("–", "-").replace("—", "-")


# ---------------------------------------------------------------- 选择题


def _grade_choice(
    mode: str,
    content: dict[str, Any],
    answer_key: dict[str, Any],
    rubric: dict[str, Any],
    teaching: dict[str, Any],
    answer: dict[str, Any],
) -> GradeResult:
    option_keys = [option["key"] for option in content.get("options", [])]
    selected = answer.get("selected_options")
    if answer.get("blanks") is not None or answer.get("text") is not None:
        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")
    if not selected:
        raise AnswerShapeError("answer.selected_options", "请至少选择一个选项")
    if mode == "single_choice" and len(selected) != 1:
        raise AnswerShapeError("answer.selected_options", "单选题只能选择一个选项")
    unknown = [key for key in selected if key not in option_keys]
    if unknown:
        raise AnswerShapeError("answer.selected_options", "包含题目中不存在的选项")

    correct = set(answer_key["value"])
    chosen = set(selected)
    analysis = teaching.get("option_analysis") or {}
    rule = rubric.get("multi_choice_rule") or "all_or_nothing"
    if mode == "multiple_choice" and rule not in MULTI_CHOICE_RULES:
        raise ValueError(f"未知的 multi_choice_rule：{rule!r}")

    if chosen == correct:
        return GradeResult(
            "verified",
            "correct",
            True,
            (Feedback("overall", "correct", "回答正确。"),),
            "回答正确。",
        )

    wrong = [key for key in option_keys if key in chosen and key not in correct]
    feedback = [
        Feedback(key, "wrong_option", analysis.get(key) or "这个选项不成立。") for key in wrong
    ]
    if correct - chosen and mode == "multiple_choice":
        # 只说"有漏选"，不指出漏掉的是哪一项、有几项
        feedback.append(Feedback("overall", "missed_options", "还有正确选项没有选上。"))

    if mode == "multiple_choice" and not wrong and rule == "partial_no_wrong":
        return GradeResult(
            "verified",
            "partially_correct",
            False,
            tuple(feedback),
            "选对了一部分，还有正确选项没有选上。",
        )
    return GradeResult(
        "verified", "incorrect", False, tuple(feedback), "这次没有答对，看看下面的分析。"
    )


# ---------------------------------------------------------------- 填空：数值与单位


def _numbers_equal(actual: float, expected: float, rule: dict[str, Any]) -> bool:
    abs_tol = float(rule.get("abs_tol", 1e-9))
    rel_tol = float(rule.get("rel_tol", 0.0))
    return abs(actual - expected) <= max(abs_tol, rel_tol * abs(expected))


def _try_number(text: str) -> float | None:
    try:
        return mathparse.evaluate_number(text)
    except (mathparse.ParseError, mathparse.EvalError):
        return None


def _split_number_and_unit(folded: str, accepted: list[str]) -> tuple[float | None, str]:
    """返回 (数值, 单位状态)。单位状态：ok（认得的单位）、none（没写）、unknown（写了但认不出）。"""
    for alias in sorted({fold(a) for a in accepted}, key=len, reverse=True):
        if alias and folded.endswith(alias) and len(folded) > len(alias):
            value = _try_number(folded[: -len(alias)])
            if value is not None:
                return value, "ok"
    value = _try_number(folded)
    if value is not None:
        return value, "none"
    match = _LEADING_NUMBER.match(folded)
    if match and match.end() < len(folded):
        value = _try_number(match.group())
        if value is not None:
            return value, "unknown"
    return None, "unknown"


def _check_numeric(
    rule: dict[str, Any], expected: str, units: dict[str, Any] | None, raw: str
) -> _BlankResult:
    expected_value = mathparse.evaluate_number(expected)
    value, unit_status = _split_number_and_unit(fold(raw), list((units or {}).get("accepted", [])))

    if value is None:
        return _BlankResult("uncertain", "format_unrecognized", "没能识别这个答案的格式。")
    if unit_status == "unknown":
        if units:
            # 换了单位的答案可能是对的，规则认不出时不能判错
            return _BlankResult(
                "uncertain", "equivalence_unconfirmed", "没能识别答案里的单位，无法确认是否等价。"
            )
        return _BlankResult("uncertain", "format_unrecognized", "没能识别这个答案的格式。")
    if not _numbers_equal(value, expected_value, rule):
        return _BlankResult("incorrect", "value_incorrect", "数值不正确。")
    if unit_status == "none" and (units or {}).get("required"):
        return _BlankResult("incorrect", "unit_missing", "数值正确，但缺少单位。")
    return _CORRECT


# ---------------------------------------------------------------- 填空：表达式等价


def _sample_env(variables: list[str], k: int) -> dict[str, float]:
    """确定性的取样点，落在 (0.37, 2.27)，避开 0、1 和常见特殊角。"""
    return {
        name: 0.37 + ((index * 0.6180339887 + k * 0.4142135623 + 0.1) % 1.0) * 1.9
        for index, name in enumerate(sorted(variables))
    }


def _check_expression(rule: dict[str, Any], expected: str, raw: str) -> _BlankResult:
    variables = list(rule.get("variables", []))
    expected_tree = mathparse.parse(expected, variables)
    try:
        actual_tree = mathparse.parse(raw, variables)
    except mathparse.ParseError:
        return _BlankResult("uncertain", "format_unrecognized", "没能识别这个表达式。")

    valid = 0
    for k in range(_SAMPLES):
        env = _sample_env(variables, k)
        try:
            expected_value = mathparse.evaluate(expected_tree, env)
            actual_value = mathparse.evaluate(actual_tree, env)
        except mathparse.EvalError:
            continue
        valid += 1
        scale = max(1.0, abs(expected_value), abs(actual_value))
        if abs(expected_value - actual_value) > 1e-9 * scale:
            return _BlankResult("incorrect", "value_incorrect", "与标准答案不等价。")
    if valid < _MIN_VALID_SAMPLES:
        return _BlankResult(
            "uncertain", "equivalence_unconfirmed", "暂时无法确认这个表达式是否等价。"
        )
    return _CORRECT


# ---------------------------------------------------------------- 填空：区间


@dataclass(frozen=True)
class _Interval:
    low: float
    high: float
    low_closed: bool
    high_closed: bool


def _endpoint(text: str) -> float | None:
    if text in _POSITIVE_INFINITY:
        return math.inf
    if text in _NEGATIVE_INFINITY:
        return -math.inf
    return _try_number(text)


def parse_interval(raw: str) -> _Interval | None:
    text = fold(raw)
    if len(text) < 5 or text[0] not in "([" or text[-1] not in ")]":
        return None
    parts = text[1:-1].split(",")
    if len(parts) != 2:
        return None
    low, high = _endpoint(parts[0]), _endpoint(parts[1])
    if low is None or high is None:
        return None
    return _Interval(low, high, text[0] == "[", text[-1] == "]")


def _same_endpoint(a: float, b: float) -> bool:
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _check_interval(rule: dict[str, Any], expected: str, raw: str) -> _BlankResult:
    target = parse_interval(expected)
    if target is None:
        raise ValueError(f"标准答案不是合法的区间：{expected!r}")
    actual = parse_interval(raw)
    if actual is None:
        return _BlankResult(
            "uncertain", "format_unrecognized", "没能识别这个区间的写法，请用区间表示。"
        )

    wrong = _BlankResult("incorrect", "value_incorrect", "区间不正确。")
    if not (_same_endpoint(actual.low, target.low) and _same_endpoint(actual.high, target.high)):
        return wrong
    if (math.isinf(actual.low) and actual.low_closed) or (
        math.isinf(actual.high) and actual.high_closed
    ):
        return _BlankResult("incorrect", "value_incorrect", "无穷的一端应当用圆括号。")
    if not rule.get("closure_flexible", False):
        low_mismatch = not math.isinf(target.low) and actual.low_closed != target.low_closed
        high_mismatch = not math.isinf(target.high) and actual.high_closed != target.high_closed
        if low_mismatch or high_mismatch:
            return _BlankResult("incorrect", "value_incorrect", "区间端点的开闭不正确。")
    return _CORRECT


# ---------------------------------------------------------------- 填空：汇总


def check_blank(
    rule: dict[str, Any], expected: str, units: dict[str, Any] | None, raw: str
) -> _BlankResult:
    kind = rule.get("type")
    if kind == "numeric":
        return _check_numeric(rule, expected, units, raw)
    if kind == "expression":
        return _check_expression(rule, expected, raw)
    if kind == "interval":
        return _check_interval(rule, expected, raw)
    raise ValueError(f"未知的等价规则类型：{kind!r}")


def _grade_fill(
    content: dict[str, Any], answer_key: dict[str, Any], answer: dict[str, Any]
) -> GradeResult:
    blank_keys = [blank["key"] for blank in content.get("blanks", [])]
    submitted = answer.get("blanks")
    if answer.get("selected_options") is not None or answer.get("text") is not None:
        raise AnswerShapeError("answer", "填空题只需要提交 blanks")
    if not submitted:
        raise AnswerShapeError("answer.blanks", "请填写答案")
    values = {item["key"]: item["value"] for item in submitted}
    if len(values) != len(submitted) or set(values) != set(blank_keys):
        raise AnswerShapeError("answer.blanks", "每个空都需要填写一次，且不能有题目之外的空")
    if any(not value.strip() for value in values.values()):
        raise AnswerShapeError("answer.blanks", "答案不能为空")

    expected = answer_key["value"]
    rules = answer_key.get("equivalence_rules") or {}
    units = answer_key.get("units") or {}
    results = {
        key: check_blank(rules[key], expected[key], units.get(key), values[key])
        for key in blank_keys
    }

    statuses = [result.status for result in results.values()]
    problems = tuple(
        Feedback(key, result.code, result.message)
        for key, result in results.items()
        if result.status != "correct"
    )
    if all(status == "correct" for status in statuses):
        return GradeResult(
            "verified",
            "correct",
            True,
            (Feedback("overall", "correct", "回答正确。"),),
            "回答正确。",
        )
    if "incorrect" in statuses:
        outcome = "partially_correct" if "correct" in statuses else "incorrect"
        wrong_only = tuple(item for item in problems if results[item.target].status == "incorrect")
        return GradeResult(
            "verified", outcome, False, wrong_only, "这次没有全部答对，看看下面的分析。"
        )

    first = next(result for result in results.values() if result.status == "uncertain")
    reason = (
        "answer_unrecognized" if first.code == "format_unrecognized" else "equivalence_unconfirmed"
    )
    return GradeResult(
        "uncertain",
        "undetermined",
        None,
        problems,
        "这个答案暂时无法自动判定，已标记为待确认，不计入正确率。",
        review_required=True,
        uncertainty_reason=reason,
    )


def grade(
    *,
    answer_mode: str,
    content: dict[str, Any],
    answer_key: dict[str, Any],
    rubric: dict[str, Any],
    teaching: dict[str, Any],
    answer: dict[str, Any],
) -> GradeResult:
    if answer_mode in {"single_choice", "multiple_choice"}:
        return _grade_choice(answer_mode, content, answer_key, rubric, teaching, answer)
    if answer_mode == "fill":
        return _grade_fill(content, answer_key, answer)
    # 主观题与实验题：本阶段只保存作答，不给任何判定
    return GradeResult(
        "pending",
        "undetermined",
        None,
        (),
        "这类题目的评分还没有开放，作答已保存。",
        review_required=True,
    )
