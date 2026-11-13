"""会话、作答、草稿与提交（客观题主流程）。`onboarded` 是四川高三学生，时钟为 2026-11-10 08:00 UTC。"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select

from support.flows import CORRECT, WRONG, begin, blank, choice, new_attempt, solve, start, submit
from support.seeds import OBJECTIVE_KEYS, qid

STROKES = {
    "version": 1,
    "pages": [
        {
            "width": 800,
            "height": 1100,
            "strokes": [
                {"color": "#1A1A1A", "width": 2.5, "points": [10, 20, 0, 0.5, 14, 26, 16, 0.6]}
            ],
        }
    ],
}


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- 会话


def test_new_session_starts_ready_with_snapshots(onboarded, clock):
    session = start(onboarded, "math-mono-quadratic")

    assert session["question_id"] == qid("math-mono-quadratic")
    assert session["question_version"] == 1
    assert session["origin"] == "practice"
    assert session["state"] == "READY"
    assert (session["region_code_snapshot"], session["exam_year_snapshot"]) == ("CN-51", 2027)
    assert session["curriculum_version_snapshot"] is None
    assert session["assisted"] is False and session["used_solution"] is False
    assert session["independent_ended"] is False and session["needs_human_help"] is False
    assert (session["hint_level_revealed"], session["hint_levels_total"]) == (0, 3)
    assert session["active_attempt_id"] is None
    assert (session["submitted_attempts"], session["last_event_seq"]) == (0, 0)
    assert session["created_at"] == "2026-11-10T08:00:00Z"
    assert onboarded.data("GET", f"/sessions/{session['id']}") == session


def test_switching_region_does_not_rewrite_existing_sessions(onboarded):
    """docs/09 验收：切换地区后历史会话的归属不变。"""
    before = start(onboarded, "math-ineq-min")

    onboarded.data(
        "PUT", "/profile", json={"region_code": "CN-50", "grade": "G11", "subjects": ["math"]}
    )
    after = start(onboarded, "math-ineq-min")

    kept = onboarded.data("GET", f"/sessions/{before['id']}")
    assert (kept["region_code_snapshot"], kept["exam_year_snapshot"]) == ("CN-51", 2027)
    assert (after["region_code_snapshot"], after["exam_year_snapshot"]) == ("CN-50", 2028)


def test_session_before_onboarding_has_empty_snapshots(student):
    session = start(student, "math-ineq-min")
    assert session["region_code_snapshot"] is None and session["exam_year_snapshot"] is None


def test_session_requires_an_existing_published_question(onboarded, db):
    from sqlalchemy import update

    from tutor_api.models import Question

    body = {"question_id": str(uuid.uuid4()), "origin": "practice"}
    assert onboarded.error("POST", "/sessions", expect=404, json=body)["code"] == "not_found"

    db.execute(
        update(Question).where(Question.id == qid("math-ineq-min")).values(status="withdrawn")
    )
    db.commit()
    body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
    assert onboarded.error("POST", "/sessions", expect=404, json=body)["code"] == "not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"question_id": "not-a-uuid", "origin": "practice"},
        {"question_id": qid("math-ineq-min"), "origin": "homework"},
        {"question_id": qid("math-ineq-min")},
        {
            "question_id": qid("math-ineq-min"),
            "origin": "practice",
            "student_id": str(uuid.uuid4()),
        },
        {"question_id": qid("math-ineq-min"), "origin": "review"},
        {
            "question_id": qid("math-ineq-min"),
            "origin": "practice",
            "review_item_id": str(uuid.uuid4()),
        },
    ],
    ids=[
        "bad-id",
        "bad-origin",
        "no-origin",
        "extra-student-id",
        "review-without-item",
        "item-without-review",
    ],
)
def test_invalid_session_requests_are_422(onboarded, body):
    assert onboarded.error("POST", "/sessions", expect=422, json=body)["code"] == "validation_error"


def test_unknown_session_is_404(onboarded):
    assert onboarded.error("GET", f"/sessions/{uuid.uuid4()}", expect=404)["code"] == "not_found"


# ---------------------------------------------------------------- 作答


def test_first_attempt_enters_independent_attempt(onboarded):
    session = start(onboarded, "math-mono-quadratic")

    attempt = new_attempt(onboarded, session["id"])

    assert attempt["session_id"] == session["id"]
    assert (attempt["attempt_no"], attempt["status"], attempt["draft_revision"]) == (1, "draft", 0)
    assert attempt["answer"] is None and attempt["evaluation"] is None
    assert attempt["independent"] is None and attempt["submitted_at"] is None
    refreshed = onboarded.data("GET", f"/sessions/{session['id']}")
    assert refreshed["state"] == "INDEPENDENT_ATTEMPT"
    assert refreshed["active_attempt_id"] == attempt["id"]
    assert onboarded.data("GET", f"/attempts/{attempt['id']}") == attempt


def test_only_one_open_attempt_per_session(onboarded):
    session, attempt = begin(onboarded, "math-mono-quadratic")

    error = onboarded.error("POST", "/attempts", expect=409, json={"session_id": session["id"]})

    assert error["code"] == "attempt_in_progress"
    assert error["details"] == {"attempt_id": attempt["id"]}


def test_attempt_needs_an_existing_session(onboarded):
    onboarded.error("POST", "/attempts", expect=404, json={"session_id": str(uuid.uuid4())})
    onboarded.error("POST", "/attempts", expect=422, json={"session_id": "nope"})
    onboarded.error("GET", f"/attempts/{uuid.uuid4()}", expect=404)


# ---------------------------------------------------------------- 草稿同步


def test_draft_starts_empty_at_revision_zero(onboarded, clock):
    _, attempt = begin(onboarded, "math-mono-quadratic")

    draft = onboarded.data("GET", f"/attempts/{attempt['id']}/draft")

    assert draft == {
        "attempt_id": attempt["id"],
        "revision": 0,
        "answer": None,
        "strokes": None,
        "updated_at": "2026-11-10T08:00:00Z",
    }


def test_draft_sync_increments_revision_and_persists(onboarded, clock):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    path = f"/attempts/{attempt['id']}/draft"
    clock.advance(seconds=30)

    synced = onboarded.data(
        "PUT", path, json={"base_revision": 0, "answer": choice("A"), "strokes": STROKES}
    )

    assert synced["revision"] == 1
    assert synced["answer"]["selected_options"] == ["A"]
    assert synced["strokes"] == STROKES
    assert synced["updated_at"] == "2026-11-10T08:00:30Z"
    assert onboarded.data("GET", path) == synced
    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["draft_revision"] == 1

    again = onboarded.data(
        "PUT", path, json={"base_revision": 1, "answer": choice("B"), "strokes": STROKES}
    )
    assert again["revision"] == 2


def test_stale_draft_sync_conflicts_without_overwriting(onboarded):
    """docs/02 §5：冲突返回 409，保留双方，不静默覆盖。"""
    _, attempt = begin(onboarded, "math-mono-quadratic")
    path = f"/attempts/{attempt['id']}/draft"
    server = onboarded.data(
        "PUT", path, json={"base_revision": 0, "answer": choice("A"), "strokes": STROKES}
    )

    error = onboarded.error(
        "PUT", path, expect=409, json={"base_revision": 0, "answer": choice("D"), "strokes": None}
    )

    assert error["code"] == "draft_revision_conflict"
    assert error["details"]["server_revision"] == 1
    assert error["details"]["server_draft"] == server
    assert onboarded.data("GET", path) == server, "服务端草稿不应被冲突的请求改动"


def test_draft_sync_replaces_the_whole_document(onboarded):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    path = f"/attempts/{attempt['id']}/draft"
    onboarded.data(
        "PUT", path, json={"base_revision": 0, "answer": choice("A"), "strokes": STROKES}
    )

    cleared = onboarded.data("PUT", path, json={"base_revision": 1})

    assert cleared["revision"] == 2
    assert cleared["answer"] is None and cleared["strokes"] is None


def test_draft_does_not_change_the_session_state_or_assistance_flags(onboarded):
    session, attempt = begin(onboarded, "math-mono-quadratic")
    onboarded.data(
        "PUT", f"/attempts/{attempt['id']}/draft", json={"base_revision": 0, "answer": choice("A")}
    )

    refreshed = onboarded.data("GET", f"/sessions/{session['id']}")

    assert refreshed["state"] == "INDEPENDENT_ATTEMPT"
    assert refreshed["assisted"] is False and refreshed["submitted_attempts"] == 0


@pytest.mark.parametrize(
    "strokes",
    [
        {"version": 2, "pages": []},
        {"version": 1, "pages": [{"width": 0, "height": 100, "strokes": []}]},
        {
            "version": 1,
            "pages": [
                {
                    "width": 100,
                    "height": 100,
                    "strokes": [{"color": "red", "width": 2, "points": []}],
                }
            ],
        },
        {
            "version": 1,
            "pages": [
                {
                    "width": 100,
                    "height": 100,
                    "strokes": [{"color": "#000000", "width": 99, "points": []}],
                }
            ],
        },
        {
            "version": 1,
            "pages": [{"width": 100, "height": 100, "strokes": [], "script": "alert(1)"}],
        },
    ],
    ids=["bad-version", "zero-width-page", "named-colour", "pen-too-wide", "extra-field"],
)
def test_malformed_strokes_are_rejected(onboarded, strokes):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    body = {"base_revision": 0, "strokes": strokes}
    onboarded.error("PUT", f"/attempts/{attempt['id']}/draft", expect=422, json=body)


def test_oversized_draft_is_413(onboarded):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    stroke = {"color": "#000000", "width": 2, "points": [0.5] * 40000}
    body = {
        "base_revision": 0,
        "strokes": {
            "version": 1,
            "pages": [{"width": 800, "height": 1100, "strokes": [stroke] * 16}],
        },
    }
    assert len(json.dumps(body)) > 2_000_000

    error = onboarded.error("PUT", f"/attempts/{attempt['id']}/draft", expect=413, json=body)

    assert error["code"] == "payload_too_large"
    assert onboarded.data("GET", f"/attempts/{attempt['id']}/draft")["revision"] == 0


def test_draft_sync_requires_idempotency_key(onboarded):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    error = onboarded.error(
        "PUT", f"/attempts/{attempt['id']}/draft", expect=400, json={"base_revision": 0}, key=False
    )
    assert error["code"] == "idempotency_key_required"


def test_draft_is_frozen_after_submission(onboarded):
    _, attempt, _ = solve(onboarded, "math-mono-quadratic")

    error = onboarded.error(
        "PUT", f"/attempts/{attempt['id']}/draft", expect=409, json={"base_revision": 0}
    )

    assert error["code"] == "attempt_already_submitted"


# ---------------------------------------------------------------- 提交与判定


def test_correct_first_submission_is_independent(onboarded, clock):
    session, attempt = begin(onboarded, "math-mono-quadratic")
    clock.advance(minutes=3)

    result = submit(onboarded, attempt["id"], choice("B"))

    evaluation = result["evaluation"]
    assert (evaluation["state"], evaluation["outcome"], evaluation["is_correct"]) == (
        "verified",
        "correct",
        True,
    )
    assert evaluation["independent"] is True
    assert evaluation["assisted"] is False and evaluation["used_solution"] is False
    assert evaluation["review_required"] is False
    assert [(f["target"], f["code"]) for f in evaluation["feedback"]] == [("overall", "correct")]
    assert "不是官方" in evaluation["disclaimer"]

    assert result["attempt"]["status"] == "submitted"
    assert result["attempt"]["submitted_at"] == "2026-11-10T08:03:00Z"
    assert result["attempt"]["answer"]["selected_options"] == ["B"]
    assert result["attempt"]["independent"] is True
    assert result["attempt"]["evaluation"] == evaluation
    assert onboarded.data("GET", f"/attempts/{attempt['id']}") == result["attempt"]

    assert result["session"]["state"] == "DIAGNOSED"
    assert result["session"]["submitted_attempts"] == 1
    assert result["session"]["active_attempt_id"] is None
    assert result["session"]["last_event_seq"] == 1
    assert result["review_item"] is None, "独立答对不需要安排复测"

    (event,) = result["events"]
    assert (event["type"], event["seq_no"], event["state_after"]) == ("diagnosis", 1, "DIAGNOSED")
    assert event["payload"]["outcome"] == "correct"
    assert event["meta"]["source"] == "rule_engine" and event["meta"]["degraded"] is False
    assert event["meta"]["question_id"] == qid("math-mono-quadratic")
    assert event["meta"]["question_version"] == 1


def test_wrong_submission_explains_the_choice_and_schedules_a_review(onboarded, clock):
    _, _, result = solve(onboarded, "math-mono-quadratic", choice("A"))

    evaluation = result["evaluation"]
    assert (evaluation["state"], evaluation["outcome"], evaluation["is_correct"]) == (
        "verified",
        "incorrect",
        False,
    )
    assert evaluation["independent"] is True, "第一次无辅助的提交即使答错也是独立作答"
    assert [(f["target"], f["code"]) for f in evaluation["feedback"]] == [("A", "wrong_option")]

    review = result["review_item"]
    assert review["question_id"] == qid("math-mono-quadratic")
    assert (review["status"], review["stage"], review["total_stages"]) == ("scheduled", 0, 3)
    assert review["due_at"] == "2026-11-11T08:00:00Z", "默认 T+1 天"
    assert review["is_due"] is False and review["last_result"] is None

    (event,) = result["events"]
    assert event["payload"]["outcome"] == "incorrect"
    actions = [s["action"] for s in event["payload"]["suggestions"]]
    assert "retry_attempt" in actions and "request_hint" in actions


def test_submission_response_does_not_leak_the_solution(onboarded):
    _, _, result = solve(onboarded, "math-mono-quadratic", choice("A"))

    text = json.dumps(result, ensure_ascii=False)
    assert "配方" not in text, "常规解法的步骤不应出现在提交结果里"
    assert "对称轴为 $x=1$，开口向上" not in text, "正确选项的分析不应出现"
    assert "final_answer" not in text


@pytest.mark.parametrize("key", sorted(OBJECTIVE_KEYS))
def test_every_sample_question_is_gradable_both_ways(onboarded, key):
    _, _, right = solve(onboarded, key, CORRECT[key])
    _, _, wrong = solve(onboarded, key, WRONG[key])

    assert (right["evaluation"]["state"], right["evaluation"]["is_correct"]) == (
        "verified",
        True,
    ), key
    assert (wrong["evaluation"]["state"], wrong["evaluation"]["is_correct"]) == (
        "verified",
        False,
    ), key
    assert right["review_item"] is None and wrong["review_item"] is not None


def test_partially_correct_multiple_choice(onboarded):
    _, _, result = solve(onboarded, "math-mono-judge", choice("A"))

    evaluation = result["evaluation"]
    assert (evaluation["outcome"], evaluation["is_correct"]) == ("partially_correct", False)
    assert [(f["target"], f["code"]) for f in evaluation["feedback"]] == [
        ("overall", "missed_options")
    ]
    assert result["review_item"] is not None


def test_missing_unit_gets_a_specific_reason(onboarded):
    _, _, result = solve(onboarded, "phys-incline-accel", blank("5"))

    assert result["evaluation"]["outcome"] == "incorrect"
    assert [(f["target"], f["code"]) for f in result["evaluation"]["feedback"]] == [
        ("b1", "unit_missing")
    ]


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("math-ineq-min", "四"),
        ("phys-incline-accel", "500 cm/s²"),
        ("phys-incline-accel-v1", "g sinα"),
        ("math-mono-quadratic-v1", "x≤2"),
    ],
)
def test_answer_that_cannot_be_verified_is_never_silently_judged(onboarded, db, key, raw):
    """US-05：判不出来就明确标成待确认，不算对也不算错，也不据此安排复测。"""
    from tutor_api.models import ReviewItem

    _, _, result = solve(onboarded, key, blank(raw))

    evaluation = result["evaluation"]
    assert (evaluation["state"], evaluation["outcome"], evaluation["is_correct"]) == (
        "uncertain",
        "undetermined",
        None,
    )
    assert evaluation["review_required"] is True
    assert "待确认" in evaluation["message"]
    assert result["attempt"]["evaluation"]["is_correct"] is None
    assert result["review_item"] is None and _count(db, ReviewItem) == 0

    (event,) = result["events"]
    assert event["type"] == "uncertainty"
    assert event["payload"]["review_required"] is True
    assert result["session"]["state"] == "DIAGNOSED"


@pytest.mark.parametrize(
    ("key", "answer"),
    [
        ("math-mono-quadratic", choice("A", "B")),
        ("math-mono-quadratic", choice("Z")),
        ("math-mono-quadratic", choice()),
        ("math-mono-quadratic", blank("B")),
        ("math-mono-quadratic", {}),
        ("math-ineq-min", choice("A")),
        ("math-ineq-min", blank("4", key="zz")),
        ("math-ineq-min", blank("   ")),
        ("math-ineq-min", {"blanks": [{"key": "b1", "value": "4"}, {"key": "b1", "value": "5"}]}),
    ],
    ids=[
        "two-for-single",
        "unknown-option",
        "nothing-selected",
        "blank-for-choice",
        "empty",
        "choice-for-fill",
        "unknown-blank",
        "whitespace",
        "duplicate-blank",
    ],
)
def test_answer_of_the_wrong_shape_is_422_and_attempt_stays_open(onboarded, key, answer):
    session, attempt = begin(onboarded, key)

    error = onboarded.error(
        "POST", f"/attempts/{attempt['id']}/submit", expect=422, json={"answer": answer}
    )

    assert error["code"] == "validation_error"
    assert onboarded.data("GET", f"/attempts/{attempt['id']}")["status"] == "draft"
    assert onboarded.data("GET", f"/sessions/{session['id']}")["submitted_attempts"] == 0


def test_submit_requires_idempotency_key_and_an_existing_attempt(onboarded):
    _, attempt = begin(onboarded, "math-ineq-min")
    path = f"/attempts/{attempt['id']}/submit"

    assert onboarded.error("POST", path, expect=400, json={"answer": blank("4")}, key=False)[
        "code"
    ] == ("idempotency_key_required")
    onboarded.error(
        "POST", f"/attempts/{uuid.uuid4()}/submit", expect=404, json={"answer": blank("4")}
    )


# ---------------------------------------------------------------- 重复提交（US-03）


def test_repeating_a_submission_with_the_same_key_evaluates_only_once(onboarded, db):
    from tutor_api.models import Attempt, ReviewItem, TutorEventRow

    _, attempt = begin(onboarded, "math-mono-quadratic")
    path = f"/attempts/{attempt['id']}/submit"
    key = f"submit-{uuid.uuid4()}"

    first = onboarded.post(path, json={"answer": choice("A")}, key=key)
    second = onboarded.post(path, json={"answer": choice("A")}, key=key)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert _count(db, Attempt) == 1
    assert _count(db, TutorEventRow) == 1
    assert _count(db, ReviewItem) == 1


def test_resubmitting_a_submitted_attempt_with_a_new_key_is_409(onboarded):
    _, attempt, _ = solve(onboarded, "math-mono-quadratic", choice("A"))

    error = onboarded.error(
        "POST", f"/attempts/{attempt['id']}/submit", expect=409, json={"answer": choice("B")}
    )

    assert error["code"] == "attempt_already_submitted"
    kept = onboarded.data("GET", f"/attempts/{attempt['id']}")
    assert kept["answer"]["selected_options"] == ["A"], "已提交的答案不能被改写"
    assert kept["evaluation"]["is_correct"] is False


def test_same_key_with_a_different_answer_is_a_conflict(onboarded):
    _, attempt = begin(onboarded, "math-mono-quadratic")
    path = f"/attempts/{attempt['id']}/submit"
    key = f"submit-{uuid.uuid4()}"
    onboarded.post(path, json={"answer": choice("A")}, key=key)

    error = onboarded.error("POST", path, expect=409, json={"answer": choice("B")}, key=key)

    assert error["code"] == "idempotency_key_conflict"


# ---------------------------------------------------------------- 独立与辅助


def test_retry_in_the_same_session_is_never_independent(onboarded):
    session, _, first = solve(onboarded, "math-mono-quadratic", choice("A"))
    assert first["evaluation"]["independent"] is True

    retry = new_attempt(onboarded, session["id"])
    second = submit(onboarded, retry["id"], choice("B"))

    assert retry["attempt_no"] == 2
    evaluation = second["evaluation"]
    assert evaluation["is_correct"] is True
    assert evaluation["independent"] is False and evaluation["assisted"] is True
    assert second["session"]["submitted_attempts"] == 2
    assert second["review_item"] is not None, "看过错因反馈后才答对，仍需要复测来确认"
    assert second["review_item"]["id"] == first["review_item"]["id"]


def test_wrong_answer_twice_keeps_a_single_review_item(onboarded, db):
    from tutor_api.models import ReviewItem

    session, _, _ = solve(onboarded, "math-mono-quadratic", choice("A"))
    retry = new_attempt(onboarded, session["id"])
    submit(onboarded, retry["id"], choice("C"))
    solve(onboarded, "math-mono-quadratic", choice("D"))

    assert _count(db, ReviewItem) == 1


def test_elapsed_time_is_optional_and_validated(onboarded):
    _, attempt = begin(onboarded, "math-ineq-min")
    path = f"/attempts/{attempt['id']}/submit"

    onboarded.error("POST", path, expect=422, json={"answer": blank("4"), "elapsed_ms": -5})
    result = onboarded.data("POST", path, json={"answer": blank("4"), "elapsed_ms": 42000})

    assert result["evaluation"]["is_correct"] is True
