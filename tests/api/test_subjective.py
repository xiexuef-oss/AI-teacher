"""解答题（主观题，PRD P0 第 3、4 条）：分小问作答、不自动评分、提交后对照要点自查。

核心原则：
- 判不出来就弃判：解答题没有自动评分，不算对也不算错，不进任何正确率，也不据此安排复测；
- 自查是学生自己对照要点做的记录，不是官方阅卷分数，也不折算成分数；
- 独立作答阶段不泄题：要点只在提交之后才给。
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select

from support.admin import decide, detail_of, edit, edit_body
from support.flows import (
    INK,
    WRITTEN,
    begin,
    blank,
    choice,
    new_attempt,
    parts,
    solve,
    submit,
    tutor,
    tutor_error,
)
from support.seeds import KEY_BY_ID, WRITTEN_KEYS, qid
from tutor_api.services.content_seed import load_seed

MATH = "math-quadratic-param-written"
PHYS = "phys-pull-friction-written"
CHEM = "chem-ion-equation-written"


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def _check_path(attempt_id: str) -> str:
    return f"/attempts/{attempt_id}/self-check"


def _rate(points: list[dict], level: str = "done") -> dict:
    return {"marks": [{"point_key": point["key"], "level": level} for point in points]}


def _checklist(student, attempt_id: str) -> dict:
    return student.data("GET", _check_path(attempt_id))


# ---------------------------------------------------------------- 题目


def test_written_questions_can_be_listed_by_answer_mode(onboarded):
    page = onboarded.data("GET", "/questions", params={"answer_mode": "written", "limit": 50})

    assert {KEY_BY_ID[item["id"]] for item in page["items"]} == WRITTEN_KEYS
    assert {item["type"] for item in page["items"]} == {"solution"}
    assert {item["answer_mode"] for item in page["items"]} == {"written"}


@pytest.mark.parametrize("key", sorted(WRITTEN_KEYS))
def test_a_written_question_shows_its_subquestions_and_nothing_to_peek_at(onboarded, key):
    seed = _seed(key)

    question = onboarded.data("GET", f"/questions/{qid(key)}")

    subquestions = question["content"]["subquestions"]
    assert [s["key"] for s in subquestions] == [s["key"] for s in seed["content"]["subquestions"]]
    assert {s["answer_mode"] for s in subquestions} == {"written"}
    assert all(s["options"] == [] and s["blanks"] == [] for s in subquestions)
    assert question["content"]["options"] == [] and question["content"]["blanks"] == []
    assert "不自动评分" in question["judging_note"] and "官方" in question["judging_note"]
    assert question["assists"]["hint_levels"] == 3
    assert question["assists"]["has_standard_solution"] is True

    # 自查要点、参考答案、解法都不出现在题目接口里
    dump = json.dumps(question, ensure_ascii=False)
    for point in seed["rubric"]["points"]:
        assert point["text"] not in dump
    for text in seed["answer"]["value"].values():
        assert text not in dump
    for step in seed["solutions"]["standard"]["steps"]:
        assert step not in dump


def test_objective_questions_keep_their_judging_notes_apart_from_written(onboarded):
    multi = onboarded.data("GET", f"/questions/{qid('math-mono-judge')}")
    single = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")

    assert "自查" not in multi["judging_note"]
    assert single["judging_note"] is None


# ---------------------------------------------------------------- 提交


@pytest.mark.parametrize("key", sorted(WRITTEN_KEYS))
def test_submitting_a_written_answer_stores_it_without_grading(onboarded, key):
    _, attempt, result = solve(onboarded, key, WRITTEN[key])

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
    assert event["payload"]["review_required"] is True
    assert result["session"]["state"] == "DIAGNOSED"

    stored = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert stored["status"] == "submitted" and stored["answer"] == WRITTEN[key]
    assert stored["evaluation"]["state"] == "pending" and stored["evaluation"]["is_correct"] is None


def test_a_written_answer_may_cover_only_some_subquestions(onboarded):
    _, _, result = solve(onboarded, MATH, parts({"2": "只做了第 (2) 问"}))

    assert result["evaluation"]["state"] == "pending"


def test_nothing_written_and_no_ink_is_rejected_and_the_attempt_stays_open(onboarded):
    session, attempt = begin(onboarded, MATH)
    path = f"/attempts/{attempt['id']}/submit"

    for answer in ({}, {"parts": []}, parts({"1": "   ", "2": "\n"})):
        error = onboarded.error("POST", path, expect=422, json={"answer": answer})
        assert error["code"] == "validation_error"
        assert error["details"]["errors"][0]["field"] == "answer"

    kept = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert kept["status"] == "draft" and kept["evaluation"] is None
    assert onboarded.data("GET", f"/sessions/{session['id']}")["submitted_attempts"] == 0
    assert onboarded.data("GET", f"/sessions/{session['id']}/events")["items"] == []


def test_ink_alone_is_enough_to_submit_a_written_answer(onboarded):
    _, attempt = begin(onboarded, PHYS)
    onboarded.data(
        "PUT", f"/attempts/{attempt['id']}/draft", json={"base_revision": 0, "strokes": INK}
    )

    result = onboarded.data("POST", f"/attempts/{attempt['id']}/submit", json={"answer": {}})

    assert result["evaluation"]["state"] == "pending"
    assert result["attempt"]["status"] == "submitted"


def test_an_empty_page_of_ink_does_not_count(onboarded):
    _, attempt = begin(onboarded, PHYS)
    empty = {"version": 1, "pages": [{"width": 800, "height": 600, "strokes": []}]}
    onboarded.data(
        "PUT", f"/attempts/{attempt['id']}/draft", json={"base_revision": 0, "strokes": empty}
    )

    error = onboarded.error(
        "POST", f"/attempts/{attempt['id']}/submit", expect=422, json={"answer": {}}
    )

    assert error["details"]["errors"][0]["field"] == "answer"


def test_written_submission_rejects_answers_of_the_wrong_shape(onboarded):
    _, attempt = begin(onboarded, MATH)
    path = f"/attempts/{attempt['id']}/submit"
    wrong_shapes = {
        "混进了选项": {"selected_options": ["A"], **parts({"1": "写了"})},
        "混进了填空": {"blanks": [{"key": "b1", "value": "1"}]},
        "整段文字不分小问": {"text": "整段解答"},
        "不存在的小问": parts({"9": "没有这个小问"}),
        "同一小问写了两次": {"parts": [{"key": "1", "text": "a"}, {"key": "1", "text": "b"}]},
        "超长": parts({"1": "字" * 4001}),
        "小问键为空": parts({"": "x"}),
    }
    for label, answer in wrong_shapes.items():
        assert onboarded.error("POST", path, expect=422, json={"answer": answer}), label

    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["status"] == "draft"


def test_objective_questions_do_not_accept_parts(onboarded):
    _, choice_attempt = begin(onboarded, "math-mono-quadratic")
    onboarded.error(
        "POST",
        f"/attempts/{choice_attempt['id']}/submit",
        expect=422,
        json={"answer": {**choice("B"), **parts({"1": "x"})}},
    )
    _, fill_attempt = begin(onboarded, "math-ineq-min")
    onboarded.error(
        "POST",
        f"/attempts/{fill_attempt['id']}/submit",
        expect=422,
        json={"answer": {**blank("4"), **parts({"1": "x"})}},
    )


def test_a_written_draft_round_trips_its_parts_and_its_ink(onboarded):
    _, attempt = begin(onboarded, MATH)
    answer = parts({"1": "写到一半"})

    draft = onboarded.data(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        json={"base_revision": 0, "answer": answer, "strokes": INK},
    )

    assert draft["revision"] == 1 and draft["answer"] == answer
    fetched = onboarded.data("GET", f"/attempts/{attempt['id']}/draft")
    assert fetched["answer"] == answer and fetched["strokes"] == INK
    # 草稿里的作答在提交时被原样存下来
    result = onboarded.data(
        "POST", f"/attempts/{attempt['id']}/submit", json={"answer": parts({"1": "写完了"})}
    )
    assert result["attempt"]["answer"] == parts({"1": "写完了"})


# ---------------------------------------------------------------- 不进正确率、不排复测


def test_written_work_stays_out_of_accuracy_reviews_and_weak_points(onboarded, clock):
    for key in sorted(WRITTEN_KEYS):
        solve(onboarded, key, WRITTEN[key])

    progress = onboarded.data("GET", "/progress/summary")

    for stat in (
        "independent",
        "assisted",
        "hint_dependency",
        "retest_success",
        "variant_transfer",
    ):
        assert progress[stat]["denominator"] == 0, stat
        assert progress[stat]["numerator"] == 0, stat
    assert progress["uncertain_attempts"] == 0, "解答题本来就不自动评分，不算'没能判定'"
    assert progress["subjective"] == {
        "attempts": 3,
        "self_checked": 0,
        "points_done": 0,
        "points_partial": 0,
        "points_missed": 0,
    }
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
    assert not {KEY_BY_ID[t["question_id"]] for t in tasks} & WRITTEN_KEYS, "做过了，不再当新题推"


def test_uncertain_objective_attempts_are_counted_apart_from_written_ones(onboarded):
    solve(onboarded, "math-ineq-min", blank("四"))  # 认不出的写法：待确认
    solve(onboarded, MATH, WRITTEN[MATH])

    progress = onboarded.data("GET", "/progress/summary")

    assert progress["uncertain_attempts"] == 1
    assert progress["subjective"]["attempts"] == 1


def test_a_new_student_has_no_subjective_work(onboarded):
    progress = onboarded.data("GET", "/progress/summary")

    assert progress["subjective"] == {
        "attempts": 0,
        "self_checked": 0,
        "points_done": 0,
        "points_partial": 0,
        "points_missed": 0,
    }


# ---------------------------------------------------------------- 辅导：提示、解析、重做、结束


def test_hints_are_layered_and_the_solution_needs_confirmation_before_submitting(onboarded):
    seed = _seed(MATH)
    session, _ = begin(onboarded, MATH)

    shown = []
    for level in (1, 2, 3):
        (event,) = tutor(onboarded, session["id"], "request_hint")["events"]
        assert (event["payload"]["level"], event["payload"]["total_levels"]) == (level, 3)
        shown.append(event["payload"]["text"])
    assert shown == seed["teaching"]["hints"]

    error = tutor_error(onboarded, session["id"], "request_standard", expect=409)
    assert error["code"] == "independent_attempt_in_progress"


def test_after_submitting_the_reference_solution_is_available(onboarded):
    seed = _seed(CHEM)
    session, _, _ = solve(onboarded, CHEM, WRITTEN[CHEM])

    step = tutor(onboarded, session["id"], "request_standard")

    (event,) = step["events"]
    assert event["type"] == "standard"
    assert event["payload"]["final_answer"] == seed["solutions"]["standard"]["final_answer"]
    assert event["payload"]["option_analysis"] == []
    assert step["session"]["used_solution"] is True


def test_a_written_question_can_be_redone_and_the_redo_is_not_independent(onboarded):
    session, _, first = solve(onboarded, PHYS, WRITTEN[PHYS])
    assert first["evaluation"]["independent"] is True

    retry = new_attempt(onboarded, session["id"])
    second = submit(onboarded, retry["id"], WRITTEN[PHYS])

    assert retry["attempt_no"] == 2
    assert second["evaluation"]["independent"] is False
    assert second["evaluation"]["state"] == "pending"
    assert second["review_item"] is None


def test_finishing_a_written_question_does_not_schedule_a_retest(onboarded):
    session, _, _ = solve(onboarded, MATH, WRITTEN[MATH])

    step = tutor(onboarded, session["id"], "mark_understood")

    codes = [e["payload"].get("code") for e in step["events"] if e["type"] == "notice"]
    assert "session_completed" in codes and "review_scheduled" not in codes
    assert step["session"]["state"] == "DONE"


# ---------------------------------------------------------------- 自查：提交之前不给要点


def test_the_checklist_is_not_available_before_submitting(onboarded):
    seed = _seed(MATH)
    _, attempt = begin(onboarded, MATH)
    path = _check_path(attempt["id"])

    error = onboarded.error("GET", path, expect=409)

    assert error["code"] == "attempt_not_submitted"
    text = json.dumps(error, ensure_ascii=False)
    assert not any(point["text"] in text for point in seed["rubric"]["points"])
    marks = {"marks": [{"point_key": "p1", "level": "done"}]}
    assert onboarded.error("PUT", path, expect=409, json=marks)["code"] == "attempt_not_submitted"


def test_a_failed_submission_does_not_open_the_checklist(onboarded):
    _, attempt = begin(onboarded, MATH)
    onboarded.error("POST", f"/attempts/{attempt['id']}/submit", expect=422, json={"answer": {}})

    assert onboarded.error("GET", _check_path(attempt["id"]), expect=409)["code"] == (
        "attempt_not_submitted"
    )


def test_after_submitting_the_student_gets_the_checklist(onboarded):
    seed = _seed(MATH)
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])

    check = _checklist(onboarded, attempt["id"])

    assert check["attempt_id"] == attempt["id"]
    assert check["points"] == seed["rubric"]["points"]
    assert check["marks"] == [] and check["saved_at"] is None
    total = len(seed["rubric"]["points"])
    assert check["summary"] == {"done": 0, "partial": 0, "missed": 0, "total": total}
    assert "官方" in check["disclaimer"] and "不是" in check["disclaimer"]
    assert not {"score", "weight", "points_earned"} & set(json.dumps(check))


@pytest.mark.parametrize("key", sorted(WRITTEN_KEYS))
def test_every_sample_has_a_checklist_covering_each_subquestion(onboarded, key):
    _, attempt, _ = solve(onboarded, key, WRITTEN[key])

    points = _checklist(onboarded, attempt["id"])["points"]

    parts_of_question = {s["key"] for s in _seed(key)["content"]["subquestions"]}
    assert parts_of_question <= {p["part"] for p in points}
    assert len({p["key"] for p in points}) == len(points)


def test_the_checklist_does_not_change_after_opening_the_solution(onboarded):
    session, attempt, _ = solve(onboarded, PHYS, WRITTEN[PHYS])
    before = _checklist(onboarded, attempt["id"])

    tutor(onboarded, session["id"], "request_standard")

    assert _checklist(onboarded, attempt["id"]) == before


# ---------------------------------------------------------------- 自查：保存


def test_saving_a_self_check_records_marks_and_counts_without_scoring(onboarded):
    session, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])
    points = _checklist(onboarded, attempt["id"])["points"]
    levels = ["done", "done", "partial", "missed", "missed", "done", "partial"]
    assert len(points) == len(levels)
    body = {
        "marks": [
            {"point_key": p["key"], "level": lv} for p, lv in zip(points, levels, strict=True)
        ]
    }

    saved = onboarded.data("PUT", _check_path(attempt["id"]), json=body)

    assert saved["marks"] == body["marks"]
    assert saved["summary"] == {"done": 3, "partial": 2, "missed": 2, "total": 7}
    assert saved["saved_at"] is not None
    assert saved["points"] == points
    assert _checklist(onboarded, attempt["id"]) == saved

    # 自查不是评分：作答的评估、会话的状态都没有变
    kept = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert kept["evaluation"]["state"] == "pending" and kept["evaluation"]["is_correct"] is None
    assert onboarded.data("GET", f"/sessions/{session['id']}")["state"] == "DIAGNOSED"


def test_the_self_check_can_be_revised(onboarded, clock):
    _, attempt, _ = solve(onboarded, PHYS, WRITTEN[PHYS])
    points = _checklist(onboarded, attempt["id"])["points"]
    first = onboarded.data("PUT", _check_path(attempt["id"]), json=_rate(points, "missed"))
    assert first["summary"]["missed"] == len(points)

    clock.advance(minutes=5)
    second = onboarded.data("PUT", _check_path(attempt["id"]), json=_rate(points, "done"))

    assert second["summary"] == {
        "done": len(points),
        "partial": 0,
        "missed": 0,
        "total": len(points),
    }
    assert second["saved_at"] > first["saved_at"]
    assert _checklist(onboarded, attempt["id"])["marks"] == _rate(points, "done")["marks"]


def test_saving_the_same_marks_twice_with_the_same_key_stores_one_self_check(onboarded, db):
    from tutor_api.models import AttemptSelfCheck

    _, attempt, _ = solve(onboarded, CHEM, WRITTEN[CHEM])
    points = _checklist(onboarded, attempt["id"])["points"]
    path = _check_path(attempt["id"])
    key = f"selfcheck-{uuid.uuid4()}"

    first = onboarded.put(path, json=_rate(points, "partial"), key=key)
    second = onboarded.put(path, json=_rate(points, "partial"), key=key)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert db.scalar(select(func.count()).select_from(AttemptSelfCheck)) == 1
    different = onboarded.error("PUT", path, expect=409, json=_rate(points, "done"), key=key)
    assert different["code"] == "idempotency_key_conflict"
    assert onboarded.error("PUT", path, expect=400, json=_rate(points), key=False)["code"] == (
        "idempotency_key_required"
    )


def test_a_self_check_must_rate_every_point_exactly_once(onboarded):
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])
    path = _check_path(attempt["id"])
    full = _rate(_checklist(onboarded, attempt["id"])["points"])["marks"]
    bad = {
        "漏评一条": {"marks": full[:-1]},
        "一条都没有": {"marks": []},
        "同一条评了两次": {"marks": [*full, full[0]]},
        "不认识的要点顶替了一条": {"marks": [*full[:-1], {"point_key": "zzz", "level": "done"}]},
        "多评了一条不存在的要点": {"marks": [*full, {"point_key": "zzz", "level": "done"}]},
        "等级不对": {"marks": [{**full[0], "level": "perfect"}, *full[1:]]},
        "想打分": {"marks": [{**full[0], "score": 2}, *full[1:]]},
        "多余字段": {"marks": full, "total_score": 10},
    }

    for label, body in bad.items():
        assert onboarded.error("PUT", path, expect=422, json=body), label

    nothing = _checklist(onboarded, attempt["id"])
    assert nothing["marks"] == [] and nothing["saved_at"] is None


def test_a_rejected_revision_keeps_the_previous_self_check(onboarded):
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])
    path = _check_path(attempt["id"])
    points = _checklist(onboarded, attempt["id"])["points"]
    saved = onboarded.data("PUT", path, json=_rate(points, "done"))

    onboarded.error("PUT", path, expect=422, json={"marks": _rate(points)["marks"][:-1]})

    assert _checklist(onboarded, attempt["id"]) == saved


# ---------------------------------------------------------------- 自查：归属与适用范围


def test_a_self_check_belongs_to_its_student(onboarded, new_student, reviewer, anon):
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])
    path = _check_path(attempt["id"])
    points = _checklist(onboarded, attempt["id"])["points"]
    stranger = new_student()

    assert stranger.error("GET", path, expect=404)["code"] == "not_found"
    assert stranger.error("PUT", path, expect=404, json=_rate(points))["code"] == "not_found"
    assert reviewer.error("GET", path, expect=403)["code"] == "forbidden"
    assert reviewer.error("PUT", path, expect=403, json=_rate(points))["code"] == "forbidden"
    assert anon.error("GET", path, expect=401)["code"] == "unauthenticated"
    # 别人没能读到，也没能写进去
    assert _checklist(onboarded, attempt["id"])["marks"] == []
    onboarded.error("GET", _check_path(str(uuid.uuid4())), expect=404)


def test_objective_attempts_have_no_self_check(onboarded):
    _, attempt, _ = solve(onboarded, "math-mono-quadratic")
    path = _check_path(attempt["id"])

    assert onboarded.error("GET", path, expect=409)["code"] == "self_check_not_applicable"
    marks = {"marks": [{"point_key": "p1", "level": "done"}]}
    error = onboarded.error("PUT", path, expect=409, json=marks)
    assert error["code"] == "self_check_not_applicable"


def test_the_self_check_follows_the_version_the_student_worked_on(onboarded, new_reviewer):
    """学生做的是第 1 版，之后题目改过：这份作答的自查仍是第 1 版的要点；新开的会话才用新要点。"""
    seed = _seed(MATH)
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])

    publisher = new_reviewer()
    decide(publisher, qid(MATH), "withdraw", comment="要点改写")
    before = detail_of(publisher, qid(MATH))
    new_points = [
        {"key": "q1", "part": "1", "text": "新版要点：第 (1) 问的结论"},
        {"key": "q2", "part": "2", "text": "新版要点：第 (2) 问的结论"},
    ]
    edit(new_reviewer(), qid(MATH), edit_body(before, rubric={"points": new_points}))
    decide(publisher, qid(MATH), "approve", version=2)
    decide(publisher, qid(MATH), "publish", version=2)

    old = _checklist(onboarded, attempt["id"])
    assert old["points"] == seed["rubric"]["points"]
    onboarded.data("PUT", _check_path(attempt["id"]), json=_rate(old["points"], "done"))

    _, fresh, _ = solve(onboarded, MATH, WRITTEN[MATH])
    assert _checklist(onboarded, fresh["id"])["points"] == new_points


# ---------------------------------------------------------------- 学情：只数自查，不折算成分数


def test_progress_counts_self_checks_but_never_turns_them_into_accuracy(onboarded):
    _, first, _ = solve(onboarded, MATH, WRITTEN[MATH])
    points = _checklist(onboarded, first["id"])["points"]
    levels = ["done", "done", "partial", "missed", "missed", "done", "partial"]
    onboarded.data(
        "PUT",
        _check_path(first["id"]),
        json={
            "marks": [
                {"point_key": p["key"], "level": lv} for p, lv in zip(points, levels, strict=True)
            ]
        },
    )
    solve(onboarded, PHYS, WRITTEN[PHYS])  # 提交了，没有自查

    progress = onboarded.data("GET", "/progress/summary")

    assert progress["subjective"] == {
        "attempts": 2,
        "self_checked": 1,
        "points_done": 3,
        "points_partial": 2,
        "points_missed": 2,
    }
    for stat in (
        "independent",
        "assisted",
        "hint_dependency",
        "retest_success",
        "variant_transfer",
    ):
        assert progress[stat]["denominator"] == 0, stat

    # 改了自评，统计跟着最新的一次走，而不是累加
    onboarded.data("PUT", _check_path(first["id"]), json=_rate(points, "missed"))
    again = onboarded.data("GET", "/progress/summary")["subjective"]
    assert again["points_done"] == 0 and again["points_missed"] == 7 and again["self_checked"] == 1


def test_another_students_self_check_is_not_in_my_progress(onboarded, new_student):
    _, attempt, _ = solve(onboarded, MATH, WRITTEN[MATH])
    onboarded.data(
        "PUT",
        _check_path(attempt["id"]),
        json=_rate(_checklist(onboarded, attempt["id"])["points"]),
    )

    assert new_student().data("GET", "/progress/summary")["subjective"]["self_checked"] == 0


# ---------------------------------------------------------------- 今日任务


def test_a_new_student_is_not_started_on_a_written_question(onboarded, db):
    """解答题不当第一道题：哪怕它排得最前（这里把难度压到最低），起步题仍是可以自动判定的题。"""
    from tutor_api.models import Question

    for key in WRITTEN_KEYS:
        db.get(Question, qid(key)).difficulty = 1
    db.commit()

    tasks = onboarded.data("GET", "/tasks/today")["items"]

    assert tasks and not {KEY_BY_ID[t["question_id"]] for t in tasks} & WRITTEN_KEYS


def test_written_questions_are_recommended_once_the_objective_ones_are_done(onboarded):
    for key in ("chem-conservation-co2", "chem-conservation-h2", "chem-ion-inference"):
        solve(onboarded, key)  # 对这个学生可发的化学选择题与填空题都做完了

    tasks = onboarded.data("GET", "/tasks/today")["items"]

    chemistry = [t for t in tasks if t["subject"] == "chemistry"]
    assert [KEY_BY_ID[t["question_id"]] for t in chemistry] == [CHEM]
    assert chemistry[0]["kind"] == "new_topic"
    assert chemistry[0]["estimated_minutes"] > 3 + _seed(CHEM)["difficulty"], (
        "解答题要写完整步骤，用时更长"
    )
