import pytest
from sqlalchemy import select

from support.flows import begin, tutor
from tutor_api.errors import ApiError
from tutor_api.models import Solution, User
from tutor_api.services.invocation_context import capture_context, require_context


def test_context_rejects_late_hint_result_after_session_changes(onboarded, db):
    session, _ = begin(onboarded, "math-mono-quadratic")
    before = capture_context(db, onboarded.user_id, session["id"])
    assert require_context(db, onboarded.user_id, session["id"], before.digest).id == session["id"]
    db.commit()
    tutor(onboarded, session["id"], "request_hint")
    with pytest.raises(ApiError) as rejected:
        require_context(db, onboarded.user_id, session["id"], before.digest)
    assert rejected.value.status_code == 409
    db.rollback()


def test_context_is_owner_scoped(onboarded, new_student, db):
    student = new_student()
    session, _ = begin(onboarded, "math-mono-quadratic")
    with pytest.raises(ApiError) as rejected:
        capture_context(db, student.user_id, session["id"])
    assert rejected.value.status_code == 404
    db.rollback()


def test_context_detects_fixed_version_solution_change(onboarded, db):
    session, _ = begin(onboarded, "math-mono-quadratic")
    before = capture_context(db, onboarded.user_id, session["id"])
    solution = db.scalar(
        select(Solution).where(
            Solution.question_id == session["question_id"],
            Solution.version == session["question_version"],
        )
    )
    solution.content_json = dict(solution.content_json, key_points=["changed reviewed explanation"])
    db.commit()
    with pytest.raises(ApiError) as rejected:
        require_context(db, onboarded.user_id, session["id"], before.digest)
    assert rejected.value.status_code == 409
    db.rollback()


def test_context_rechecks_disabled_account(onboarded, db):
    session, _ = begin(onboarded, "math-mono-quadratic")
    before = capture_context(db, onboarded.user_id, session["id"])
    db.get(User, onboarded.user_id).status = "disabled"
    db.commit()
    with pytest.raises(ApiError) as rejected:
        require_context(db, onboarded.user_id, session["id"], before.digest)
    assert rejected.value.status_code == 404
    db.rollback()
