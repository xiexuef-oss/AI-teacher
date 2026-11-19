"""Expose actual first submission, even when a later-created draft submits first."""

import uuid

from support.flows import begin, choice, new_attempt, submit


def test_session_reports_actual_first_submission_and_never_creation_order(onboarded):
    session, original = begin(onboarded, "math-mono-quadratic")
    path = f"/sessions/{session['id']}"
    assert onboarded.data("GET", path)["first_submitted_attempt_id"] is None
    copied = onboarded.data(
        "POST",
        f"/attempts/{original['id']}/copies",
        json={"source_revision": 0, "answer": choice("A"), "strokes": None},
        expect=201,
    )["attempt"]
    assert copied["attempt_no"] == 2
    assert onboarded.data("GET", path)["first_submitted_attempt_id"] is None
    first = submit(onboarded, copied["id"], choice("A"))
    assert first["session"]["first_submitted_attempt_id"] == copied["id"]
    current = onboarded.data("GET", path)
    assert current["first_submitted_attempt_id"] == copied["id"]
    assert current["active_attempt_id"] == original["id"]
    submit(onboarded, original["id"], choice("B"))
    new_attempt(onboarded, session["id"])
    assert onboarded.data("GET", path)["first_submitted_attempt_id"] == copied["id"]


def test_first_submission_pointer_does_not_rewrite_creation_receipt(onboarded):
    key = f"session-{uuid.uuid4()}"
    from support.seeds import qid

    body = {"question_id": qid("math-mono-quadratic"), "origin": "practice"}
    initial = onboarded.data("POST", "/sessions", json=body, key=key, expect=201)
    attempt = onboarded.data("POST", "/attempts", json={"session_id": initial["id"]}, expect=201)
    submit(onboarded, attempt["id"], choice("A"))
    assert onboarded.data("POST", "/sessions", json=body, key=key, expect=201) == initial
    assert (
        onboarded.data("GET", f"/sessions/{initial['id']}")["first_submitted_attempt_id"]
        == attempt["id"]
    )


def test_session_pointer_is_private_and_does_not_bypass_owner_or_role(
    onboarded,
    new_student,
    parent,
):
    session, _ = begin(onboarded, "math-mono-quadratic")
    path = f"/sessions/{session['id']}"
    response = onboarded.request("GET", path)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    for other in (path, f"/sessions/{uuid.uuid4()}"):
        stranger = new_student().request("GET", other)
        assert stranger.status_code == 404
        assert "no-store" in stranger.headers["cache-control"]
        assert parent.request("GET", other).status_code == 403
