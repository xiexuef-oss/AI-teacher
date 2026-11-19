"""Review epochs protect same-content ABA and preserve fixed success receipts."""

import pytest
from sqlalchemy import select

from support.admin import FAST_KEY, make_draft
from tutor_api.models import AuditLog, Question


def send(who, identifier, decision, revision, *, key=None, **extra):
    return who.request("POST", f"/admin/questions/{identifier}/review", key=key,
        json={"decision": decision, "expected_version": 1, "expected_review_revision": revision, **extra})


def test_old_publish_cannot_cross_rejected_and_reapproved_content(reviewer, new_reviewer, db):
    identifier = make_draft(db, FAST_KEY)
    other = new_reviewer()
    assert send(reviewer, identifier, "approve", 1, solution_kinds=["standard", "fast"]).status_code == 200
    assert send(other, identifier, "reject", 2, comment="重新审查").status_code == 200
    assert send(other, identifier, "approve", 3, solution_kinds=["standard"]).status_code == 200
    stale = send(reviewer, identifier, "publish", 2, key="delayed-old-publish")
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "review_revision_conflict"
    assert stale.headers["Cache-Control"] == "no-store"
    current = reviewer.data("GET", f"/admin/questions/{identifier}")
    assert (current["version"], current["review_revision"], current["status"]) == (1, 4, "reviewed")


def test_old_approve_cannot_cross_rejection_even_when_status_returns_to_draft(reviewer, db):
    identifier = make_draft(db)
    assert send(reviewer, identifier, "reject", 1, comment="退回修改").status_code == 200
    assert send(reviewer, identifier, "approve", 1).status_code == 409
    assert reviewer.data("GET", f"/admin/questions/{identifier}")["status"] == "draft"


def test_historical_success_replays_before_epoch_check_and_keeps_current_state(reviewer, db):
    identifier = make_draft(db)
    first = send(reviewer, identifier, "approve", 1, key="old-success-approve")
    assert first.status_code == 200
    assert send(reviewer, identifier, "reject", 2, comment="退回").status_code == 200
    replay = send(reviewer, identifier, "approve", 1, key="old-success-approve")
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert reviewer.data("GET", f"/admin/questions/{identifier}")["review_revision"] == 3
    assert reviewer.data("GET", f"/admin/questions/{identifier}")["status"] == "draft"


@pytest.mark.parametrize("revision", [None, True, False, 0, -1, 1.0, "1"])
def test_review_epoch_is_strict_positive_integer(reviewer, db, revision):
    identifier = make_draft(db)
    assert send(reviewer, identifier, "approve", revision).status_code == 422


def test_missing_review_epoch_is_rejected(reviewer, db):
    identifier = make_draft(db)
    reviewer.error("POST", f"/admin/questions/{identifier}/review", expect=422,
        json={"decision": "approve", "expected_version": 1})


@pytest.mark.parametrize("durable", [False, True])
def test_review_receipt_failure_rolls_back_epoch_state_solutions_and_audit(reviewer, db, app, durable):
    from tutor_api.receipts import LegacyProtoReceiptStore, SqlReceiptStore

    identifier = make_draft(db)
    store = SqlReceiptStore() if durable else LegacyProtoReceiptStore()
    app.state.receipt_store = store
    finish = store.finish

    def fail(*_args):
        raise RuntimeError("injected review receipt failure")

    store.finish = fail
    with pytest.raises(RuntimeError, match="injected review receipt"):
        send(reviewer, identifier, "approve", 1, key="failed-review-receipt")
    db.expire_all()
    current = db.get(Question, identifier)
    assert (current.status, current.review_revision) == ("draft", 1)
    assert db.scalars(select(AuditLog).where(AuditLog.target_id == identifier)).all() == []
    store.finish = finish
    assert send(reviewer, identifier, "approve", 1, key="failed-review-receipt").status_code == 200


def test_legacy_success_receipt_keeps_missing_revision_unknown(reviewer, db):
    from tutor_api.proto_models import IdempotencyRecord

    identifier = make_draft(db)
    first = send(reviewer, identifier, "approve", 1, key="legacy-review-response")
    assert first.status_code == 200
    row = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "legacy-review-response"))
    payload = row.response_json["data"].copy()
    payload.pop("review_revision")
    row.response_json = {"data": payload}
    db.commit()
    replay = send(reviewer, identifier, "approve", 1, key="legacy-review-response")
    assert replay.status_code == 200
    assert "review_revision" not in replay.json()["data"]
    assert replay.headers["Idempotency-Replayed"] == "true"


@pytest.mark.parametrize("revision", [None, True, 1.0, "1", 0])
def test_edit_and_batch_require_strict_review_epoch(reviewer, db, revision):
    from support.admin import edit_body

    identifier = make_draft(db)
    detail = reviewer.data("GET", f"/admin/questions/{identifier}")
    reviewer.error("POST", f"/admin/questions/{identifier}/versions", expect=422,
        json=edit_body(detail, title=detail["title"] + " new", expected_review_revision=revision))
    reviewer.error("POST", "/admin/question-reviews/batch", expect=422,
        json={"items": [{"question_id": identifier, "decision": "approve", "confirmed": True,
            "expected_version": 1, "expected_review_revision": revision}]})


def test_edit_requires_review_epoch_without_implicit_default(reviewer, db):
    from support.admin import edit_body

    identifier = make_draft(db)
    detail = reviewer.data("GET", f"/admin/questions/{identifier}")
    body = edit_body(detail, title=detail["title"] + " new")
    body.pop("expected_review_revision")
    reviewer.error("POST", f"/admin/questions/{identifier}/versions", expect=422, json=body)
