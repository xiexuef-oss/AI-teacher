"""实验题（PRD §5、docs/03 P03）：带数据表和安全提示的主观题。

核心原则（与解答题一致）：
- 判不出来就弃判：实验题不自动评分，哪怕数据表里的数和参考数据一模一样也不判对；不进任何正确率，也不据此安排复测；
- 自查是学生自己对照要点和参考数据做的记录，不是官方阅卷分数；
- 独立作答阶段不泄题：要点和参考数据只在提交之后才给；题目里留空的格子没有任何值；
- 每道实验题都有安全提示；它是纸面练习，不是操作指导。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from support.flows import (
    EXPERIMENT,
    INK,
    WRITTEN,
    begin,
    blank,
    cells,
    choice,
    parts,
    solve,
    submit,
    tutor,
)
from support.parents import authorize, weekly
from support.seeds import EXPERIMENT_KEYS, KEY_BY_ID, WRITTEN_KEYS, qid
from tutor_api.services import task_planner
from tutor_api.services.content_seed import load_seed

TAPE = "phys-tape-experiment"
OHM = "phys-ohm-experiment"
TITRATION = "chem-titration-experiment"


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def _blank_cells(seed: dict) -> list[tuple[str, str, str]]:
    return [
        (table["key"], row["key"], cell["col"])
        for table in seed["content"]["data_tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["text"] is None
    ]


def _check_path(attempt_id: str) -> str:
    return f"/attempts/{attempt_id}/self-check"


# ---------------------------------------------------------------- 题目


def test_experiment_questions_can_be_listed_by_answer_mode(onboarded):
    page = onboarded.data("GET", "/questions", params={"answer_mode": "experiment", "limit": 50})

    assert {KEY_BY_ID[item["id"]] for item in page["items"]} == EXPERIMENT_KEYS
    assert {item["type"] for item in page["items"]} == {"experiment"}
    assert {item["answer_mode"] for item in page["items"]} == {"experiment"}
    assert {item["subject"] for item in page["items"]} == {"physics", "chemistry"}


@pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
def test_an_experiment_question_shows_tables_and_safety_notes_and_nothing_to_peek_at(
    onboarded, key
):
    seed = _seed(key)

    question = onboarded.data("GET", f"/questions/{qid(key)}")

    content = question["content"]
    assert content["data_tables"] == seed["content"]["data_tables"]
    assert content["safety"] == seed["content"]["safety"]
    assert content["safety"]["level"] in ("low", "medium")
    assert [s["key"] for s in content["subquestions"]] == [
        s["key"] for s in seed["content"]["subquestions"]
    ]
    assert content["options"] == [] and content["blanks"] == []
    note = question["judging_note"]
    assert "不自动评分" in note and "官方" in note and "不是操作指导" in note
    assert question["assists"]["hint_levels"] == 3
    assert question["assists"]["has_standard_solution"] is True

    # 留空的格子没有值：参考值只在提交之后随自查给出
    blanks = [
        cell["text"]
        for table in content["data_tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["col"] in {col for _, _, col in _blank_cells(seed)} and cell["text"] is None
    ]
    assert len(blanks) == len(_blank_cells(seed))

    # 自查要点、参考答案、解法、提示都不出现在题目接口里
    dump = json.dumps(question, ensure_ascii=False)
    for point in seed["rubric"]["points"]:
        assert point["text"] not in dump
    for cell_key, text in seed["answer"]["value"].items():
        if "." not in cell_key:
            assert text not in dump  # 小问的参考答案文字
    for step in seed["solutions"]["standard"]["steps"]:
        assert step not in dump
    for hint in seed["teaching"]["hints"]:
        assert hint not in dump


def test_other_questions_have_no_tables_and_no_safety_notes(onboarded):
    for key in ("math-mono-quadratic", "math-ineq-min", "phys-pull-friction-written"):
        content = onboarded.data("GET", f"/questions/{qid(key)}")["content"]
        assert content["data_tables"] == [] and content["safety"] is None, key


# ---------------------------------------------------------------- 提交


@pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
def test_submitting_an_experiment_answer_stores_it_without_grading(onboarded, key):
    _, attempt, result = solve(onboarded, key, EXPERIMENT[key])

    evaluation = result["evaluation"]
    assert (evaluation["state"], evaluation["outcome"], evaluation["is_correct"]) == (
        "pending",
        "undetermined",
        None,
    )
    assert evaluation["independent"] is True and evaluation["review_required"] is True
    assert evaluation["feedback"] == []
    assert "不自动评分" in evaluation["message"]
    assert "官方" in evaluation["disclaimer"]
    assert result["review_item"] is None

    (event,) = result["events"]
    assert event["type"] == "uncertainty"
    assert event["payload"]["reason_code"] == "subjective_self_check"
    assert result["session"]["state"] == "DIAGNOSED"

    stored = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert stored["status"] == "submitted" and stored["answer"] == EXPERIMENT[key]
    assert stored["evaluation"]["state"] == "pending" and stored["evaluation"]["is_correct"] is None


@pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
def test_an_answer_identical_to_the_reference_data_is_still_not_graded(onboarded, key):
    """哪怕每个格子都和参考数据一模一样也不判对：实验题不是靠比对来评的，系统不冒充阅卷。"""
    seed = _seed(key)
    reference = seed["answer"]["value"]
    answer = cells(*[(t, r, c, reference[f"{t}.{r}.{c}"]) for t, r, c in _blank_cells(seed)])

    _, _, result = solve(onboarded, key, answer)

    assert (result["evaluation"]["state"], result["evaluation"]["is_correct"]) == ("pending", None)


def test_an_experiment_answer_may_fill_only_some_cells_or_only_text(onboarded):
    _, _, only_cells = solve(onboarded, TAPE, cells(("t1", "r1", "v", "0.4")))
    _, _, only_text = solve(onboarded, OHM, parts({"1": "内接"}))

    assert only_cells["evaluation"]["state"] == only_text["evaluation"]["state"] == "pending"


def test_nothing_filled_and_no_ink_is_rejected_and_the_attempt_stays_open(onboarded):
    session, attempt = begin(onboarded, TAPE)
    path = f"/attempts/{attempt['id']}/submit"

    for answer in ({}, {"cells": []}, cells(("t1", "r1", "v", "  ")), parts({"1": "\n"})):
        error = onboarded.error("POST", path, expect=422, json={"answer": answer})
        assert error["code"] == "validation_error"
        assert error["details"]["errors"][0]["field"] == "answer"

    kept = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert kept["status"] == "draft" and kept["evaluation"] is None
    assert onboarded.data("GET", f"/sessions/{session['id']}")["submitted_attempts"] == 0
    assert onboarded.data("GET", f"/sessions/{session['id']}/events")["items"] == []


def test_ink_alone_is_enough_to_submit_an_experiment_answer(onboarded):
    _, attempt = begin(onboarded, TITRATION)
    onboarded.data(
        "PUT", f"/attempts/{attempt['id']}/draft", json={"base_revision": 0, "strokes": INK}
    )

    result = onboarded.data("POST", f"/attempts/{attempt['id']}/submit", json={"answer": {}})

    assert result["evaluation"]["state"] == "pending"


def test_only_the_blank_cells_of_the_question_can_be_filled(onboarded):
    _, attempt = begin(onboarded, TAPE)
    path = f"/attempts/{attempt['id']}/submit"
    wrong = {
        "题目给定的格子": cells(("t1", "r1", "x", "4.0")),
        "给定的文字格子": cells(("t1", "r1", "seg", "AB")),
        "不存在的表": cells(("t9", "r1", "v", "1")),
        "不存在的行": cells(("t1", "r9", "v", "1")),
        "不存在的列": cells(("t1", "r1", "zz", "1")),
        "同一个格子填两次": cells(("t1", "r1", "v", "1"), ("t1", "r1", "v", "2")),
    }
    for label, answer in wrong.items():
        error = onboarded.error("POST", path, expect=422, json={"answer": answer})
        assert error["details"]["errors"][0]["field"] == "answer.cells", label

    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["status"] == "draft"


def test_experiment_submission_rejects_answers_of_the_wrong_shape(onboarded):
    _, attempt = begin(onboarded, TAPE)
    path = f"/attempts/{attempt['id']}/submit"
    wrong_shapes = {
        "混进了选项": {"selected_options": ["A"], **cells(("t1", "r1", "v", "1"))},
        "混进了填空": {"blanks": [{"key": "b1", "value": "1"}]},
        "整段文字不分小问": {"text": "整段"},
        "不存在的小问": parts({"9": "没有这个小问"}),
        "同一小问写了两次": {"parts": [{"key": "1", "text": "a"}, {"key": "1", "text": "b"}]},
        "格子的值太长": cells(("t1", "r1", "v", "9" * 41)),
        "格子多出字段": {
            "cells": [{"table": "t1", "row": "r1", "col": "v", "value": "1", "score": 1}]
        },
        "格子缺字段": {"cells": [{"table": "t1", "row": "r1", "value": "1"}]},
    }
    for label, answer in wrong_shapes.items():
        assert onboarded.error("POST", path, expect=422, json={"answer": answer}), label

    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["status"] == "draft"


def test_the_other_question_types_do_not_accept_cells(onboarded):
    extra = cells(("t1", "r1", "v", "1"))
    for key, answer in (
        ("math-mono-quadratic", choice("B")),
        ("math-ineq-min", blank("4")),
        ("math-quadratic-param-written", parts({"1": "写了"})),
    ):
        _, attempt = begin(onboarded, key)
        error = onboarded.error(
            "POST",
            f"/attempts/{attempt['id']}/submit",
            expect=422,
            json={"answer": {**answer, **extra}},
        )
        assert error["details"]["errors"][0]["field"] == "answer", key


def test_an_experiment_draft_round_trips_its_cells_and_its_text(onboarded):
    _, attempt = begin(onboarded, OHM)
    answer = {**cells(("t1", "r1", "r", "50.0")), **parts({"1": "先看"})}

    draft = onboarded.data(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        json={"base_revision": 0, "answer": answer, "strokes": INK},
    )

    assert draft["revision"] == 1 and draft["answer"] == answer
    fetched = onboarded.data("GET", f"/attempts/{attempt['id']}/draft")
    assert fetched["answer"] == answer and fetched["strokes"] == INK


# ---------------------------------------------------------------- 对照自查：要点和参考数据

POINTS_KEYS = ("p1",)


@pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
def test_the_checklist_and_reference_data_only_appear_after_submitting(onboarded, key):
    seed = _seed(key)
    session, attempt = begin(onboarded, key)
    error = onboarded.error("GET", _check_path(attempt["id"]), expect=409)
    assert error["code"] == "attempt_not_submitted"
    assert onboarded.error(
        "PUT",
        _check_path(attempt["id"]),
        expect=409,
        json={"marks": [{"point_key": "p1", "level": "done"}]},
    )

    submit(onboarded, attempt["id"], EXPERIMENT[key])
    checklist = onboarded.data("GET", _check_path(attempt["id"]))

    assert [p["key"] for p in checklist["points"]] == [p["key"] for p in seed["rubric"]["points"]]
    assert all(set(p) == {"key", "part", "text"} for p in checklist["points"])  # 没有分值
    expected = [
        {"table": t, "row": r, "col": c, "value": seed["answer"]["value"][f"{t}.{r}.{c}"]}
        for t, r, c in _blank_cells(seed)
    ]
    assert checklist["reference_cells"] == expected
    assert checklist["marks"] == [] and checklist["saved_at"] is None
    assert checklist["summary"]["total"] == len(seed["rubric"]["points"])
    assert "不是官方阅卷分数" in checklist["disclaimer"]


def test_an_experiment_self_check_is_saved_like_a_written_one(onboarded):
    seed = _seed(TAPE)
    _, attempt, _ = solve(onboarded, TAPE, EXPERIMENT[TAPE])
    levels = ["done", "partial", "missed"]
    marks = [
        {"point_key": point["key"], "level": levels[index % 3]}
        for index, point in enumerate(seed["rubric"]["points"])
    ]

    saved = onboarded.data("PUT", _check_path(attempt["id"]), json={"marks": marks})

    assert saved["marks"] == marks and saved["saved_at"] is not None
    assert saved["summary"]["done"] + saved["summary"]["partial"] + saved["summary"][
        "missed"
    ] == len(marks)
    assert (
        saved["reference_cells"]
        == onboarded.data("GET", _check_path(attempt["id"]))["reference_cells"]
    )
    # 每个要点必须恰好评一次
    for broken in (marks[1:], [*marks, marks[0]], [*marks, {"point_key": "zz", "level": "done"}]):
        assert onboarded.error(
            "PUT", _check_path(attempt["id"]), expect=422, json={"marks": broken}
        )


def test_written_self_checks_have_no_reference_cells(onboarded):
    key = sorted(WRITTEN_KEYS)[0]
    _, attempt, _ = solve(onboarded, key, WRITTEN[key])

    assert onboarded.data("GET", _check_path(attempt["id"]))["reference_cells"] == []


def test_objective_attempts_have_nothing_to_self_check(onboarded):
    _, attempt, _ = solve(onboarded, "math-mono-quadratic")

    error = onboarded.error("GET", _check_path(attempt["id"]), expect=409)

    assert error["code"] == "self_check_not_applicable"


def test_another_student_cannot_see_the_checklist_or_the_reference_data(onboarded, new_student):
    _, attempt, _ = solve(onboarded, TAPE, EXPERIMENT[TAPE])

    assert new_student().error("GET", _check_path(attempt["id"]), expect=404)


# ---------------------------------------------------------------- 不进正确率、不排复测


def test_experiment_work_stays_out_of_accuracy_reviews_and_weak_points(onboarded, clock):
    for key in sorted(EXPERIMENT_KEYS):
        solve(onboarded, key, EXPERIMENT[key])

    progress = onboarded.data("GET", "/progress/summary")

    for stat in (
        "independent",
        "assisted",
        "hint_dependency",
        "retest_success",
        "variant_transfer",
    ):
        assert progress[stat]["denominator"] == 0, stat
    assert progress["uncertain_attempts"] == 0, "实验题本来就不自动评分，不算'没能判定'"
    assert progress["subjective"]["attempts"] == 3
    assert [bucket["key"] for bucket in progress["by_answer_mode"]] == [
        "single_choice",
        "multiple_choice",
        "fill",
    ]
    for group in ("by_subject", "by_answer_mode", "by_difficulty"):
        assert all(b["independent"]["denominator"] == 0 for b in progress[group]), group

    clock.advance(days=30)
    assert onboarded.data("GET", "/reviews/due")["items"] == []
    tasks = onboarded.data("GET", "/tasks/today")["items"]
    assert not {t["kind"] for t in tasks} & {"review_mistake", "retest", "weak_point"}
    assert not {KEY_BY_ID[t["question_id"]] for t in tasks} & EXPERIMENT_KEYS, (
        "做过了，不再当新题推"
    )


def test_experiment_and_written_work_are_counted_together_as_subjective(onboarded):
    solve(onboarded, TAPE, EXPERIMENT[TAPE])
    solve(onboarded, "chem-ion-equation-written", WRITTEN["chem-ion-equation-written"])
    _, attempt, _ = solve(onboarded, OHM, EXPERIMENT[OHM])
    onboarded.data(
        "PUT",
        _check_path(attempt["id"]),
        json={
            "marks": [
                {"point_key": p["key"], "level": "done"} for p in _seed(OHM)["rubric"]["points"]
            ]
        },
    )

    subjective = onboarded.data("GET", "/progress/summary")["subjective"]

    assert subjective["attempts"] == 3
    assert subjective["self_checked"] == 1
    assert subjective["points_done"] == len(_seed(OHM)["rubric"]["points"])


def test_the_parents_weekly_report_counts_experiments_but_never_rates_them(onboarded, parent):
    solve(onboarded, TITRATION, EXPERIMENT[TITRATION])
    solve(onboarded, "math-quadratic-param-written", WRITTEN["math-quadratic-param-written"])
    authorize(onboarded, parent)

    report = weekly(parent, onboarded.user_id)

    assert report["attempts_count"] == 2 and report["written_attempts"] == 2
    for stat in ("independent", "assisted", "hint_dependency", "retest_success"):
        assert report[stat]["denominator"] == 0, stat
    assert "实验题" in report["disclaimer"]
    dump = json.dumps(report, ensure_ascii=False)
    assert "滴定" not in dump and "NaOH" not in dump, "周报里没有题目内容"


# ---------------------------------------------------------------- 辅导：提示、解析


def test_hints_are_layered_and_the_solution_needs_confirmation_before_submitting(onboarded):
    seed = _seed(TITRATION)
    session, _ = begin(onboarded, TITRATION)

    shown = []
    for level in (1, 2, 3):
        (event,) = tutor(onboarded, session["id"], "request_hint")["events"]
        assert (event["payload"]["level"], event["payload"]["total_levels"]) == (level, 3)
        shown.append(event["payload"]["text"])
    assert shown == seed["teaching"]["hints"]

    error = onboarded.error(
        "POST",
        f"/tutor/sessions/{session['id']}/next",
        expect=409,
        json={"action": "request_standard"},
    )
    assert error["code"] == "independent_attempt_in_progress"


def test_after_submitting_the_reference_solution_is_available(onboarded):
    seed = _seed(OHM)
    session, _, _ = solve(onboarded, OHM, EXPERIMENT[OHM])

    (event,) = tutor(onboarded, session["id"], "request_standard")["events"]

    assert event["type"] == "standard"
    assert event["payload"]["final_answer"] == seed["solutions"]["standard"]["final_answer"]


# ---------------------------------------------------------------- 今日任务的排序与用时


def _question(mode: str, difficulty: int = 3):
    return SimpleNamespace(answer_mode=mode, difficulty=difficulty)


def test_experiment_questions_are_offered_after_the_objective_ones():
    questions = [
        _question("experiment"),
        _question("written"),
        _question("fill"),
        _question("single_choice"),
        _question("multiple_choice"),
    ]

    ordered = task_planner._objective_first(questions)

    assert [q.answer_mode for q in ordered] == [
        "fill",
        "single_choice",
        "multiple_choice",
        "experiment",
        "written",
    ]


def test_an_experiment_takes_longer_than_a_written_question_of_the_same_difficulty():
    assert task_planner.estimated_minutes(_question("single_choice", 3)) == 6
    assert task_planner.estimated_minutes(_question("written", 3)) == 14
    assert task_planner.estimated_minutes(_question("experiment", 3)) == 16
