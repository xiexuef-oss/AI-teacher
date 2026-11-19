"""DRAFT301B1: creation order must never stand in for submission order."""

from support.flows import begin, blank, solve, submit
from support.parents import authorize, weekly
from tutor_api.db import new_id
from tutor_api.models import Attempt
from tutor_api.services import task_planner


def seed_first_submission(db, session, *, now, correct=False):
    """Leave creation #1 as a draft and submit creation #2 first."""
    attempt = Attempt(
        id=new_id(),
        session_id=session["id"],
        attempt_no=2,
        submission_no=1,
        status="submitted",
        answer_json=blank("5"),
        evaluation_state="verified",
        is_correct=correct,
        independent=True,
        created_at=now,
        submitted_at=now,
        updated_at=now,
    )
    db.add(attempt)
    db.commit()
    return attempt.id


def test_progress_counts_first_submission_after_an_earlier_unsubmitted_draft(onboarded, db, clock):
    session, _ = begin(onboarded, "math-ineq-min")
    seed_first_submission(db, session, now=clock.now())
    progress = onboarded.data("GET", "/progress/summary")
    assert progress["hint_dependency"]["denominator"] == 1
    assert progress["independent"]["denominator"] == 1


def test_weekly_counts_first_submission_without_counting_drafts_or_extra_sessions(
    onboarded,
    parent,
    db,
    clock,
):
    authorize(onboarded, parent)
    session, _ = begin(onboarded, "math-ineq-min")
    seed_first_submission(db, session, now=clock.now())
    report = weekly(parent, onboarded.user_id)
    assert report["hint_dependency"]["denominator"] == 1
    assert (report["sessions_count"], report["attempts_count"]) == (1, 1)


def test_weak_nodes_use_first_submission_even_when_first_created_attempt_is_draft(
    onboarded,
    db,
    clock,
):
    session, _ = begin(onboarded, "math-ineq-min")
    seed_first_submission(db, session, now=clock.now())
    assert task_planner._weak_nodes(db, onboarded.user_id)


def test_review_completion_uses_first_submission_and_only_advances_once(onboarded, db, clock):
    _, _, result = solve(onboarded, "math-ineq-min", blank("5"))
    item = result["review_item"]
    clock.advance(days=1)
    session, draft = begin(onboarded, "math-ineq-min", origin="review", review_item_id=item["id"])
    first_id = seed_first_submission(db, session, now=clock.now(), correct=True)
    done = onboarded.data("POST", f"/reviews/{item['id']}/complete", json={"attempt_id": first_id})
    assert done["result"] == "passed"
    assert done["review_item"]["stage"] == 1
    error = onboarded.error(
        "POST", f"/reviews/{item['id']}/complete", expect=409, json={"attempt_id": draft["id"]}
    )
    assert error["code"] == "review_already_completed"


def test_two_sessions_in_one_due_window_cannot_skip_the_next_interval(onboarded, clock):
    _, _, result = solve(onboarded, "math-ineq-min", blank("5"))
    item = result["review_item"]
    clock.advance(days=1)
    attempts = [
        begin(onboarded, "math-ineq-min", origin="review", review_item_id=item["id"])[1]
        for _ in range(2)
    ]
    for attempt in attempts:
        assert submit(onboarded, attempt["id"], blank("4"))["evaluation"]["independent"]
    path = f"/reviews/{item['id']}/complete"
    body = {"attempt_id": attempts[0]["id"]}
    first = onboarded.data("POST", path, json=body, key="first-window-completion")
    assert first["review_item"]["stage"] == 1
    assert onboarded.data("POST", path, json=body, key="first-window-completion") == first
    error = onboarded.error("POST", path, expect=409, json={"attempt_id": attempts[1]["id"]})
    assert error["code"] == "review_not_due"
    items = onboarded.data("GET", "/reviews/due", params={"scope": "all"})["items"]
    assert [(row["stage"], row["due_at"]) for row in items] == [(1, first["next_due_at"])]
