"""Idempotency-Key（docs/05 §1）：非幂等动作必须带键，同键同请求只执行一次。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from support.seeds import qid

BODY = {"question_id": qid("math-ineq-min"), "origin": "practice"}


def _sessions(db) -> int:
    from tutor_api.models import StudySession

    return db.scalar(select(func.count()).select_from(StudySession))


def test_missing_key_is_rejected_before_anything_happens(onboarded, db):
    error = onboarded.error("POST", "/sessions", expect=400, json=BODY, key=False)

    assert error["code"] == "idempotency_key_required"
    assert _sessions(db) == 0


@pytest.mark.parametrize("key", ["short", "has space in it", "x" * 129, "bad/key-0001!"])
def test_malformed_key_is_rejected(onboarded, key):
    error = onboarded.error(
        "POST", "/sessions", expect=400, json=BODY, key=False, headers={"Idempotency-Key": key}
    )
    assert error["code"] == "invalid_idempotency_key"


def test_same_key_and_same_request_runs_once_and_replays_the_response(onboarded, db):
    key = f"k-{uuid.uuid4()}"

    first = onboarded.post("/sessions", json=BODY, key=key)
    second = onboarded.post("/sessions", json=BODY, key=key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "idempotency-replayed" not in first.headers
    assert second.headers["idempotency-replayed"] == "true"
    assert _sessions(db) == 1


def test_same_key_with_a_different_request_is_a_conflict(onboarded, db):
    key = f"k-{uuid.uuid4()}"
    onboarded.post("/sessions", json=BODY, key=key)

    other = {"question_id": qid("math-ineq-rect"), "origin": "practice"}
    error = onboarded.error("POST", "/sessions", expect=409, json=other, key=key)

    assert error["code"] == "idempotency_key_conflict"
    assert _sessions(db) == 1


def test_same_key_on_a_different_operation_is_a_conflict(onboarded):
    key = f"k-{uuid.uuid4()}"
    session = onboarded.data("POST", "/sessions", expect=201, json=BODY, key=key)

    error = onboarded.error(
        "POST", "/attempts", expect=409, json={"session_id": session["id"]}, key=key
    )

    assert error["code"] == "idempotency_key_conflict"


def test_keys_are_scoped_to_the_student(new_student, db):
    key = f"k-{uuid.uuid4()}"
    alice, bob = new_student(), new_student()

    first = alice.data("POST", "/sessions", expect=201, json=BODY, key=key)
    second = bob.data("POST", "/sessions", expect=201, json=BODY, key=key)

    assert first["id"] != second["id"]
    assert _sessions(db) == 2


def test_failed_requests_are_not_recorded(onboarded, db):
    key = f"k-{uuid.uuid4()}"
    missing = {"question_id": str(uuid.uuid4()), "origin": "practice"}
    onboarded.error("POST", "/sessions", expect=404, json=missing, key=key)

    retried = onboarded.post("/sessions", json=missing, key=key)
    assert retried.status_code == 404, "失败的请求重试时重新执行，而不是重放"
    assert "idempotency-replayed" not in retried.headers
    assert _sessions(db) == 0


def test_replay_returns_the_original_response_even_after_state_moved_on(onboarded):
    """重放的是首次响应的原样，不是按当前状态重新计算。"""
    key = f"k-{uuid.uuid4()}"
    created = onboarded.data("POST", "/sessions", expect=201, json=BODY, key=key)
    onboarded.data("POST", "/attempts", expect=201, json={"session_id": created["id"]})

    replayed = onboarded.data("POST", "/sessions", expect=201, json=BODY, key=key)

    assert replayed == created
    assert replayed["state"] == "READY"
    assert onboarded.data("GET", f"/sessions/{created['id']}")["state"] == "INDEPENDENT_ATTEMPT"
