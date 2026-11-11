"""教学编排（docs/06、docs/03 P04）。

样题里 math-mono-quadratic 带审核过的"换种讲法"、快速解法和图解；
math-mono-quadratic-v1 没有"换种讲法"（走模型网关）；phys-newton2-force 没有快速解法和图解。
"""

from __future__ import annotations

import json
import uuid

import pytest
import yaml
from sqlalchemy import delete, func, select, update

from support.flows import (
    begin,
    blank,
    choice,
    events,
    new_attempt,
    session_of,
    solve,
    start,
    submit,
    tutor,
    tutor_error,
)
from support.gateway_fakes import EXAMPLE_ROUTES_PATH, ScriptedProvider, hint_ok, unavailable
from support.seeds import qid
from tutor_api.services.content_seed import load_seed

SEED = {q["key"]: q for q in load_seed().questions}
RICH = "math-mono-quadratic"  # 有审核过的换种讲法、快速解法、图解、变式
NO_REPHRASE = "math-mono-quadratic-v1"
PLAIN = "phys-newton2-force"  # 没有快速解法、没有图解


def _only(step: dict) -> dict:
    (event,) = step["events"]
    return event


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- 分层提示（US-04）


def test_hints_are_revealed_one_level_at_a_time(onboarded):
    session, _ = begin(onboarded, RICH)
    seed_hints = SEED[RICH]["teaching"]["hints"]

    for level in (1, 2, 3):
        step = tutor(onboarded, session["id"], "request_hint")
        event = _only(step)

        assert (event["type"], event["state_after"]) == ("hint", "HINTED")
        assert event["payload"] == {
            "level": level,
            "total_levels": 3,
            "style": "layered",
            "text": seed_hints[level - 1],
            "concept": "函数的单调性",
        }
        assert event["meta"]["source"] == "reviewed_content"
        assert event["meta"]["provider"] is None
        assert step["session"]["hint_level_revealed"] == level
        assert step["session"]["state"] == "HINTED"
        assert step["session"]["assisted"] is True
        assert step["session"]["used_solution"] is False


def test_when_hints_run_out_there_is_a_notice_not_more_content(onboarded):
    session, _ = begin(onboarded, RICH)
    for _ in range(3):
        tutor(onboarded, session["id"], "request_hint")

    step = tutor(onboarded, session["id"], "request_hint")

    event = _only(step)
    assert (event["type"], event["payload"]["code"]) == ("notice", "hints_exhausted")
    assert step["session"]["hint_level_revealed"] == 3
    assert step["session"]["state"] == "HINTED"


def test_a_hint_before_submitting_makes_the_attempt_assisted(onboarded):
    session, attempt = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "request_hint")

    result = submit(onboarded, attempt["id"], choice("B"))

    assert result["evaluation"]["is_correct"] is True
    assert result["evaluation"]["independent"] is False
    assert result["evaluation"]["assisted"] is True
    assert result["evaluation"]["used_solution"] is False
    assert result["review_item"] is not None, "在提示下答对，需要之后无提示复测"


def test_hints_remain_available_after_submission(onboarded):
    session, _, _ = solve(onboarded, RICH, choice("A"))

    event = _only(tutor(onboarded, session["id"], "request_hint"))

    assert (event["type"], event["payload"]["level"]) == ("hint", 1)


def test_repeating_a_hint_request_with_the_same_key_does_not_advance(onboarded, db):
    from tutor_api.models import TutorEventRow

    session, _ = begin(onboarded, RICH)
    path = f"/tutor/sessions/{session['id']}/next"
    key = f"hint-{uuid.uuid4()}"

    first = onboarded.post(path, json={"action": "request_hint"}, key=key)
    second = onboarded.post(path, json={"action": "request_hint"}, key=key)

    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert session_of(onboarded, session["id"])["hint_level_revealed"] == 1
    assert _count(db, TutorEventRow) == 1


# ---------------------------------------------------------------- 解析（P04 验收：未完成独立答题前不自动泄露）


@pytest.mark.parametrize("action", ["request_standard", "request_fast"])
def test_solution_is_not_revealed_before_submission_without_confirmation(onboarded, db, action):
    from tutor_api.models import TutorEventRow

    session, _ = begin(onboarded, RICH)

    error = tutor_error(onboarded, session["id"], action, expect=409)

    assert error["code"] == "independent_attempt_in_progress"
    refreshed = session_of(onboarded, session["id"])
    assert refreshed["used_solution"] is False and refreshed["assisted"] is False
    assert refreshed["state"] == "INDEPENDENT_ATTEMPT"
    assert _count(db, TutorEventRow) == 0


def test_explicitly_ending_independent_attempt_reveals_the_solution_and_records_it(onboarded):
    session, attempt = begin(onboarded, RICH)
    seed = SEED[RICH]["solutions"]["standard"]

    step = tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)

    event = _only(step)
    assert (event["type"], event["state_after"]) == ("standard", "STANDARD")
    assert [s["text"] for s in event["payload"]["steps"]] == seed["steps"]
    assert event["payload"]["final_answer"] == "B"
    assert event["payload"]["key_points"] == seed["key_points"]
    verdicts = {o["key"]: o["verdict"] for o in event["payload"]["option_analysis"]}
    assert verdicts == {"A": "wrong", "B": "correct", "C": "wrong", "D": "wrong"}
    assert event["meta"]["source"] == "reviewed_content"
    assert step["session"]["used_solution"] is True
    assert step["session"]["independent_ended"] is True
    assert step["session"]["assisted"] is True

    result = submit(onboarded, attempt["id"], choice("B"))
    assert result["evaluation"]["independent"] is False
    assert result["evaluation"]["used_solution"] is True
    assert result["attempt"]["used_solution"] is True


def test_solution_after_submission_needs_no_confirmation(onboarded):
    session, _, _ = solve(onboarded, RICH, choice("A"))

    step = tutor(onboarded, session["id"], "request_standard")

    assert _only(step)["type"] == "standard"
    assert step["session"]["used_solution"] is True
    assert step["session"]["independent_ended"] is False, "已经提交过，不算提前结束独立作答"


def test_standard_solution_of_a_fill_question_has_no_option_analysis(onboarded):
    session, _, _ = solve(onboarded, "math-ineq-min", blank("5"))

    payload = _only(tutor(onboarded, session["id"], "request_standard"))["payload"]

    assert payload["option_analysis"] == []
    assert payload["final_answer"] == "$4$"


def test_fast_solution_carries_conditions_and_boundary(onboarded):
    session, _, _ = solve(onboarded, RICH, choice("A"))
    seed = SEED[RICH]["solutions"]["fast"]

    step = tutor(onboarded, session["id"], "request_fast")

    event = _only(step)
    assert (event["type"], event["state_after"]) == ("fast", "FAST")
    assert event["payload"]["conditions"] == seed["conditions"]
    assert event["payload"]["boundary"] == seed["boundary"]
    assert event["payload"]["reviewed"] is True
    assert [s["text"] for s in event["payload"]["steps"]] == seed["steps"]
    assert step["session"]["used_solution"] is True


def test_fast_solution_with_confirmation_before_submission(onboarded):
    session, _ = begin(onboarded, RICH)

    step = tutor(onboarded, session["id"], "request_fast", confirm_end_independent=True)

    assert _only(step)["type"] == "fast"
    assert step["session"]["independent_ended"] is True


def test_question_without_reviewed_fast_solution_says_so_instead_of_inventing_one(onboarded):
    session, _ = begin(onboarded, PLAIN)

    step = tutor(onboarded, session["id"], "request_fast")

    event = _only(step)
    assert (event["type"], event["payload"]["code"]) == ("notice", "fast_not_applicable")
    assert step["session"]["used_solution"] is False and step["session"]["assisted"] is False
    assert step["session"]["state"] == "INDEPENDENT_ATTEMPT"


def test_unreviewed_fast_solution_is_treated_as_missing(onboarded, db):
    from tutor_api.models import Solution

    db.execute(
        update(Solution)
        .where(Solution.question_id == qid(RICH), Solution.kind == "fast")
        .values(reviewed=False)
    )
    db.commit()
    session, _, _ = solve(onboarded, RICH, choice("A"))

    event = _only(tutor(onboarded, session["id"], "request_fast"))

    assert (event["type"], event["payload"]["code"]) == ("notice", "fast_not_applicable")


def test_missing_reviewed_solution_falls_back_honestly(onboarded, db):
    """没有审核解析、也没有可靠模型时，如实说明，不编造解析。"""
    from tutor_api.models import Solution

    db.execute(delete(Solution).where(Solution.question_id == qid(PLAIN)))
    db.commit()
    session, _, _ = solve(onboarded, PLAIN, choice("A"))

    step = tutor(onboarded, session["id"], "request_standard")

    event = _only(step)
    assert (event["type"], event["state_after"]) == ("fallback", "FALLBACK")
    assert event["payload"]["reason_code"] == "MODEL_UNAVAILABLE"
    assert event["meta"]["degraded"] is True
    assert step["session"]["used_solution"] is False
    assert step["session"]["state"] == "FALLBACK"


# ---------------------------------------------------------------- 图解


def test_visual_event_uses_a_whitelisted_template_with_complete_params(onboarded):
    session, _ = begin(onboarded, RICH)

    step = tutor(onboarded, session["id"], "request_visual")

    event = _only(step)
    assert (event["type"], event["state_after"]) == ("visual", "VISUAL")
    assert event["payload"]["template_id"] == "quadratic_graph"
    assert event["payload"]["params"] == {"a": 1, "b": -2, "c": -3}
    assert event["payload"]["caption"] == SEED[RICH]["teaching"]["visual"]["caption"]
    assert event["payload"]["static_fallback"], "必须带静态后备说明"
    assert step["session"]["assisted"] is True
    assert step["session"]["used_solution"] is False


def test_visual_params_are_completed_from_the_registry(onboarded):
    session, _ = begin(onboarded, "math-mono-judge")

    payload = _only(tutor(onboarded, session["id"], "request_visual"))["payload"]

    assert payload["template_id"] == "number_line"
    assert set(payload["params"]) == {
        "min",
        "max",
        "left",
        "right",
        "left_closed",
        "right_closed",
        "left_unbounded",
        "right_unbounded",
    }


def test_question_without_visual_gets_a_notice(onboarded):
    session, _ = begin(onboarded, PLAIN)

    step = tutor(onboarded, session["id"], "request_visual")

    assert (_only(step)["type"], _only(step)["payload"]["code"]) == (
        "notice",
        "visual_not_available",
    )
    assert step["session"]["assisted"] is False


@pytest.mark.parametrize(
    "visual",
    [
        {"template_id": "free_canvas", "params": {}, "caption": "x"},
        {"template_id": "quadratic_graph", "params": {"a": 99}, "caption": "x"},
        {"template_id": "quadratic_graph", "params": {"a": 1, "script": 1}, "caption": "x"},
    ],
    ids=["unregistered-template", "out-of-range", "unknown-param"],
)
def test_visual_that_fails_the_whitelist_is_never_sent(onboarded, db, visual):
    from tutor_api.models import QuestionVersion

    row = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == qid(RICH)))
    row.teaching_json = {**row.teaching_json, "visual": visual}
    db.commit()
    session, _ = begin(onboarded, RICH)

    event = _only(tutor(onboarded, session["id"], "request_visual"))

    assert (event["type"], event["payload"]["code"]) == ("notice", "visual_not_available")
    assert onboarded.data("GET", f"/questions/{qid(RICH)}")["assists"]["visual_available"] is False


def test_looking_at_the_visual_before_submitting_counts_as_assistance(onboarded):
    session, attempt = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "request_visual")

    result = submit(onboarded, attempt["id"], choice("B"))

    assert result["evaluation"]["independent"] is False


# ---------------------------------------------------------------- "没懂"的三级回退（docs/06 §4）


def test_first_confused_uses_the_reviewed_rephrase_when_there_is_one(onboarded, db):
    from tutor_api.models import ModelCallAudit

    session, _ = begin(onboarded, RICH)

    step = tutor(onboarded, session["id"], "mark_confused")

    event = _only(step)
    assert (event["type"], event["payload"]["style"]) == ("hint", "rephrase")
    assert event["payload"]["text"] == SEED[RICH]["teaching"]["concept_rephrase"]
    assert event["meta"]["source"] == "reviewed_content"
    assert step["session"]["confused_streak"] == 1
    assert step["session"]["assisted"] is True
    assert _count(db, ModelCallAudit) == 0, "有审核内容时不调用模型"


def test_first_confused_without_reviewed_rephrase_goes_through_the_gateway(onboarded, db):
    from tutor_api.models import ModelBudgetUsage, ModelCallAudit

    session, _ = begin(onboarded, NO_REPHRASE)

    step = tutor(onboarded, session["id"], "mark_confused")

    event = _only(step)
    assert (event["type"], event["payload"]["style"], event["state_after"]) == (
        "hint",
        "rephrase",
        "HINTED",
    )
    assert event["payload"]["concept"] == "函数的单调性"
    meta = event["meta"]
    assert (meta["source"], meta["provider"], meta["model_id"]) == ("model", "mock", "mock-tutor")
    assert meta["prompt_version"] and meta["trace_id"]
    assert meta["degraded"] is False
    assert step["session"]["assisted"] is True

    (audit,) = db.scalars(select(ModelCallAudit)).all()
    assert (audit.task_type, audit.provider, audit.status) == ("tutor_explain", "mock", "ok")
    assert audit.trace_id == meta["trace_id"] and audit.request_id == meta["request_id"]
    assert audit.student_pseudonym != onboarded.user_id, "审计里只能出现去标识化 ID"
    assert onboarded.user_id not in audit.student_pseudonym

    usage = {row.scope: row.request_count for row in db.scalars(select(ModelBudgetUsage))}
    assert usage == {"student": 1, "platform": 1}


def test_second_confused_checks_prerequisites_and_recommends_the_visual(onboarded):
    session, _ = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "mark_confused")

    step = tutor(onboarded, session["id"], "mark_confused")

    event = _only(step)
    assert event["type"] == "ask"
    by_action = {s["action"]: s for s in event["payload"]["suggestions"]}
    assert "request_visual" in by_action
    assert "函数的概念与定义域" in by_action["review_prerequisite"]["label"]
    assert by_action["review_prerequisite"]["knowledge_id"]
    assert step["session"]["confused_streak"] == 2
    assert step["session"]["needs_human_help"] is False


def test_third_confused_suggests_a_pause_and_stops_repeating(onboarded, db):
    from tutor_api.models import TutorEventRow

    session, _ = begin(onboarded, RICH)
    for _ in range(2):
        tutor(onboarded, session["id"], "mark_confused")

    third = tutor(onboarded, session["id"], "mark_confused")

    assert (_only(third)["type"], _only(third)["payload"]["code"]) == ("notice", "needs_human_help")
    assert third["session"]["needs_human_help"] is True
    recorded = _count(db, TutorEventRow)

    for _ in range(3):
        again = tutor(onboarded, session["id"], "mark_confused")
        assert again["events"] == [], "不再无限重复生成内容"
    assert _count(db, TutorEventRow) == recorded
    assert session_of(onboarded, session["id"])["needs_human_help"] is True


def test_understood_resets_the_confusion_streak(onboarded):
    session, _ = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "mark_confused")

    step = tutor(onboarded, session["id"], "mark_understood")

    assert step["session"]["confused_streak"] == 0
    assert tutor(onboarded, session["id"], "mark_confused")["session"]["confused_streak"] == 1


def test_a_correct_answer_resets_the_confusion_streak(onboarded):
    session, attempt = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "mark_confused")

    result = submit(onboarded, attempt["id"], choice("B"))

    assert result["session"]["confused_streak"] == 0


# ---------------------------------------------------------------- 模型不可用与输出被拒（docs/06 §2、docs/10）


def _confuse_with_adapter(custom_student, adapter):
    app, learner = custom_student(gateway_adapters={"mock": adapter})
    session, _ = begin(learner, NO_REPHRASE)
    return app, learner, session, tutor(learner, session["id"], "mark_confused")


def test_model_unavailable_gives_a_fallback_event_and_no_fake_content(custom_student):
    from tutor_api.models import ModelCallAudit

    app, _, _, step = _confuse_with_adapter(custom_student, ScriptedProvider(unavailable()))

    event = _only(step)
    assert (event["type"], event["state_after"]) == ("fallback", "FALLBACK")
    assert event["payload"]["reason_code"] == "MODEL_UNAVAILABLE"
    assert event["meta"]["source"] == "rule_engine" and event["meta"]["degraded"] is True
    assert event["meta"]["provider"] is None
    assert "internal detail" not in json.dumps(event, ensure_ascii=False)
    assert step["session"]["state"] == "FALLBACK"
    assert step["session"]["assisted"] is False, "没有给出任何讲解，不算辅助"
    with app.state.session_factory() as db:
        (audit,) = db.scalars(select(ModelCallAudit)).all()
        assert (audit.status, audit.error_code) == ("degraded", "MODEL_UNAVAILABLE")


def test_schema_invalid_model_output_is_never_delivered(custom_student):
    bad = {"event_type": "hint", "payload": {"text": "INVALID-OUTPUT-MARKER", "html": "<b>x</b>"}}
    _, learner, session, step = _confuse_with_adapter(custom_student, ScriptedProvider(bad))

    assert _only(step)["payload"]["reason_code"] == "SCHEMA_INVALID"
    assert "INVALID-OUTPUT-MARKER" not in json.dumps(
        events(learner, session["id"]), ensure_ascii=False
    )


def test_model_output_that_leaks_the_answer_is_blocked(custom_student):
    leaking = ScriptedProvider(hint_ok("递增区间就是 (-∞,2]，记住就行。"))
    _, learner, session, step = _confuse_with_adapter(custom_student, leaking)

    assert _only(step)["payload"]["reason_code"] == "CONTENT_BLOCKED"
    assert "记住就行" not in json.dumps(events(learner, session["id"]), ensure_ascii=False)


def test_student_can_keep_going_after_a_fallback(custom_student):
    _, learner, session, _ = _confuse_with_adapter(custom_student, ScriptedProvider(unavailable()))

    step = tutor(learner, session["id"], "request_hint")

    assert _only(step)["type"] == "hint"
    assert step["session"]["state"] == "HINTED"


def test_exhausted_model_budget_degrades_to_fallback(custom_student, settings, tmp_path):
    routes = yaml.safe_load(EXAMPLE_ROUTES_PATH.read_text(encoding="utf-8"))
    routes["budgets"]["student_daily_requests"] = 1
    path = tmp_path / "routes.yaml"
    path.write_text(yaml.safe_dump(routes, allow_unicode=True), encoding="utf-8")
    _, learner = custom_student(settings=settings.model_copy(update={"model_routes_path": path}))

    first, _ = begin(learner, NO_REPHRASE)
    second, _ = begin(learner, "math-ineq-rect")
    served = _only(tutor(learner, first["id"], "mark_confused"))
    over = _only(tutor(learner, second["id"], "mark_confused"))

    assert served["meta"]["source"] == "model"
    assert (over["type"], over["payload"]["reason_code"]) == ("fallback", "BUDGET_EXCEEDED")


# ---------------------------------------------------------------- 复测会话：提交前不给任何辅助


def _due_retest(student, clock, key="math-ineq-min", wrong=None):
    _, _, result = solve(student, key, wrong or blank("5"))
    clock.advance(days=1)
    return begin(student, key, origin="review", review_item_id=result["review_item"]["id"])


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("request_hint", {}),
        ("request_standard", {"confirm_end_independent": True}),
        ("request_fast", {"confirm_end_independent": True}),
        ("request_visual", {}),
        ("mark_confused", {}),
    ],
)
def test_retest_session_gives_no_assistance_before_submission(onboarded, clock, action, body):
    session, _ = _due_retest(onboarded, clock)

    error = tutor_error(onboarded, session["id"], action, expect=409, **body)

    assert error["code"] == "hints_disabled_in_retest"
    refreshed = session_of(onboarded, session["id"])
    assert refreshed["assisted"] is False and refreshed["used_solution"] is False


def test_retest_session_allows_the_solution_after_submission(onboarded, clock):
    session, attempt = _due_retest(onboarded, clock)
    submit(onboarded, attempt["id"], blank("6"))

    assert _only(tutor(onboarded, session["id"], "request_standard"))["type"] == "standard"


# ---------------------------------------------------------------- "我懂了"：变式、复测安排、结束


def test_understood_before_submitting_just_encourages(onboarded):
    session, _ = begin(onboarded, RICH)

    step = tutor(onboarded, session["id"], "mark_understood")

    assert (_only(step)["type"], _only(step)["payload"]["code"]) == ("notice", "keep_going")
    assert step["session"]["state"] == "INDEPENDENT_ATTEMPT"


def test_understood_after_a_wrong_answer_offers_a_variant_and_announces_the_review(onboarded):
    session, _, result = solve(onboarded, RICH, choice("A"))
    tutor(onboarded, session["id"], "request_standard")

    step = tutor(onboarded, session["id"], "mark_understood")

    offer, review, done = step["events"]
    assert (offer["type"], offer["state_after"]) == ("ask", "VARIANT")
    variant = next(s for s in offer["payload"]["suggestions"] if s["action"] == "start_variant")
    assert variant["question_id"] == qid("math-mono-quadratic-v1")
    assert (review["type"], review["payload"]["code"], review["state_after"]) == (
        "notice",
        "review_scheduled",
        "REVIEW_SCHEDULED",
    )
    assert review["payload"]["due_at"] == result["review_item"]["due_at"]
    assert (done["type"], done["payload"]["code"], done["state_after"]) == (
        "notice",
        "session_completed",
        "DONE",
    )
    assert [e["seq_no"] for e in step["events"]] == [3, 4, 5]
    assert step["session"]["state"] == "DONE"


def test_understood_after_an_independent_correct_answer_just_completes(onboarded):
    session, _, _ = solve(onboarded, "math-ineq-min", blank("4"))

    step = tutor(onboarded, session["id"], "mark_understood")

    event = _only(step)
    assert (event["payload"]["code"], event["state_after"]) == ("session_completed", "DONE")
    assert step["session"]["state"] == "DONE"


def test_variant_already_attempted_is_not_offered_again(onboarded):
    solve(onboarded, "math-mono-quadratic-v1", origin="variant")
    session, _, _ = solve(onboarded, RICH, choice("B"))

    step = tutor(onboarded, session["id"], "mark_understood")

    assert [e["type"] for e in step["events"]] == ["notice"]


def test_variant_session_can_link_back_to_its_parent(onboarded):
    parent, _, _ = solve(onboarded, RICH, choice("B"))

    variant = start(
        onboarded, "math-mono-quadratic-v1", origin="variant", parent_session_id=parent["id"]
    )

    assert variant["parent_session_id"] == parent["id"]
    body = {
        "question_id": qid("math-mono-quadratic-v1"),
        "origin": "variant",
        "parent_session_id": str(uuid.uuid4()),
    }
    onboarded.error("POST", "/sessions", expect=404, json=body)


def test_finished_session_accepts_no_further_actions(onboarded):
    session, _, _ = solve(onboarded, "math-ineq-min", blank("4"))
    tutor(onboarded, session["id"], "mark_understood")

    for action in (
        "request_hint",
        "request_standard",
        "request_visual",
        "mark_confused",
        "mark_understood",
    ):
        assert tutor_error(onboarded, session["id"], action, expect=409)["code"] == "invalid_state"
    error = onboarded.error("POST", "/attempts", expect=409, json={"session_id": session["id"]})
    assert error["code"] == "invalid_state"


# ---------------------------------------------------------------- 事件恢复与请求校验


def test_events_can_be_restored_in_order(onboarded):
    session, attempt = begin(onboarded, RICH)
    tutor(onboarded, session["id"], "request_hint")
    tutor(onboarded, session["id"], "request_visual")
    submit(onboarded, attempt["id"], choice("A"))
    tutor(onboarded, session["id"], "request_standard")

    everything = events(onboarded, session["id"])

    assert [e["seq_no"] for e in everything] == [1, 2, 3, 4]
    assert [e["type"] for e in everything] == ["hint", "visual", "diagnosis", "standard"]
    assert [e["state_after"] for e in everything] == ["HINTED", "VISUAL", "DIAGNOSED", "STANDARD"]
    assert [e["seq_no"] for e in events(onboarded, session["id"], after_seq=2)] == [3, 4]
    assert [e["seq_no"] for e in events(onboarded, session["id"], after_seq=1, limit=1)] == [2]
    page = onboarded.data("GET", f"/sessions/{session['id']}/events", params={"after_seq": 4})
    assert page == {"items": [], "last_seq": 4}


def test_event_metadata_is_traceable_to_the_request(onboarded):
    session, _ = begin(onboarded, RICH)

    response = onboarded.post(
        f"/tutor/sessions/{session['id']}/next",
        json={"action": "request_hint"},
        headers={"X-Request-Id": "req-trace-1"},
    )

    meta = response.json()["data"]["events"][0]["meta"]
    assert meta["request_id"] == "req-trace-1"
    assert meta["question_id"] == qid(RICH) and meta["question_version"] == 1
    assert meta["schema_version"] == "1.0"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "submit_attempt"},
        {"action": "reveal_everything"},
        {},
        {"action": "request_hint", "level": 3},
        {"action": "request_standard", "confirm_end_independent": "yes please"},
    ],
    ids=["submit-is-its-own-endpoint", "unknown-action", "no-action", "extra-field", "bad-flag"],
)
def test_invalid_tutor_requests_are_422(onboarded, body):
    session, _ = begin(onboarded, RICH)
    onboarded.error("POST", f"/tutor/sessions/{session['id']}/next", expect=422, json=body)


def test_tutor_next_requires_key_and_an_existing_session(onboarded):
    session, _ = begin(onboarded, RICH)
    path = f"/tutor/sessions/{session['id']}/next"

    assert onboarded.error("POST", path, expect=400, json={"action": "request_hint"}, key=False)[
        "code"
    ] == ("idempotency_key_required")
    onboarded.error(
        "POST", f"/tutor/sessions/{uuid.uuid4()}/next", expect=404, json={"action": "request_hint"}
    )
    onboarded.error("GET", f"/sessions/{uuid.uuid4()}/events", expect=404)


def test_retry_after_seeing_the_solution_is_marked_accordingly(onboarded):
    session, _, _ = solve(onboarded, RICH, choice("A"))
    tutor(onboarded, session["id"], "request_standard")
    retry = new_attempt(onboarded, session["id"])

    result = submit(onboarded, retry["id"], choice("B"))

    assert result["evaluation"]["is_correct"] is True
    assert result["evaluation"]["independent"] is False
    assert result["evaluation"]["used_solution"] is True
