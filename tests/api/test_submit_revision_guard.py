"""Submission draft CAS must precede grading and preserve historical replay."""

import hashlib
import json

import pytest
from sqlalchemy import func, select

from support.flows import CORRECT, begin
from tutor_api.models import HandwritingDraft
from tutor_api.proto_models import IdempotencyRecord
from tutor_api.schemas import SubmitIn

KEY = "math-mono-quadratic"


@pytest.mark.parametrize("revision", [None, True, False, "0", 0.0, 0.5, -1])
def test_submit_revision_is_strict_nonnullable(onboarded, revision):
    _, attempt = begin(onboarded, KEY)
    onboarded.error(
        "POST",
        f"/attempts/{attempt['id']}/submit",
        expect=422,
        json={"answer": CORRECT[KEY], "expected_draft_revision": revision},
    )


def test_submit_conflict_precedes_grading_and_has_no_side_effects(onboarded, app, monkeypatch):
    from tutor_api.services import grading

    session, attempt = begin(onboarded, KEY)
    id = attempt["id"]
    draft = onboarded.data(
        "PUT", f"/attempts/{id}/draft", json={"base_revision": 0, "answer": CORRECT[KEY]}
    )
    before = onboarded.data("GET", f"/attempts/{id}")
    before_session = onboarded.data("GET", f"/sessions/{session['id']}")

    def forbidden(**kwargs):
        raise AssertionError("Conflicting submit must not grade")

    monkeypatch.setattr(grading, "grade", forbidden)
    with app.state.session_factory() as db:
        receipts = db.scalar(select(func.count()).select_from(IdempotencyRecord))
    response = onboarded.request(
        "POST",
        f"/attempts/{id}/submit",
        json={"answer": CORRECT[KEY], "expected_draft_revision": 0},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "submission_draft_revision_conflict"
    assert error["details"] == {
        "expected_draft_revision": 0,
        "server_revision": draft["revision"],
        "server_draft": draft,
    }
    assert response.headers["cache-control"] == "no-store"
    assert onboarded.data("GET", f"/attempts/{id}") == before
    assert onboarded.data("GET", f"/sessions/{session['id']}") == before_session
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == receipts


def test_matching_submit_and_success_replay_ignore_later_revision(onboarded, app):
    _, attempt = begin(onboarded, KEY)
    id = attempt["id"]
    path = f"/attempts/{id}/submit"
    body = {"answer": CORRECT[KEY], "expected_draft_revision": 0}
    first = onboarded.data("POST", path, json=body, key="guarded-submit-replay")
    assert first["attempt"]["submission_no"] == 1
    with app.state.session_factory() as db:
        draft = db.scalar(select(HandwritingDraft).where(HandwritingDraft.attempt_id == id))
        draft.revision += 1
        db.commit()
    assert onboarded.data("POST", path, json=body, key="guarded-submit-replay") == first


def test_legacy_submit_fingerprint_replays(onboarded, app):
    _, attempt = begin(onboarded, KEY)
    path = f"/attempts/{attempt['id']}/submit"
    key = "old-submit-fingerprint"
    body = {"answer": CORRECT[KEY]}
    first = onboarded.data("POST", path, json=body, key=key)
    old = SubmitIn(**body).model_dump(mode="json")
    old.pop("expected_draft_revision", None)
    canonical = json.dumps(
        {"m": "POST", "p": "/api/v1" + path, "b": old}, sort_keys=True, ensure_ascii=False
    )
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key)
        )
        receipt.fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        db.commit()
    assert onboarded.data("POST", path, json=body, key=key) == first
