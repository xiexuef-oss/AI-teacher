"""证明题（PRD §5"数学解答/证明"、§4.1"证明题逻辑链"）：有"已知 / 求证"，学生把证明写成一步一步，每步带依据。

核心原则（与解答题、实验题一致）：
- 判不出来就弃判：证明题不自动评分，哪怕和参考证明一字不差也不判对；不进任何正确率，也不据此安排复测；
- 自查是学生自己对照参考证明和要点做的记录，不是官方阅卷分数；
- 独立作答阶段不泄题：参考证明和要点只在提交之后才给；题目里只有已知和求证。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from support.flows import (
    EXPERIMENT,
    INK,
    PROOF,
    WRITTEN,
    begin,
    blank,
    cells,
    choice,
    parts,
    solve,
    steps,
    submit,
    tutor,
)
from support.parents import authorize, weekly
from support.seeds import KEY_BY_ID, PROOF_KEYS, WRITTEN_KEYS, qid
from tutor_api.services import task_planner
from tutor_api.services.content_seed import load_seed

DIFF = "math-ineq-diff-proof"
MONO = "math-mono-def-proof"
MUL = "math-ineq-mul-proof"
ENERGY = "phys-work-energy-proof"
STAGES = {"premise", "construction", "reasoning", "conclusion"}


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def _check_path(attempt_id: str) -> str:
    return f"/attempts/{attempt_id}/self-check"


# ---------------------------------------------------------------- 题目


def test_proof_questions_can_be_listed_by_answer_mode(onboarded):
    page = onboarded.data("GET", "/questions", params={"answer_mode": "proof", "limit": 50})

    assert {KEY_BY_ID[item["id"]] for item in page["items"]} == PROOF_KEYS
    assert {item["type"] for item in page["items"]} == {"proof"}
    assert {item["answer_mode"] for item in page["items"]} == {"proof"}
    assert {item["subject"] for item in page["items"]} == {"math", "physics"}


@pytest.mark.parametrize("key", sorted(PROOF_KEYS))
def test_a_proof_question_shows_givens_and_the_claim_and_nothing_to_peek_at(onboarded, key):
    seed = _seed(key)

    question = onboarded.data("GET", f"/questions/{qid(key)}")

    content = question["content"]
    assert content["proof"] == seed["content"]["proof"]
    assert content["proof"]["claim"].strip()
    assert set(content["proof"]) == {"givens", "claim"}
    assert content["options"] == [] and content["blanks"] == [] and content["subquestions"] == []
    assert content["data_tables"] == [] and content["safety"] is None
    note = question["judging_note"]
    assert "不自动评分" in note and "官方" in note and "参考证明" in note
    assert question["assists"]["hint_levels"] == 3
    assert question["assists"]["has_standard_solution"] is True

    # 参考证明、自查要点、解法、提示都不出现在题目接口里
    dump = json.dumps(question, ensure_ascii=False)
    for step in seed["answer"]["value"]["steps"]:
        assert step["text"] not in dump and step["reason"] not in dump
    for point in seed["rubric"]["points"]:
        assert point["text"] not in dump
    for step in seed["solutions"]["standard"]["steps"]:
        assert step not in dump
    for hint in seed["teaching"]["hints"]:
        assert hint not in dump
    assert "reference_steps" not in dump and "stage" not in dump


def test_other_questions_have_no_proof_statement(onboarded):
    for key in (
        "math-mono-quadratic",
        "math-ineq-min",
        "phys-pull-friction-written",
        "phys-tape-experiment",
    ):
        content = onboarded.data("GET", f"/questions/{qid(key)}")["content"]
        assert content["proof"] is None, key


# ---------------------------------------------------------------- 提交


@pytest.mark.parametrize("key", sorted(PROOF_KEYS))
def test_submitting_a_proof_stores_it_without_grading(onboarded, key):
    _, attempt, result = solve(onboarded, key, PROOF[key])

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
    assert stored["status"] == "submitted" and stored["answer"] == PROOF[key]
    assert stored["evaluation"]["state"] == "pending" and stored["evaluation"]["is_correct"] is None


@pytest.mark.parametrize("key", sorted(PROOF_KEYS))
def test_a_proof_identical_to_the_reference_is_still_not_graded(onboarded, key):
    """哪怕每一步都和参考证明一字不差也不判对：证明的写法不止一种，系统不冒充阅卷。"""
    reference = _seed(key)["answer"]["value"]["steps"]
    answer = steps(*[(step["text"], step["reason"]) for step in reference])

    _, _, result = solve(onboarded, key, answer)

    assert (result["evaluation"]["state"], result["evaluation"]["is_correct"]) == ("pending", None)


def test_a_proof_may_be_partial_and_may_leave_the_reasons_out(onboarded):
    _, _, partial = solve(onboarded, DIFF, steps(("先作差", "")))
    _, _, no_reason = solve(onboarded, MONO, steps(("任取 x1<x2", ""), ("作差", "")))

    assert partial["evaluation"]["state"] == no_reason["evaluation"]["state"] == "pending"


def test_nothing_written_and_no_ink_is_rejected_and_the_attempt_stays_open(onboarded):
    session, attempt = begin(onboarded, DIFF)
    path = f"/attempts/{attempt['id']}/submit"

    for answer in (
        {},
        {"steps": []},
        steps(("", "")),
        steps(("  \n", "已知")),  # 只有依据、没有写这一步的内容，不算有内容
        steps(("\t", ""), (" ", "")),
    ):
        error = onboarded.error("POST", path, expect=422, json={"answer": answer})
        assert error["code"] == "validation_error"
        assert error["details"]["errors"][0]["field"] == "answer"

    kept = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert kept["status"] == "draft" and kept["evaluation"] is None
    assert onboarded.data("GET", f"/sessions/{session['id']}")["submitted_attempts"] == 0
    assert onboarded.data("GET", f"/sessions/{session['id']}/events")["items"] == []


def test_ink_alone_is_enough_to_submit_a_proof(onboarded):
    _, attempt = begin(onboarded, MUL)
    onboarded.data(
        "PUT", f"/attempts/{attempt['id']}/draft", json={"base_revision": 0, "strokes": INK}
    )

    result = onboarded.data("POST", f"/attempts/{attempt['id']}/submit", json={"answer": {}})

    assert result["evaluation"]["state"] == "pending"


def test_proof_submission_rejects_answers_of_the_wrong_shape(onboarded):
    _, attempt = begin(onboarded, DIFF)
    path = f"/attempts/{attempt['id']}/submit"
    ok = steps(("ab>0", "已知"))
    wrong_shapes = {
        "混进了选项": {"selected_options": ["A"], **ok},
        "混进了填空": {"blanks": [{"key": "b1", "value": "1"}], **ok},
        "整段文字不分步": {"text": "整段"},
        "混进了小问": {**parts({"1": "没有小问"}), **ok},
        "混进了格子": {**cells(("t1", "r1", "v", "1")), **ok},
        "步骤太多": steps(*[("x", "y")] * 31),
        "文字太长": steps(("x" * 1001, "y")),
        "依据太长": steps(("x", "y" * 401)),
        "步骤多出字段": {"steps": [{"text": "a", "reason": "b", "score": 1}]},
        "步骤缺依据": {"steps": [{"text": "a"}]},
        "步骤缺文字": {"steps": [{"reason": "a"}]},
        "步骤不是对象": {"steps": ["a"]},
    }
    for label, answer in wrong_shapes.items():
        assert onboarded.error("POST", path, expect=422, json={"answer": answer}), label

    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["status"] == "draft"


def test_the_other_question_types_do_not_accept_steps(onboarded):
    extra = steps(("ab>0", "已知"))
    for key, answer in (
        ("math-mono-quadratic", choice("B")),
        ("math-ineq-min", blank("4")),
        ("math-quadratic-param-written", parts({"1": "写了"})),
        ("phys-tape-experiment", cells(("t1", "r1", "v", "0.4"))),
    ):
        _, attempt = begin(onboarded, key)
        error = onboarded.error(
            "POST",
            f"/attempts/{attempt['id']}/submit",
            expect=422,
            json={"answer": {**answer, **extra}},
        )
        assert error["details"]["errors"][0]["field"] == "answer", key


def test_the_steps_are_stored_in_the_order_they_were_written(onboarded):
    answer = steps(("第三步先写", "r3"), ("第一步后写", "r1"), ("第二步", "r2"))

    _, attempt, _ = solve(onboarded, MUL, answer)

    stored = onboarded.data("GET", f"/attempts/{attempt['id']}")["answer"]["steps"]
    assert [step["text"] for step in stored] == ["第三步先写", "第一步后写", "第二步"]


def test_a_proof_draft_round_trips_its_steps_in_order(onboarded):
    _, attempt = begin(onboarded, MONO)
    answer = steps(("任取 x1<x2", "单调性的定义"), ("", ""), ("作差", ""))

    draft = onboarded.data(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        json={"base_revision": 0, "answer": answer, "strokes": INK},
    )

    assert draft["revision"] == 1 and draft["answer"] == answer
    fetched = onboarded.data("GET", f"/attempts/{attempt['id']}/draft")
    assert fetched["answer"] == answer and fetched["strokes"] == INK


def test_a_draft_with_too_many_steps_is_rejected(onboarded):
    _, attempt = begin(onboarded, MONO)

    error = onboarded.error(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        expect=422,
        json={"base_revision": 0, "answer": steps(*[("x", "y")] * 31)},
    )

    assert error["code"] == "validation_error"


# ---------------------------------------------------------------- 对照自查：要点和参考证明


@pytest.mark.parametrize("key", sorted(PROOF_KEYS))
def test_the_checklist_and_the_reference_proof_only_appear_after_submitting(onboarded, key):
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

    submit(onboarded, attempt["id"], PROOF[key])
    checklist = onboarded.data("GET", _check_path(attempt["id"]))

    assert [p["key"] for p in checklist["points"]] == [p["key"] for p in seed["rubric"]["points"]]
    assert all(set(p) == {"key", "part", "text"} for p in checklist["points"])  # 没有分值
    assert {p["part"] for p in checklist["points"]} <= STAGES | {None}
    assert checklist["reference_steps"] == seed["answer"]["value"]["steps"]
    assert all(set(step) == {"stage", "text", "reason"} for step in checklist["reference_steps"])
    assert checklist["reference_steps"][-1]["stage"] == "conclusion"
    assert checklist["reference_cells"] == []
    assert checklist["marks"] == [] and checklist["saved_at"] is None
    assert checklist["summary"]["total"] == len(seed["rubric"]["points"])
    assert "不是官方阅卷分数" in checklist["disclaimer"]


def test_a_proof_self_check_is_saved_like_the_others(onboarded):
    seed = _seed(MONO)
    _, attempt, _ = solve(onboarded, MONO, PROOF[MONO])
    levels = ["done", "partial", "missed"]
    marks = [
        {"point_key": point["key"], "level": levels[index % 3]}
        for index, point in enumerate(seed["rubric"]["points"])
    ]

    saved = onboarded.data("PUT", _check_path(attempt["id"]), json={"marks": marks})

    assert saved["marks"] == marks and saved["saved_at"] is not None
    summary = saved["summary"]
    assert summary["done"] + summary["partial"] + summary["missed"] == len(marks)
    assert (
        saved["reference_steps"]
        == onboarded.data("GET", _check_path(attempt["id"]))["reference_steps"]
    )
    # 每个要点必须恰好评一次
    for broken in (marks[1:], [*marks, marks[0]], [*marks, {"point_key": "zz", "level": "done"}]):
        assert onboarded.error(
            "PUT", _check_path(attempt["id"]), expect=422, json={"marks": broken}
        )


def test_the_other_subjective_self_checks_have_no_reference_steps(onboarded):
    written = sorted(WRITTEN_KEYS)[0]
    _, written_attempt, _ = solve(onboarded, written, WRITTEN[written])
    _, experiment_attempt, _ = solve(
        onboarded, "phys-tape-experiment", EXPERIMENT["phys-tape-experiment"]
    )

    for attempt in (written_attempt, experiment_attempt):
        assert onboarded.data("GET", _check_path(attempt["id"]))["reference_steps"] == []


def test_objective_attempts_have_nothing_to_self_check(onboarded):
    _, attempt, _ = solve(onboarded, "math-mono-quadratic")

    error = onboarded.error("GET", _check_path(attempt["id"]), expect=409)

    assert error["code"] == "self_check_not_applicable"


def test_another_student_cannot_see_the_checklist_or_the_reference_proof(onboarded, new_student):
    _, attempt, _ = solve(onboarded, DIFF, PROOF[DIFF])

    assert new_student().error("GET", _check_path(attempt["id"]), expect=404)


# ---------------------------------------------------------------- 不进正确率、不排复测


def test_proof_work_stays_out_of_accuracy_reviews_and_weak_points(onboarded, clock):
    for key in sorted(PROOF_KEYS):
        solve(onboarded, key, PROOF[key])

    progress = onboarded.data("GET", "/progress/summary")

    for stat in (
        "independent",
        "assisted",
        "hint_dependency",
        "retest_success",
        "variant_transfer",
    ):
        assert progress[stat]["denominator"] == 0, stat
    assert progress["uncertain_attempts"] == 0, "证明题本来就不自动评分，不算'没能判定'"
    assert progress["subjective"]["attempts"] == len(PROOF_KEYS)
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
    assert not {KEY_BY_ID[t["question_id"]] for t in tasks} & PROOF_KEYS, "做过了，不再当新题推"


def test_all_three_kinds_of_subjective_work_are_counted_together(onboarded):
    solve(onboarded, DIFF, PROOF[DIFF])
    solve(onboarded, "chem-ion-equation-written", WRITTEN["chem-ion-equation-written"])
    solve(onboarded, "phys-ohm-experiment", EXPERIMENT["phys-ohm-experiment"])
    _, attempt, _ = solve(onboarded, ENERGY, PROOF[ENERGY])
    onboarded.data(
        "PUT",
        _check_path(attempt["id"]),
        json={
            "marks": [
                {"point_key": p["key"], "level": "done"} for p in _seed(ENERGY)["rubric"]["points"]
            ]
        },
    )

    subjective = onboarded.data("GET", "/progress/summary")["subjective"]

    assert subjective["attempts"] == 4
    assert subjective["self_checked"] == 1
    assert subjective["points_done"] == len(_seed(ENERGY)["rubric"]["points"])


def test_the_parents_weekly_report_counts_proofs_but_never_rates_them(onboarded, parent):
    solve(onboarded, MONO, PROOF[MONO])
    solve(onboarded, "math-quadratic-param-written", WRITTEN["math-quadratic-param-written"])
    authorize(onboarded, parent)

    report = weekly(parent, onboarded.user_id)

    assert report["attempts_count"] == 2 and report["written_attempts"] == 2
    for stat in ("independent", "assisted", "hint_dependency", "retest_success"):
        assert report[stat]["denominator"] == 0, stat
    assert "证明题" in report["disclaimer"]
    dump = json.dumps(report, ensure_ascii=False)
    assert "单调" not in dump and "x1" not in dump, "周报里没有题目内容"


# ---------------------------------------------------------------- 辅导：提示、解析


@pytest.mark.parametrize("key", sorted(PROOF_KEYS))
def test_hints_are_layered_and_the_solution_needs_confirmation_before_submitting(onboarded, key):
    seed = _seed(key)
    session, _ = begin(onboarded, key)

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
    seed = _seed(MUL)
    session, _, _ = solve(onboarded, MUL, PROOF[MUL])

    (event,) = tutor(onboarded, session["id"], "request_standard")["events"]

    assert event["type"] == "standard"
    assert event["payload"]["final_answer"] == seed["solutions"]["standard"]["final_answer"]


# ---------------------------------------------------------------- 今日任务的排序与用时


def _question(mode: str, difficulty: int = 3):
    return SimpleNamespace(answer_mode=mode, difficulty=difficulty)


def test_proof_questions_are_offered_after_the_objective_ones():
    questions = [
        _question("proof"),
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
        "proof",
        "experiment",
        "written",
    ]


def test_a_proof_takes_longer_than_the_other_subjective_questions_of_the_same_difficulty():
    assert task_planner.estimated_minutes(_question("single_choice", 3)) == 6
    assert task_planner.estimated_minutes(_question("written", 3)) == 14
    assert task_planner.estimated_minutes(_question("experiment", 3)) == 16
    assert task_planner.estimated_minutes(_question("proof", 3)) == 18
