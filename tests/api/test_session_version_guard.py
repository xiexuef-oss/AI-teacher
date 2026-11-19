"""Expected-version session creation guard and durable replay semantics."""

import pytest
from sqlalchemy import func, select

from support.seeds import qid
from tutor_api.models import Question, StudySession

KEY = "math-mono-quadratic"


def body(**extra):
    return {"question_id": qid(KEY), "origin": "practice", **extra}


@pytest.mark.parametrize("value", [None, True, False, "1", 1.5, 0, -1])
def test_expected_version_is_strict_nonnullable_integer(onboarded, value):
    onboarded.error("POST", "/sessions", json=body(expected_question_version=value), expect=422)


def test_guard_conflict_no_session_and_legacy_compatible(onboarded, app):
    with app.state.session_factory() as db:
        before = db.scalar(select(func.count()).select_from(StudySession))
    error = onboarded.error("POST", "/sessions", json=body(expected_question_version=2), expect=409)
    assert error["code"] == "question_version_conflict"
    assert error["details"] == {"expected_question_version": 2, "current_question_version": 1}
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(StudySession)) == before
    assert onboarded.data("POST", "/sessions", expect=201, json=body())["question_version"] == 1
    assert (
        onboarded.data("POST", "/sessions", expect=201, json=body(expected_question_version=1))[
            "question_version"
        ]
        == 1
    )


def test_success_replay_survives_version_change(onboarded, app):
    from tutor_api.db import new_id
    from tutor_api.models import QuestionVersion

    request = body(expected_question_version=1)
    session = onboarded.data(
        "POST", "/sessions", expect=201, json=request, key="session-version-replay"
    )
    with app.state.session_factory() as db:
        q = db.get(Question, qid(KEY))
        old = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == q.id, QuestionVersion.version == 1
            )
        )
        values = {c.name: getattr(old, c.name) for c in QuestionVersion.__table__.columns}
        values.update(id=new_id(), version=2)
        db.add(QuestionVersion(**values))
        q.version = 2
        db.commit()
    assert (
        onboarded.data("POST", "/sessions", expect=201, json=request, key="session-version-replay")
        == session
    )
    onboarded.error("POST", "/sessions", json=request, key="fresh-session-version", expect=409)


def test_legacy_persisted_fingerprint_replays_without_new_optional_field(onboarded, app):
    import hashlib
    import json

    from tutor_api.proto_models import IdempotencyRecord

    key = "legacy-session-version-key"
    first = onboarded.data("POST", "/sessions", expect=201, json=body(), key=key)
    canonical = json.dumps(
        {
            "m": "POST",
            "p": "/api/v1/sessions",
            "b": {**body(), "review_item_id": None, "parent_session_id": None},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key)
        )
        receipt.fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        db.commit()
    assert onboarded.data("POST", "/sessions", expect=201, json=body(), key=key) == first
