"""客观题判定（docs/01 §5、docs/06 §3）。

原则：规则能确定的才给确定结论；认不出格式、认不出单位、确认不了等价的，一律 uncertain，
不算对也不算错。
"""

from __future__ import annotations

import pytest

from tutor_api.services.grading import AnswerShapeError, grade

OPTIONS = [{"key": k, "text": f"选项 {k}"} for k in "ABCD"]
ANALYSIS = {
    "A": "A 的错因说明。",
    "B": "B 为什么成立。",
    "C": "C 为什么成立。",
    "D": "D 的错因说明。",
}


def choice(
    mode: str, correct: list[str], selected: list[str] | None, rule: str | None = None, **extra
):
    answer = {} if selected is None else {"selected_options": selected}
    answer.update(extra)
    return grade(
        answer_mode=mode,
        content={"stem": "题干", "options": OPTIONS},
        answer_key={"value": correct},
        rubric={"multi_choice_rule": rule} if rule else {},
        teaching={"option_analysis": ANALYSIS},
        answer=answer,
    )


def fill(raw: str | dict[str, str], rule: dict, expected: str = "4", units: dict | None = None):
    blanks = raw if isinstance(raw, dict) else {"b1": raw}
    keys = list(blanks)
    expected_map = {key: expected for key in keys} if isinstance(expected, str) else expected
    return grade(
        answer_mode="fill",
        content={"stem": "题干", "blanks": [{"key": key} for key in keys]},
        answer_key={
            "value": expected_map,
            "equivalence_rules": {key: rule for key in keys},
            "units": {key: units for key in keys},
        },
        rubric={},
        teaching={},
        answer={"blanks": [{"key": key, "value": value} for key, value in blanks.items()]},
    )


def codes(result) -> list[tuple[str, str]]:
    return [(item.target, item.code) for item in result.feedback]


# ---------------------------------------------------------------- 单选


def test_single_choice_correct():
    result = choice("single_choice", ["B"], ["B"])

    assert (result.state, result.outcome, result.is_correct) == ("verified", "correct", True)
    assert result.review_required is False
    assert codes(result) == [("overall", "correct")]


def test_single_choice_wrong_explains_the_chosen_option_only():
    result = choice("single_choice", ["B"], ["A"])

    assert (result.state, result.outcome, result.is_correct) == ("verified", "incorrect", False)
    assert codes(result) == [("A", "wrong_option")]
    assert result.feedback[0].message == ANALYSIS["A"]
    assert ANALYSIS["B"] not in str(result), "不能顺带把正确选项的解析带出来"


@pytest.mark.parametrize(
    ("selected", "extra"),
    [
        ([], {}),
        (["A", "B"], {}),
        (["Z"], {}),
        (None, {}),
        (["A"], {"blanks": [{"key": "b1", "value": "1"}]}),
        (["A"], {"text": "我觉得选 A"}),
    ],
    ids=["empty", "two-options", "unknown-key", "missing", "extra-blanks", "extra-text"],
)
def test_single_choice_rejects_answers_of_the_wrong_shape(selected, extra):
    with pytest.raises(AnswerShapeError):
        choice("single_choice", ["B"], selected, **extra)


# ---------------------------------------------------------------- 多选：判定规则可配


def test_multiple_choice_exact_match_is_correct():
    result = choice("multiple_choice", ["B", "C"], ["C", "B"])
    assert (result.outcome, result.is_correct) == ("correct", True)


def test_subset_is_partially_correct_under_partial_rule():
    result = choice("multiple_choice", ["B", "C"], ["B"], rule="partial_no_wrong")

    assert (result.state, result.outcome, result.is_correct) == (
        "verified",
        "partially_correct",
        False,
    )
    assert codes(result) == [("overall", "missed_options")]
    assert "C" not in result.feedback[0].message, "不能指出漏掉的是哪一项"


def test_subset_is_incorrect_under_all_or_nothing_rule():
    result = choice("multiple_choice", ["B", "C"], ["B"], rule="all_or_nothing")

    assert (result.outcome, result.is_correct) == ("incorrect", False)
    assert codes(result) == [("overall", "missed_options")]


def test_default_multiple_choice_rule_is_all_or_nothing():
    assert choice("multiple_choice", ["B", "C"], ["B"]).outcome == "incorrect"


@pytest.mark.parametrize("rule", ["partial_no_wrong", "all_or_nothing"])
def test_any_wrong_option_makes_the_answer_incorrect(rule):
    result = choice("multiple_choice", ["B", "C"], ["A", "B"], rule=rule)

    assert (result.outcome, result.is_correct) == ("incorrect", False)
    assert codes(result) == [("A", "wrong_option"), ("overall", "missed_options")]


def test_all_correct_plus_one_wrong_reports_only_the_wrong_option():
    result = choice("multiple_choice", ["B", "C"], ["B", "C", "D"], rule="partial_no_wrong")

    assert result.outcome == "incorrect"
    assert codes(result) == [("D", "wrong_option")]


def test_multiple_choice_rejects_empty_and_unknown_options():
    for selected in ([], ["B", "X"]):
        with pytest.raises(AnswerShapeError):
            choice("multiple_choice", ["B", "C"], selected)


def test_unknown_rubric_rule_is_a_configuration_error():
    with pytest.raises(ValueError, match="multi_choice_rule"):
        choice("multiple_choice", ["B", "C"], ["B"], rule="half_points")


# ---------------------------------------------------------------- 填空：数值

NUMERIC = {"type": "numeric"}


@pytest.mark.parametrize("raw", ["4", " 4 ", "４", "4.0", "+4", "8/2", "2^2", "2²", "√16"])
def test_numeric_accepts_equal_values_in_any_notation(raw):
    result = fill(raw, NUMERIC)
    assert (result.state, result.outcome, result.is_correct) == ("verified", "correct", True)


def test_numeric_wrong_value_is_incorrect():
    result = fill("5", NUMERIC)

    assert (result.state, result.outcome, result.is_correct) == ("verified", "incorrect", False)
    assert codes(result) == [("b1", "value_incorrect")]


@pytest.mark.parametrize("raw", ["四", "abc", "4 左右", "≈4", "x=4", "4 或 5"])
def test_unrecognised_format_is_uncertain_not_wrong(raw):
    result = fill(raw, NUMERIC)

    assert (result.state, result.outcome, result.is_correct) == ("uncertain", "undetermined", None)
    assert result.review_required is True
    assert result.uncertainty_reason == "answer_unrecognized"
    assert codes(result) == [("b1", "format_unrecognized")]


def test_empty_blank_is_a_shape_error():
    for raw in ("", "   "):
        with pytest.raises(AnswerShapeError):
            fill(raw, NUMERIC)


def test_missing_or_unknown_blank_keys_are_shape_errors():
    with pytest.raises(AnswerShapeError):
        grade(
            answer_mode="fill",
            content={"stem": "题干", "blanks": [{"key": "b1"}, {"key": "b2"}]},
            answer_key={
                "value": {"b1": "1", "b2": "2"},
                "equivalence_rules": {"b1": NUMERIC, "b2": NUMERIC},
            },
            rubric={},
            teaching={},
            answer={"blanks": [{"key": "b1", "value": "1"}, {"key": "zz", "value": "2"}]},
        )


def test_numeric_tolerance_is_configurable():
    rule = {"type": "numeric", "rel_tol": 0.005}
    assert fill("4.4", rule, expected="4.4").outcome == "correct"
    assert fill("4.40", rule, expected="4.4").outcome == "correct"
    assert fill("4.41", rule, expected="4.4").outcome == "correct"
    assert fill("4.5", rule, expected="4.4").outcome == "incorrect"
    assert fill("4.41", NUMERIC, expected="4.4").outcome == "incorrect", "默认要求数值相等"


# ---------------------------------------------------------------- 填空：单位

OPTIONAL_G = {"required": False, "accepted": ["g", "克"]}
REQUIRED_ACCEL = {"required": True, "accepted": ["m/s²", "m/s^2", "m/s2", "米每二次方秒"]}


@pytest.mark.parametrize("raw", ["4.4", "4.4g", "4.4 g", "4.4克", "4.4 G"])
def test_optional_unit_may_be_written_or_omitted(raw):
    assert fill(raw, NUMERIC, expected="4.4", units=OPTIONAL_G).outcome == "correct"


@pytest.mark.parametrize(
    "raw", ["5 m/s²", "5m/s^2", "5 m/s2", "5米每二次方秒", "5.0 M/S²", "10/2 m/s²"]
)
def test_required_unit_in_any_accepted_spelling(raw):
    assert fill(raw, NUMERIC, expected="5", units=REQUIRED_ACCEL).outcome == "correct"


def test_missing_required_unit_is_incorrect_with_a_specific_reason():
    result = fill("5", NUMERIC, expected="5", units=REQUIRED_ACCEL)

    assert (result.state, result.outcome, result.is_correct) == ("verified", "incorrect", False)
    assert codes(result) == [("b1", "unit_missing")]
    assert "单位" in result.feedback[0].message


def test_wrong_value_with_correct_unit_is_incorrect():
    result = fill("6 m/s²", NUMERIC, expected="5", units=REQUIRED_ACCEL)
    assert codes(result) == [("b1", "value_incorrect")]


@pytest.mark.parametrize("raw", ["5 N", "500 cm/s²", "5 m/s", "0.005 km/s²"])
def test_unrecognised_unit_is_uncertain_never_judged_wrong(raw):
    """换了单位的答案可能是对的（500 cm/s² 就等于 5 m/s²），规则认不出时不能判错。"""
    result = fill(raw, NUMERIC, expected="5", units=REQUIRED_ACCEL)

    assert (result.state, result.is_correct) == ("uncertain", None)
    assert result.uncertainty_reason == "equivalence_unconfirmed"
    assert codes(result) == [("b1", "equivalence_unconfirmed")]


def test_trailing_text_without_any_unit_rule_is_uncertain():
    assert fill("4 cm", NUMERIC).state == "uncertain"


# ---------------------------------------------------------------- 填空：表达式等价

EXPRESSION = {"type": "expression", "variables": ["g", "theta", "m"]}


@pytest.mark.parametrize(
    "raw",
    [
        "g sinθ",
        "gsinθ",
        "sinθ·g",
        "g*sin(theta)",
        "g×sin θ",
        "mg sinθ/m",
        "gsinθ+0",
        "(g sinθ)",
        "g·sin(θ)",
    ],
)
def test_equivalent_expressions_are_correct(raw):
    result = fill(raw, EXPRESSION, expected="g*sin(theta)")
    assert (result.state, result.outcome, result.is_correct) == ("verified", "correct", True)


@pytest.mark.parametrize(
    "raw", ["g cosθ", "g", "sinθ", "9.8 sinθ", "g sin2θ", "mg sinθ", "g tanθ", "-g sinθ"]
)
def test_non_equivalent_expressions_are_incorrect(raw):
    result = fill(raw, EXPRESSION, expected="g*sin(theta)")

    assert (result.state, result.outcome, result.is_correct) == ("verified", "incorrect", False)
    assert codes(result) == [("b1", "value_incorrect")]


@pytest.mark.parametrize("raw", ["g sinα", "g·sin", "加速度是 g sinθ", "g sinθ m/s²"])
def test_unparseable_expressions_are_uncertain(raw):
    result = fill(raw, EXPRESSION, expected="g*sin(theta)")
    assert (result.state, result.is_correct) == ("uncertain", None)


def test_polynomial_equivalence():
    rule = {"type": "expression", "variables": ["x"]}
    assert fill("2(x+1)", rule, expected="2*x+2").outcome == "correct"
    assert fill("(x+1)(x-1)", rule, expected="x^2-1").outcome == "correct"
    assert fill("x²-1", rule, expected="x^2-1").outcome == "correct"
    assert fill("x^2+1", rule, expected="x^2-1").outcome == "incorrect"


# ---------------------------------------------------------------- 填空：区间

FLEXIBLE = {"type": "interval", "closure_flexible": True}
STRICT = {"type": "interval", "closure_flexible": False}


@pytest.mark.parametrize(
    "raw",
    [
        "(-∞,2]",
        "(-∞, 2)",
        "（－∞，2］",
        "(负无穷,2]",
        "(-inf,2]",
        "(-oo, 2]",
        "(−∞,4/2]",
        "( -∞ , 2.0 ]",
    ],
)
def test_interval_accepts_common_notations(raw):
    result = fill(raw, FLEXIBLE, expected="(-inf,2]")
    assert (result.state, result.outcome) == ("verified", "correct"), raw


@pytest.mark.parametrize("raw", ["[2,+∞)", "(-∞,3]", "(-∞,-2]", "(2,+∞)", "[-∞,2]", "(0,2]"])
def test_wrong_intervals_are_incorrect(raw):
    result = fill(raw, FLEXIBLE, expected="(-inf,2]")

    assert (result.state, result.outcome) == ("verified", "incorrect"), raw
    assert codes(result) == [("b1", "value_incorrect")]


@pytest.mark.parametrize("raw", ["x≤2", "x<=2", "2", "{x|x≤2}", "小于等于 2", "(-∞,2", "(-∞;2]"])
def test_non_interval_notation_is_uncertain(raw):
    assert fill(raw, FLEXIBLE, expected="(-inf,2]").state == "uncertain", raw


def test_closure_matters_when_the_rule_says_so():
    assert fill("[1,3)", STRICT, expected="[1,3)").outcome == "correct"
    assert fill("(1,3)", STRICT, expected="[1,3)").outcome == "incorrect"
    assert fill("(1,3)", FLEXIBLE, expected="[1,3)").outcome == "correct"


def test_infinite_ends_expected_on_the_right():
    assert fill("[1,+∞)", FLEXIBLE, expected="[1,+inf)").outcome == "correct"
    assert fill("[1,∞)", FLEXIBLE, expected="[1,+inf)").outcome == "correct"
    assert fill("(1,正无穷)", FLEXIBLE, expected="[1,+inf)").outcome == "correct"
    assert fill("[1,+∞]", FLEXIBLE, expected="[1,+inf)").outcome == "incorrect"


# ---------------------------------------------------------------- 多空与其他题型


def test_all_blanks_correct():
    result = fill({"b1": "1", "b2": "2"}, NUMERIC, expected={"b1": "1", "b2": "2"})
    assert (result.outcome, result.is_correct) == ("correct", True)


def test_some_blanks_wrong_is_partially_correct_but_not_correct():
    result = fill({"b1": "1", "b2": "9"}, NUMERIC, expected={"b1": "1", "b2": "2"})

    assert (result.state, result.outcome, result.is_correct) == (
        "verified",
        "partially_correct",
        False,
    )
    assert codes(result) == [("b2", "value_incorrect")]


def test_all_blanks_wrong_is_incorrect():
    result = fill({"b1": "7", "b2": "9"}, NUMERIC, expected={"b1": "1", "b2": "2"})
    assert result.outcome == "incorrect"


def test_uncertain_blank_without_any_wrong_blank_makes_the_whole_answer_uncertain():
    result = fill({"b1": "1", "b2": "二"}, NUMERIC, expected={"b1": "1", "b2": "2"})
    assert (result.state, result.is_correct) == ("uncertain", None)


def test_a_definitely_wrong_blank_decides_even_if_another_is_uncertain():
    result = fill({"b1": "7", "b2": "二"}, NUMERIC, expected={"b1": "1", "b2": "2"})
    assert (result.state, result.is_correct) == ("verified", False)


# ---------------------------------------------------------------- 解答题

REFERENCE = {"1": "a ≤ 1", "2": "最大值 3，最小值 -1"}
WRITTEN_CONTENT = {
    "stem": "已知二次函数……",
    "subquestions": [
        {"key": "1", "stem": "求 a 的取值范围", "answer_mode": "written"},
        {"key": "2", "stem": "求最值", "answer_mode": "written"},
    ],
}


def written(answer: dict, *, has_ink: bool = False):
    return grade(
        answer_mode="written",
        content=WRITTEN_CONTENT,
        answer_key={"value": REFERENCE},
        rubric={"points": [{"key": "p1", "part": "1", "text": "写出对称轴"}]},
        teaching={},
        answer=answer,
        has_ink=has_ink,
    )


def parts(**texts: str) -> dict:
    return {"parts": [{"key": key, "text": text} for key, text in texts.items()]}


def test_written_answers_are_never_graded_by_the_system():
    result = written(parts(**{"1": "a≤1", "2": "我不会"}))

    assert (result.state, result.outcome, result.is_correct) == ("pending", "undetermined", None)
    assert result.review_required is True
    assert result.uncertainty_reason == "subjective_self_check"
    assert result.feedback == ()
    assert "不自动评分" in result.message


def test_a_written_answer_identical_to_the_reference_is_still_not_graded():
    """哪怕和参考答案一字不差也不判对：解答题不是靠比对文字来评的，系统不冒充阅卷。"""
    result = written(parts(**{"1": REFERENCE["1"], "2": REFERENCE["2"]}))

    assert (result.state, result.is_correct) == ("pending", None)


def test_a_written_answer_may_cover_only_some_parts():
    assert written(parts(**{"2": "只做了第二问"})).state == "pending"


@pytest.mark.parametrize(
    "answer",
    [{}, {"parts": []}, parts(**{"1": ""}), parts(**{"1": "  \n ", "2": "\t"})],
)
def test_a_written_answer_needs_some_text_or_some_ink(answer):
    with pytest.raises(AnswerShapeError) as error:
        written(answer)

    assert error.value.field == "answer"
    assert written(answer, has_ink=True).state == "pending", "只有笔迹也可以提交"


def test_written_answers_reject_unknown_and_repeated_parts():
    with pytest.raises(AnswerShapeError) as unknown:
        written(parts(**{"1": "写了", "9": "不存在的小问"}))
    assert unknown.value.field == "answer.parts"

    repeated = {"parts": [{"key": "1", "text": "第一次"}, {"key": "1", "text": "第二次"}]}
    with pytest.raises(AnswerShapeError) as duplicate:
        written(repeated)
    assert duplicate.value.field == "answer.parts"


@pytest.mark.parametrize(
    "extra",
    [
        {"selected_options": ["A"]},
        {"blanks": [{"key": "b1", "value": "1"}]},
        {"text": "整段解答"},
    ],
)
def test_written_answers_only_use_parts(extra):
    with pytest.raises(AnswerShapeError) as error:
        written({**parts(**{"1": "写了"}), **extra})

    assert error.value.field == "answer"


def test_objective_questions_reject_parts():
    with pytest.raises(AnswerShapeError):
        choice("single_choice", ["B"], ["B"], parts=[{"key": "1", "text": "x"}])
    with pytest.raises(AnswerShapeError):
        grade(
            answer_mode="fill",
            content={"stem": "题干", "blanks": [{"key": "b1"}]},
            answer_key={"value": {"b1": "4"}, "equivalence_rules": {"b1": NUMERIC}, "units": {}},
            rubric={},
            teaching={},
            answer={"blanks": [{"key": "b1", "value": "4"}], "parts": [{"key": "1", "text": "x"}]},
        )


# ---------------------------------------------------------------- 实验题

EXPERIMENT_REFERENCE = {"t1.r1.v": "0.400", "t1.r2.v": "0.600", "1": "取平均速度，除以 0.10 s"}
EXPERIMENT_CONTENT = {
    "stem": "纸带实验……",
    "data_tables": [
        {
            "key": "t1",
            "title": "纸带数据",
            "columns": [
                {"key": "seg", "label": "线段", "unit": None},
                {"key": "x", "label": "位移", "unit": "cm"},
                {"key": "v", "label": "平均速度", "unit": "m/s"},
            ],
            "rows": [
                {
                    "key": "r1",
                    "label": None,
                    "cells": [
                        {"col": "seg", "text": "AB"},
                        {"col": "x", "text": "4.00"},
                        {"col": "v", "text": None},
                    ],
                },
                {
                    "key": "r2",
                    "label": None,
                    "cells": [
                        {"col": "seg", "text": "BC"},
                        {"col": "x", "text": "6.00"},
                        {"col": "v", "text": None},
                    ],
                },
            ],
        }
    ],
    "subquestions": [{"key": "1", "stem": "说明怎么算平均速度", "answer_mode": "written"}],
}


def experiment(answer: dict, *, has_ink: bool = False, content: dict | None = None):
    return grade(
        answer_mode="experiment",
        content=content or EXPERIMENT_CONTENT,
        answer_key={"value": EXPERIMENT_REFERENCE},
        rubric={"points": [{"key": "p1", "part": "t1", "text": "单位换算"}]},
        teaching={},
        answer=answer,
        has_ink=has_ink,
    )


def cells(*items: tuple[str, str, str, str]) -> dict:
    return {
        "cells": [
            {"table": table, "row": row, "col": col, "value": value}
            for table, row, col, value in items
        ]
    }


def test_experiment_answers_are_never_graded_by_the_system():
    result = experiment(cells(("t1", "r1", "v", "0.5"), ("t1", "r2", "v", "0.1")))

    assert (result.state, result.outcome, result.is_correct) == ("pending", "undetermined", None)
    assert result.review_required is True
    assert result.uncertainty_reason == "subjective_self_check"
    assert result.feedback == ()
    assert "不自动评分" in result.message


def test_an_experiment_answer_identical_to_the_reference_is_still_not_graded():
    """哪怕每个格子都和参考数据一模一样也不判对：实验题不自动评分，系统不冒充阅卷。"""
    answer = {
        **cells(("t1", "r1", "v", "0.400"), ("t1", "r2", "v", "0.600")),
        **parts(**{"1": EXPERIMENT_REFERENCE["1"]}),
    }

    result = experiment(answer)

    assert (result.state, result.is_correct) == ("pending", None)


def test_an_experiment_answer_may_fill_only_some_cells_or_only_text():
    assert experiment(cells(("t1", "r2", "v", "0.6"))).state == "pending"
    assert experiment(parts(**{"1": "先算位移"})).state == "pending"


def test_a_blank_cell_value_with_spaces_around_it_is_kept_as_given():
    assert experiment(cells(("t1", "r1", "v", " 0.4 "))).state == "pending"


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"cells": []},
        {"parts": []},
        cells(("t1", "r1", "v", "  ")),
        parts(**{"1": "\n"}),
        {**cells(("t1", "r1", "v", "")), **parts(**{"1": " "})},
    ],
)
def test_an_experiment_answer_needs_some_filling_or_some_ink(answer):
    with pytest.raises(AnswerShapeError) as error:
        experiment(answer)

    assert error.value.field == "answer"


def test_ink_alone_is_enough_for_an_experiment_answer():
    assert experiment({}, has_ink=True).state == "pending"


@pytest.mark.parametrize(
    "answer",
    [
        cells(("t1", "r1", "x", "4.0")),  # 题目给定的格子，不能改
        cells(("t1", "r1", "seg", "AB")),
        cells(("t9", "r1", "v", "1")),  # 不存在的表
        cells(("t1", "r9", "v", "1")),  # 不存在的行
        cells(("t1", "r1", "zz", "1")),  # 不存在的列
    ],
)
def test_only_the_blank_cells_of_the_question_can_be_filled(answer):
    with pytest.raises(AnswerShapeError) as error:
        experiment(answer)

    assert error.value.field == "answer.cells"


def test_a_cell_can_only_be_filled_once():
    with pytest.raises(AnswerShapeError) as error:
        experiment(cells(("t1", "r1", "v", "0.4"), ("t1", "r1", "v", "0.5")))

    assert error.value.field == "answer.cells"


def test_experiment_parts_must_belong_to_the_question_and_appear_once():
    with pytest.raises(AnswerShapeError) as unknown:
        experiment(parts(**{"9": "x"}))
    assert unknown.value.field == "answer.parts"

    with pytest.raises(AnswerShapeError) as twice:
        experiment({"parts": [{"key": "1", "text": "a"}, {"key": "1", "text": "b"}]})
    assert twice.value.field == "answer.parts"


@pytest.mark.parametrize(
    "answer",
    [
        {"selected_options": ["A"]},
        {"blanks": [{"key": "b1", "value": "1"}]},
        {"text": "我的方案"},
    ],
)
def test_an_experiment_answer_cannot_use_the_other_answer_shapes(answer):
    with pytest.raises(AnswerShapeError) as error:
        experiment({**answer, **cells(("t1", "r1", "v", "0.4"))})

    assert error.value.field == "answer"


def test_an_experiment_without_tables_can_still_be_answered_in_text():
    content = {"stem": "现象解释", "subquestions": EXPERIMENT_CONTENT["subquestions"]}

    assert experiment(parts(**{"1": "产生气泡"}), content=content).state == "pending"
    with pytest.raises(AnswerShapeError):
        experiment(cells(("t1", "r1", "v", "1")), content=content)


@pytest.mark.parametrize(
    ("mode", "content", "key"),
    [
        ("single_choice", {"options": [{"key": "A"}, {"key": "B"}]}, {"value": ["A"]}),
        ("fill", {"blanks": [{"key": "b1"}]}, {"value": {"b1": "1"}}),
        ("written", WRITTEN_CONTENT, {"value": REFERENCE}),
    ],
)
def test_the_other_modes_reject_experiment_cells(mode, content, key):
    answer = {
        "single_choice": {"selected_options": ["A"]},
        "fill": {"blanks": [{"key": "b1", "value": "1"}]},
        "written": parts(**{"1": "x"}),
    }[mode]

    with pytest.raises(AnswerShapeError) as error:
        grade(
            answer_mode=mode,
            content=content,
            answer_key=key,
            rubric={},
            teaching={},
            answer={**answer, **cells(("t1", "r1", "v", "1"))},
        )

    assert error.value.field == "answer"
