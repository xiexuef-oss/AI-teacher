import json

from sqlalchemy import func, select

from support.parents import invite
from support.seeds import qid
from tutor_api.models import IdempotencyReceipt, StudySession
from tutor_api.receipts import SqlReceiptStore


def test_formal_receipt_replays_and_rejects_cross_operation(onboarded, app, db):
    app.state.receipt_store = SqlReceiptStore()
    body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
    first = onboarded.post("/sessions", json=body, key="durable-receipt-key")
    second = onboarded.post("/sessions", json=body, key="durable-receipt-key")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert db.scalar(select(func.count()).select_from(StudySession)) == 1
    assert (
        onboarded.error(
            "POST",
            "/me/parent-invites",
            json={"expected_parent_invite_revision": 0},
            expect=409,
            key="durable-receipt-key",
        )["code"]
        == "idempotency_key_conflict"
    )


def test_formal_invite_receipt_preserves_sensitive_expiry(onboarded, app, clock, db):
    app.state.receipt_store = SqlReceiptStore()
    created = invite(
        onboarded, json={"expected_parent_invite_revision": 0}, key="durable-invite-key"
    )
    record = db.scalar(select(IdempotencyReceipt))
    assert created["code"] not in json.dumps(record.response_json)
    assert (
        invite(onboarded, json={"expected_parent_invite_revision": 0}, key="durable-invite-key")
        == created
    )
    clock.advance(hours=24)
    assert (
        onboarded.error(
            "POST",
            "/me/parent-invites",
            json={"expected_parent_invite_revision": 0},
            expect=409,
            key="durable-invite-key",
        )["code"]
        == "invite_response_expired"
    )


def test_failed_formal_action_leaves_no_committed_reservation(onboarded, app, db):
    app.state.receipt_store = SqlReceiptStore()
    for _ in range(2):
        onboarded.error(
            "POST",
            "/sessions",
            expect=404,
            json={"question_id": "00000000-0000-0000-0000-000000000000", "origin": "practice"},
            key="failed-formal-key",
        )
    assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 0


def test_formal_receipts_keep_role_and_actor_scoping(onboarded, parent, new_student, app):
    app.state.receipt_store = SqlReceiptStore()
    body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
    first = onboarded.data("POST", "/sessions", expect=201, json=body, key="actor-scope-key")
    other = new_student()
    second = other.data("POST", "/sessions", expect=201, json=body, key="actor-scope-key")
    assert first["id"] != second["id"]
    assert (
        parent.error("POST", "/sessions", expect=403, json=body, key="actor-scope-key")["code"]
        == "forbidden"
    )


def test_redis_outage_does_not_repeat_committed_business(onboarded, app):
    class Unavailable:
        calls = 0

        def acquire(self, digest):
            self.calls += 1
            raise RuntimeError("offline")

    app.state.receipt_store = SqlReceiptStore()
    app.state.receipt_coordinator = coordinator = Unavailable()
    body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
    first = onboarded.post("/sessions", json=body, key="redis-outage-key")
    second = onboarded.post("/sessions", json=body, key="redis-outage-key")
    assert first.json() == second.json() and coordinator.calls == 1


def test_redis_busy_returns_same_key_retry_conflict_without_action(onboarded, app, db):
    class Busy:
        def acquire(self, digest):
            return None

    app.state.receipt_store = SqlReceiptStore()
    app.state.receipt_coordinator = Busy()
    body = {"question_id": qid("math-ineq-min"), "origin": "practice"}
    assert (
        onboarded.error("POST", "/sessions", expect=409, json=body, key="redis-busy-key")["code"]
        == "conflict"
    )
    assert db.scalar(select(func.count()).select_from(StudySession)) == 0
    assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 0
