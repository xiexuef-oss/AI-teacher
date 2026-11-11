"""间隔复测（docs/06 §7）。默认间隔 T+1、T+3、T+7 天。"""

from __future__ import annotations

import uuid

import pytest

from support.flows import begin, blank, choice, new_attempt, solve, submit, tutor
from support.seeds import qid

KEY = "math-ineq-min"  # 正确答案 4


def _mistake(student, key=KEY, wrong=None) -> dict:
    """做错一道题，返回自动安排的复测项。"""
    _, _, result = solve(student, key, wrong or blank("5"))
    return result["review_item"]


def _reviews(student, scope="due") -> list[dict]:
    return student.data("GET", "/reviews/due", params={"scope": scope})["items"]


def _retest(student, item, answer, key=KEY) -> tuple[dict, dict, dict]:
    """用到期的复测项开会话并提交一次，返回 (会话, 作答, 提交结果)。"""
    session, attempt = begin(student, key, origin="review", review_item_id=item["id"])
    return session, attempt, submit(student, attempt["id"], answer)


def _complete(student, item, attempt, **kwargs) -> dict:
    return student.data(
        "POST", f"/reviews/{item['id']}/complete", json={"attempt_id": attempt["id"]}, **kwargs
    )


def _complete_error(student, item_id, attempt_id, *, expect: int) -> dict:
    return student.error(
        "POST", f"/reviews/{item_id}/complete", expect=expect, json={"attempt_id": attempt_id}
    )


# ---------------------------------------------------------------- 到期


def test_a_mistake_is_scheduled_but_not_due_yet(onboarded):
    item = _mistake(onboarded)

    assert _reviews(onboarded) == []
    (listed,) = _reviews(onboarded, scope="all")
    assert listed == item
    assert listed["question_title"] == "用基本不等式求最小值" and listed["subject"] == "math"
    assert (listed["stage"], listed["total_stages"], listed["is_due"]) == (0, 3, False)


def test_item_becomes_due_after_the_first_interval(onboarded, clock):
    item = _mistake(onboarded)

    clock.advance(hours=23, minutes=59)
    assert _reviews(onboarded) == []
    clock.advance(minutes=1)

    (due,) = _reviews(onboarded)
    assert due["id"] == item["id"] and due["is_due"] is True


def test_review_session_needs_a_due_item_of_the_same_question(onboarded, clock):
    item = _mistake(onboarded)
    body = {"question_id": qid(KEY), "origin": "review", "review_item_id": item["id"]}

    early = onboarded.error("POST", "/sessions", expect=409, json=body)
    assert early["code"] == "review_not_due"
    assert early["details"] == {"due_at": item["due_at"]}

    clock.advance(days=1)
    wrong_question = {**body, "question_id": qid("math-ineq-rect")}
    onboarded.error("POST", "/sessions", expect=422, json=wrong_question)
    onboarded.error(
        "POST", "/sessions", expect=404, json={**body, "review_item_id": str(uuid.uuid4())}
    )

    session = onboarded.data("POST", "/sessions", expect=201, json=body)
    assert session["origin"] == "review" and session["review_item_id"] == item["id"]


# ---------------------------------------------------------------- 通过与未通过


def test_passing_a_retest_moves_to_the_next_interval(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, attempt, result = _retest(onboarded, item, blank("4"))
    assert result["evaluation"]["independent"] is True
    assert result["review_item"] is None, "复测会话的提交不自行改排期，由 complete 记录结果"

    done = _complete(onboarded, item, attempt)

    assert done["result"] == "passed"
    assert done["next_due_at"] == "2026-11-14T08:00:00Z", "通过第一档后间隔 3 天"
    assert (done["review_item"]["stage"], done["review_item"]["status"]) == (1, "scheduled")
    assert done["review_item"]["last_result"] == "passed"
    assert done["review_item"]["is_due"] is False
    assert _reviews(onboarded) == []


def test_three_passes_master_the_item(onboarded, clock):
    item = _mistake(onboarded)
    outcomes = []
    for days in (1, 3, 7):
        clock.advance(days=days)
        _, attempt, _ = _retest(onboarded, item, blank("4"))
        outcomes.append(_complete(onboarded, item, attempt))

    assert [o["review_item"]["stage"] for o in outcomes] == [1, 2, 3]
    assert outcomes[1]["next_due_at"] == "2026-11-21T08:00:00Z", "第二档之后间隔 7 天"
    assert outcomes[2]["review_item"]["status"] == "mastered"
    assert outcomes[2]["next_due_at"] is None
    clock.advance(days=30)
    assert _reviews(onboarded, scope="all") == []


def test_failing_a_retest_goes_back_to_the_first_interval(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, attempt, _ = _retest(onboarded, item, blank("4"))
    _complete(onboarded, item, attempt)
    clock.advance(days=3)

    _, attempt, _ = _retest(onboarded, item, blank("7"))
    done = _complete(onboarded, item, attempt)

    assert done["result"] == "failed"
    assert (done["review_item"]["stage"], done["review_item"]["status"]) == (0, "scheduled")
    assert done["review_item"]["last_result"] == "failed"
    assert done["next_due_at"] == "2026-11-15T08:00:00Z", "未通过：回到第一档，1 天后再测"


def test_only_the_first_submission_of_a_retest_counts(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    session, _, _ = _retest(onboarded, item, blank("9"))
    retry = new_attempt(onboarded, session["id"])
    submit(onboarded, retry["id"], blank("4"))

    done = _complete(onboarded, item, retry)

    assert done["result"] == "failed", "看过反馈之后的重试不能算复测通过"


def test_retest_with_help_after_submission_still_judged_by_the_unaided_first_answer(
    onboarded, clock
):
    item = _mistake(onboarded)
    clock.advance(days=1)
    session, attempt, _ = _retest(onboarded, item, blank("4"))
    tutor(onboarded, session["id"], "request_standard")

    assert _complete(onboarded, item, attempt)["result"] == "passed"


# ---------------------------------------------------------------- 结果只取服务端判定


def test_client_cannot_claim_a_result(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, attempt, _ = _retest(onboarded, item, blank("7"))
    path = f"/reviews/{item['id']}/complete"

    for claimed in ({"result": "passed"}, {"passed": True}, {"is_correct": True}):
        onboarded.error("POST", path, expect=422, json={"attempt_id": attempt["id"], **claimed})

    assert _complete(onboarded, item, attempt)["result"] == "failed"


def test_unverified_attempt_cannot_complete_a_retest(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    session, attempt = begin(onboarded, KEY, origin="review", review_item_id=item["id"])

    assert (
        _complete_error(onboarded, item["id"], attempt["id"], expect=409)["code"]
        == "attempt_not_verified"
    )

    submit(onboarded, attempt["id"], blank("四"))
    assert (
        _complete_error(onboarded, item["id"], attempt["id"], expect=409)["code"]
        == "attempt_not_verified"
    )
    (still_due,) = _reviews(onboarded)
    assert still_due["stage"] == 0 and still_due["last_result"] is None


def test_attempt_must_come_from_a_session_opened_with_this_review_item(
    onboarded, new_student, clock
):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, practice_attempt, _ = solve(onboarded, KEY, blank("4"))

    error = _complete_error(onboarded, item["id"], practice_attempt["id"], expect=409)
    assert error["code"] == "attempt_not_for_this_review"

    stranger = new_student()
    _, foreign_attempt, _ = solve(stranger, KEY, blank("4"))
    _complete_error(onboarded, item["id"], foreign_attempt["id"], expect=404)
    _complete_error(onboarded, str(uuid.uuid4()), practice_attempt["id"], expect=404)
    _complete_error(onboarded, item["id"], str(uuid.uuid4()), expect=404)


def test_a_retest_is_recorded_only_once(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, attempt, _ = _retest(onboarded, item, blank("4"))
    key = f"complete-{uuid.uuid4()}"

    first = _complete(onboarded, item, attempt, key=key)
    replayed = _complete(onboarded, item, attempt, key=key)
    again = _complete_error(onboarded, item["id"], attempt["id"], expect=409)

    assert replayed == first
    assert again["code"] == "review_already_completed"
    assert _reviews(onboarded, scope="all")[0]["stage"] == 1


def test_complete_requires_idempotency_key(onboarded, clock):
    item = _mistake(onboarded)
    body = {"attempt_id": str(uuid.uuid4())}
    error = onboarded.error(
        "POST", f"/reviews/{item['id']}/complete", expect=400, json=body, key=False
    )
    assert error["code"] == "idempotency_key_required"


# ---------------------------------------------------------------- 练习中的表现对排期的影响


def test_getting_it_wrong_again_in_practice_resets_progress(onboarded, clock):
    item = _mistake(onboarded)
    clock.advance(days=1)
    _, attempt, _ = _retest(onboarded, item, blank("4"))
    _complete(onboarded, item, attempt)  # 第 1 档已通过，下次在 3 天后

    clock.advance(hours=1)
    _, _, result = solve(onboarded, KEY, blank("0"))

    assert result["review_item"]["id"] == item["id"]
    assert result["review_item"]["stage"] == 0
    assert result["review_item"]["due_at"] == "2026-11-12T09:00:00Z", "提前到 1 天后复习"


def test_getting_it_right_in_practice_does_not_skip_the_retest(onboarded, clock):
    item = _mistake(onboarded)

    _, _, result = solve(onboarded, KEY, blank("4"))

    assert result["review_item"] is None
    (kept,) = _reviews(onboarded, scope="all")
    assert (kept["id"], kept["stage"], kept["due_at"]) == (item["id"], 0, item["due_at"])


def test_assisted_correct_answer_schedules_a_retest(onboarded):
    session, attempt = begin(onboarded, "math-mono-quadratic")
    tutor(onboarded, session["id"], "request_hint")

    result = submit(onboarded, attempt["id"], choice("B"))

    assert result["review_item"]["stage"] == 0
    assert result["review_item"]["question_id"] == qid("math-mono-quadratic")


# ---------------------------------------------------------------- 配置与列表


def test_intervals_are_configurable(custom_student, settings, clock):
    _, learner = custom_student(
        settings=settings.model_copy(update={"review_intervals_minutes": "10,20"})
    )

    item = _mistake(learner)

    assert item["due_at"] == "2026-11-10T08:10:00Z"
    assert item["total_stages"] == 2
    clock.advance(minutes=10)
    _, attempt, _ = _retest(learner, item, blank("4"))
    assert _complete(learner, item, attempt)["next_due_at"] == "2026-11-10T08:30:00Z"


def test_due_list_is_ordered_and_paginated(onboarded, clock):
    first = _mistake(onboarded, "math-ineq-min", blank("5"))
    clock.advance(minutes=5)
    second = _mistake(onboarded, "phys-newton2-force", choice("D"))
    clock.advance(minutes=5)
    third = _mistake(onboarded, "chem-lab-operation", choice("B"))
    clock.advance(days=2)

    assert [i["id"] for i in _reviews(onboarded)] == [first["id"], second["id"], third["id"]]
    page = onboarded.data("GET", "/reviews/due", params={"limit": 2})
    assert [i["id"] for i in page["items"]] == [first["id"], second["id"]] and page["next_cursor"]
    rest = onboarded.data("GET", "/reviews/due", params={"limit": 2, "cursor": page["next_cursor"]})
    assert [i["id"] for i in rest["items"]] == [third["id"]] and rest["next_cursor"] is None


@pytest.mark.parametrize("params", [{"scope": "overdue"}, {"limit": 0}, {"limit": 99}])
def test_invalid_review_list_parameters_are_422(onboarded, params):
    onboarded.error("GET", "/reviews/due", expect=422, params=params)


def test_invalid_review_cursor_is_400(onboarded):
    assert (
        onboarded.error("GET", "/reviews/due", expect=400, params={"cursor": "???"})["code"]
        == "invalid_cursor"
    )
