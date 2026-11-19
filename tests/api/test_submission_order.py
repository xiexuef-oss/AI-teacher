"""Creation order must not decide which of several drafts was submitted first."""

from support.flows import CORRECT, begin, submit, tutor
from tutor_api.db import new_id
from tutor_api.models import Attempt, HandwritingDraft

KEY = "math-mono-quadratic"


def another_draft(app, clock, session_id):
    identifier = new_id()
    with app.state.session_factory() as db:
        db.add(
            Attempt(
                id=identifier,
                session_id=session_id,
                attempt_no=2,
                status="draft",
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        db.flush()
        db.add(
            HandwritingDraft(
                id=new_id(), attempt_id=identifier, revision=1, updated_at=clock.now()
            )
        )
        db.commit()
    return identifier


def test_submission_number_is_unassigned_until_submit(onboarded):
    _, draft = begin(onboarded, KEY)
    assert draft["submission_no"] is None
    assert draft["copied_from_attempt_id"] is None
    assert draft["copied_from_revision"] is None
    result = submit(onboarded, draft["id"], CORRECT[KEY])
    assert result["attempt"]["submission_no"] == 1
    assert result["evaluation"]["independent"] is True


def test_later_created_draft_can_be_first_actual_submission(onboarded, app, clock):
    session, original = begin(onboarded, KEY)
    later = another_draft(app, clock, session["id"])
    first = submit(onboarded, later, CORRECT[KEY])
    assert first["evaluation"]["independent"] is True
    assert first["attempt"]["attempt_no"] == 2
    assert first["attempt"]["submission_no"] == 1
    assert first["session"]["active_attempt_id"] == original["id"]
    second = submit(onboarded, original["id"], CORRECT[KEY])
    assert second["evaluation"]["independent"] is False
    assert second["attempt"]["attempt_no"] == 1
    assert second["attempt"]["submission_no"] == 2
    assert second["session"]["submitted_attempts"] == 2


def test_first_actual_submission_still_inherits_shared_assistance(onboarded, app, clock):
    session, _ = begin(onboarded, KEY)
    later = another_draft(app, clock, session["id"])
    tutor(onboarded, session["id"], "request_hint")
    result = submit(onboarded, later, CORRECT[KEY])
    assert result["evaluation"]["independent"] is False
    assert result["evaluation"]["assisted"] is True
    assert result["attempt"]["submission_no"] == 1


def test_invalid_answer_does_not_consume_submission_number(onboarded):
    _, draft = begin(onboarded, KEY)
    onboarded.error(
        "POST", f"/attempts/{draft['id']}/submit", json={"answer": {}}, expect=422
    )
    result = submit(onboarded, draft["id"], CORRECT[KEY])
    assert result["attempt"]["submission_no"] == 1
