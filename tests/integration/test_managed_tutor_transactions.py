"""PROD302-A acceptance, prepared before implementation. Real isolated MySQL/Redis."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import build, dependencies  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from support.api import LOOPBACK, ApiClient
from tutor_api.idempotency import key_digest
from tutor_api.models import (
    IdempotencyReceipt,
    KnowledgeNode,
    ModelBudgetUsage,
    ModelCallAudit,
    StudySession,
    TutorEventRow,
)


@pytest.fixture
def tutor_case(request, monkeypatch):
    values = request.getfixturevalue("dependencies")
    _, factory, tokens, _, _, _, _ = values
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    with factory() as db:
        for code in payload["question"]["knowledge"]:
            db.add(
                KnowledgeNode(
                    id=str(uuid4()),
                    subject=payload["subject"],
                    code=code,
                    title="Self authored fixture",
                    created_at=datetime.now(UTC),
                )
            )
        db.commit()
    app = build(values)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("gateway")
        raise AssertionError("managed reviewed/rule transaction must never call a gateway")

    monkeypatch.setattr(app.state.gateway, "invoke", forbidden)
    with TestClient(app, client=LOOPBACK) as raw:
        author = ApiClient(raw, "reviewer", tokens["reviewer"])
        reviewer = ApiClient(raw, "reviewer2", tokens["reviewer2"])
        student = ApiClient(raw, "student", tokens["student"])
        created = author.data("POST", "/admin/question-imports", expect=201, json=payload)
        identifier = created["id"]
        reviewer.data(
            "POST",
            f"/admin/questions/{identifier}/review",
            json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
        )
        reviewer.data(
            "POST",
            f"/admin/questions/{identifier}/review",
            json={"expected_review_revision": (1) + 1, "expected_version": 1, "decision": "publish"},
        )
        session = student.data(
            "POST", "/sessions", expect=201, json={"question_id": identifier, "origin": "practice"}
        )
        yield {
            "raw": raw,
            "author": author,
            "reviewer": reviewer,
            "student": student,
            "factory": factory,
            "tokens": tokens,
            "session": session,
            "question": identifier,
            "payload": payload,
            "app": app,
            "calls": calls,
        }


def next_step(case, action, *, key=None, **extra):
    return case["student"].data(
        "POST",
        f"/tutor/sessions/{case['session']['id']}/next",
        json={"action": action, **extra},
        key=key,
    )


def test_managed_reviewed_hint_and_replay_are_one_transaction(tutor_case):
    case = tutor_case
    first = next_step(case, "request_hint", key="managed-next-replay")
    assert next_step(case, "request_hint", key="managed-next-replay") == first
    assert first["events"][0]["type"] == "hint"
    assert (
        first["events"][0]["payload"]["text"] == case["payload"]["question"]["teaching"]["hints"][0]
    )
    assert first["session"]["hint_level_revealed"] == 1
    assert case["calls"] == []
    with case["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(ModelCallAudit)) == 0
        assert db.scalar(select(func.count()).select_from(ModelBudgetUsage)) == 0


def test_managed_reviewed_rephrase_and_unavailable_model_are_honest(tutor_case):
    case = tutor_case
    reviewed = next_step(case, "mark_confused")
    assert reviewed["events"][0]["type"] == "hint"
    assert reviewed["events"][0]["meta"]["source"] == "reviewed_content"
    # Publish a distinct self-authored question without reviewed rephrase copy;
    # published versions remain immutable, including in this fixture.
    payload = json.loads(json.dumps(case["payload"]))
    payload["question"]["teaching"]["concept_rephrase"] = None
    created = case["author"].data("POST", "/admin/question-imports", expect=201, json=payload)
    identifier = created["id"]
    for decision in ("approve", "publish"):
        case["reviewer"].data(
            "POST",
            f"/admin/questions/{identifier}/review",
            json={"expected_review_revision": 1 if decision == "approve" else 2, "expected_version": 1, "decision": decision},
        )
    session = case["student"].data(
        "POST", "/sessions", expect=201, json={"question_id": identifier, "origin": "practice"}
    )
    case = {**case, "session": session}
    fallback = next_step(case, "mark_confused")
    event = fallback["events"][0]
    assert event["type"] == "fallback"
    assert event["meta"]["source"] == "rule_engine" and event["meta"]["degraded"] is True
    assert event["meta"]["provider"] is None and event["meta"]["model_id"] is None
    assert event["meta"]["trace_id"] is None and case["calls"] == []


def test_managed_next_keeps_role_owner_and_solution_confirmation(tutor_case):
    case = tutor_case
    path = f"/tutor/sessions/{case['session']['id']}/next"
    ApiClient(case["raw"], "parent", case["tokens"]["parent"]).error(
        "POST", path, expect=403, json={"action": "request_hint"}
    )
    ApiClient(case["raw"], "other", case["tokens"]["other"]).error(
        "POST", path, expect=404, json={"action": "request_hint"}
    )
    denied = case["student"].error("POST", path, expect=409, json={"action": "request_standard"})
    assert denied["code"] == "independent_attempt_in_progress"
    solution = next_step(case, "request_standard", confirm_end_independent=True)
    assert solution["session"]["used_solution"] is True
    assert solution["session"]["independent_ended"] is True
    assert solution["events"][0]["type"] == "standard"


@pytest.mark.parametrize("same_key", [True, False])
def test_managed_concurrent_next_replays_or_serializes_levels(tutor_case, same_key):
    case = tutor_case
    start = Event()

    def invoke(index):
        assert start.wait(3)
        return next_step(
            case,
            "request_hint",
            key="concurrent-next-same" if same_key else f"concurrent-next-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, index) for index in range(2)]
        start.set()
        results = [future.result(timeout=10) for future in futures]
    if same_key:
        assert results[0] == results[1]
    else:
        assert sorted(result["session"]["hint_level_revealed"] for result in results) == [1, 2]
        assert len({result["events"][0]["seq_no"] for result in results}) == 2
    with case["factory"]() as db:
        assert db.get(StudySession, case["session"]["id"]).hint_level_revealed == (
            1 if same_key else 2
        )
    assert case["calls"] == []


def test_managed_next_rolls_back_event_state_and_receipt_on_failure(tutor_case, monkeypatch):
    from tutor_api.services import events

    case = tutor_case
    with case["factory"]() as db:
        before = db.scalar(select(func.count()).select_from(TutorEventRow))
    original = events.append_event

    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs["event_type"] == "hint":
            raise RuntimeError("test failure after event append")
        return result

    monkeypatch.setattr(events, "append_event", broken)
    with pytest.raises(RuntimeError, match="test failure after event append"):
        next_step(case, "request_hint", key="failed-managed-next")
    with case["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(TutorEventRow)) == before
        assert db.get(StudySession, case["session"]["id"]).hint_level_revealed == 0
        assert (
            db.scalar(
                select(IdempotencyReceipt).where(
                    IdempotencyReceipt.key_digest
                    == key_digest(case["tokens"]["student"], "failed-managed-next")
                )
            )
            is None
        )


def test_managed_retest_keeps_all_pre_submit_assistance_blocked(tutor_case):
    from datetime import timedelta

    from tutor_api.models import ReviewItem

    case = tutor_case
    attempt = case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )
    correct = set(case["payload"]["question"]["answer"]["value"])
    wrong = next(
        option["key"]
        for option in case["payload"]["question"]["content"]["options"]
        if option["key"] not in correct
    )
    submitted = case["student"].data(
        "POST", f"/attempts/{attempt['id']}/submit", json={"answer": {"selected_options": [wrong]}}
    )
    review_id = submitted["review_item"]["id"]
    with case["factory"]() as db:
        db.get(ReviewItem, review_id).due_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    session = case["student"].data(
        "POST",
        "/sessions",
        expect=201,
        json={"question_id": case["question"], "origin": "review", "review_item_id": review_id},
    )
    path = f"/tutor/sessions/{session['id']}/next"
    before = case["student"].data("GET", f"/sessions/{session['id']}/events")
    for action in (
        "request_hint",
        "request_standard",
        "request_fast",
        "request_visual",
        "mark_confused",
    ):
        error = case["student"].error(
            "POST", path, expect=409, json={"action": action, "confirm_end_independent": True}
        )
        assert error["code"] == "hints_disabled_in_retest"
    assert case["student"].data("GET", f"/sessions/{session['id']}/events") == before
    assert case["calls"] == []


@pytest.mark.parametrize("first_action", ["hint", "submit"])
def test_rr_old_snapshot_waits_then_uses_current_session_and_tail(tutor_case, first_action):
    from threading import current_thread

    from sqlalchemy import event, text

    from tutor_api.schemas import SubmitIn, TutorActionIn
    from tutor_api.services import orchestrator, session_service

    case = tutor_case
    factory = case["factory"]
    waiting, snapshot = Event(), Event()
    attempt = None
    if first_action == "submit":
        attempt = case["student"].data(
            "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
        )
    with factory() as first:
        engine = first.get_bind()
        session_service.lock_owned_session(first, case["tokens"]["student"], case["session"]["id"])

        def observe(conn, cursor, sql, parameters, ctx, many):
            if (
                current_thread().name.startswith("stale-view")
                and "study_sessions" in sql
                and "FOR UPDATE" in sql.upper()
            ):
                waiting.set()

        event.listen(engine, "before_cursor_execute", observe)

        def turn(db, request_id, action="request_hint"):
            return orchestrator.next_step(
                orchestrator.TutorContext(
                    db=db,
                    settings=case["app"].state.settings,
                    gateway=case["app"].state.gateway,
                    student_id=case["tokens"]["student"],
                    pseudonym="fixture-pseudonym",
                    request_id=request_id,
                    now=datetime.now(UTC),
                    allow_gateway=False,
                ),
                case["session"]["id"],
                TutorActionIn(action=action),
            )

        def stale_reader():
            with factory() as second:
                assert (
                    second.execute(text("SELECT @@transaction_isolation")).scalar()
                    == "REPEATABLE-READ"
                )
                second.scalar(select(func.count()).select_from(TutorEventRow))
                cached = second.get(StudySession, case["session"]["id"])
                assert cached.hint_level_revealed == 0
                snapshot.set()
                result = turn(
                    second,
                    "stale-second",
                    "request_visual" if first_action == "submit" else "request_hint",
                )
                second.commit()
                return result

        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-view") as pool:
                pending = pool.submit(stale_reader)
                try:
                    assert snapshot.wait(3) and waiting.wait(3)
                    assert not pending.done()
                    if first_action == "submit":
                        result = session_service.submit_attempt(
                            first,
                            case["app"].state.settings,
                            case["tokens"]["student"],
                            attempt["id"],
                            SubmitIn(
                                answer={
                                    "selected_options": case["payload"]["question"]["answer"][
                                        "value"
                                    ]
                                }
                            ),
                            key_digest="f" * 64,
                            request_id="lock-first-submit",
                            now=datetime.now(UTC),
                        )
                    else:
                        result = turn(first, "lock-first")
                    first.commit()
                finally:
                    first.rollback()
                resumed = pending.result(timeout=5)
            if first_action == "submit":
                assert resumed.events[0]["type"] == "visual"
                assert resumed.session.submitted_attempts == 1
                assert resumed.session.active_attempt_id is None
            else:
                assert result.session.hint_level_revealed == 1
                assert resumed.session.hint_level_revealed == 2
            assert resumed.events[0]["seq_no"] == result.events[0]["seq_no"] + 1
        finally:
            event.remove(engine, "before_cursor_execute", observe)


def test_next_and_submit_share_session_lock_and_event_order(tutor_case):
    case = tutor_case
    attempt = case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )
    start = Event()

    def hint():
        assert start.wait(3)
        return next_step(case, "request_hint")

    def submit():
        assert start.wait(3)
        return case["student"].data(
            "POST",
            f"/attempts/{attempt['id']}/submit",
            json={"answer": {"selected_options": case["payload"]["question"]["answer"]["value"]}},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        hinted, submitted = pool.submit(hint), pool.submit(submit)
        start.set()
        hint_result, submit_result = hinted.result(timeout=10), submitted.result(timeout=10)
    assert submit_result["evaluation"]["is_correct"] is True
    hinted_first = hint_result["events"][0]["seq_no"] < submit_result["events"][0]["seq_no"]
    assert submit_result["evaluation"]["assisted"] is hinted_first
    assert submit_result["evaluation"]["independent"] is (not hinted_first)
    page = case["student"].data("GET", f"/sessions/{case['session']['id']}/events")
    seq = [event["seq_no"] for event in page["items"]]
    assert len(seq) == len(set(seq)) and seq == sorted(seq)
    with case["factory"]() as db:
        assert db.get(StudySession, case["session"]["id"]).hint_level_revealed == 1


def test_concurrent_create_attempt_has_single_open_attempt(tutor_case):
    case = tutor_case
    start = Event()

    def create(_):
        assert start.wait(3)
        return case["student"].request(
            "POST", "/attempts", json={"session_id": case["session"]["id"]}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(create, index) for index in range(2)]
        start.set()
        results = [future.result(timeout=10) for future in pending]
    assert sorted(result.status_code for result in results) == [201, 409]
    assert (
        next(result for result in results if result.status_code == 409).json()["error"]["code"]
        == "attempt_in_progress"
    )


def test_managed_visual_preserves_sec304_before_and_after_solution(tutor_case):
    case = tutor_case
    first = next_step(case, "request_visual", confirm_end_independent=True)
    assert first["events"][0]["type"] == "notice"
    assert first["session"]["used_solution"] is False
    next_step(case, "request_standard", confirm_end_independent=True)
    shown = next_step(case, "request_visual")
    assert shown["events"][0]["type"] == "visual"
    assert case["calls"] == []
