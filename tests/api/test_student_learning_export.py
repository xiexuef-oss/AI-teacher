import json

import pytest
from sqlalchemy import select

from support.flows import (
    EXPERIMENT,
    INK,
    PROOF,
    WRITTEN,
    begin,
    blank,
    choice,
    solve,
    submit,
    tutor,
)
from support.parents import authorize, invite, links_of, revoke
from tutor_api.models import Attempt, HandwritingDraft, ParentInvite, ParentStudentLink

PATH = "/profile/learning-export"


def test_parent_access_export_is_owned_whitelisted_and_readonly(student, parent, new_student, db):
    authorize(student, parent)
    link = links_of(student)["links"][0]
    assert parent.get(PATH, params={"student_id": student.user_id}).status_code == 403
    revoke(student, link["id"])
    active_invite = invite(student)
    other = new_student()
    foreign_invite = invite(other)
    authorize(other, parent)
    foreign_link = links_of(other)["links"][0]
    before_links = [
        (r.id, r.authorization_revision, r.consent_at, r.revoked_at)
        for r in db.scalars(select(ParentStudentLink))
    ]
    before_invites = [
        (r.id, r.code_hash, r.redeemed_at, r.revoked_at) for r in db.scalars(select(ParentInvite))
    ]
    data = student.data("GET", PATH)
    records = data["parent_access_records"]
    assert records["history_complete"] is False
    assert len(records["links"]) == 1 and records["links"][0]["id"] == link["id"]
    assert records["links"][0]["revoked_at"] is not None
    assert len(records["invites"]) == 2
    assert any(r["redeemed_at"] is not None for r in records["invites"])
    raw = json.dumps(records)
    for secret in (
        parent.user_id,
        parent.token,
        other.user_id,
        foreign_invite["id"],
        foreign_link["id"],
        active_invite["code"],
        student.token,
        "code_hash",
        "redeemed_by",
        "parent_id",
    ):
        assert secret not in raw
    for row in db.scalars(select(ParentInvite)):
        assert row.code_hash not in raw
    assert "guardian_authorizations" not in data["excluded"]
    db.expire_all()
    assert [
        (r.id, r.authorization_revision, r.consent_at, r.revoked_at)
        for r in db.scalars(select(ParentStudentLink))
    ] == before_links
    assert [
        (r.id, r.code_hash, r.redeemed_at, r.revoked_at) for r in db.scalars(select(ParentInvite))
    ] == before_invites


def test_reauthorization_exports_only_stored_state_and_never_claims_full_history(
    student, parent, clock
):
    authorize(student, parent)
    first = links_of(student)["links"][0]
    revoke(student, first["id"])
    clock.advance(days=1)
    authorize(student, parent)
    current = links_of(student)["links"][0]
    assert current["id"] == first["id"]
    records = student.data("GET", PATH)["parent_access_records"]
    assert records["history_complete"] is False
    assert len(records["links"]) == 1
    assert records["links"][0]["consent_at"] == current["consent_at"]
    assert records["links"][0]["revoked_at"] is None
    assert len(records["invites"]) == 2


def test_export_keeps_expired_and_superseded_invites_without_refreshing_them(student, clock):
    first = invite(student)
    second = invite(student)
    clock.advance(days=2)
    records = student.data("GET", PATH)["parent_access_records"]
    assert {row["id"] for row in records["invites"]} == {first["id"], second["id"]}
    by_id = {row["id"]: row for row in records["invites"]}
    assert by_id[first["id"]]["revoked_at"] is not None
    assert by_id[second["id"]]["expires_at"] == second["expires_at"]
    assert by_id[second["id"]]["redeemed_at"] is None
    assert records["links"] == []


def test_export_parent_records_keep_one_snapshot_during_concurrent_revoke(student, parent, app):
    from sqlalchemy import event

    authorize(student, parent)
    original = links_of(student)["links"][0]
    changed = []
    engine = app.state.session_factory.kw["bind"]

    def another_device(connection, cursor, sql, parameters, context, many):
        if changed or "FROM parent_student_links" not in sql:
            return
        changed.append(True)
        revoke(student, original["id"])
        invite(student)

    event.listen(engine, "after_cursor_execute", another_device)
    try:
        records = student.data("GET", PATH)["parent_access_records"]
    finally:
        event.remove(engine, "after_cursor_execute", another_device)
    assert changed
    assert records["links"][0]["revoked_at"] is None
    assert len(records["invites"]) == 1
    current = student.data("GET", PATH)["parent_access_records"]
    assert current["links"][0]["revoked_at"] is not None
    assert len(current["invites"]) == 2


@pytest.mark.parametrize("scope", ["link", "invite"])
def test_parent_access_records_count_toward_whole_export_limit(student, parent, monkeypatch, scope):
    from tutor_api.services import student_learning_export

    if scope == "link":
        authorize(student, parent)
    else:
        invite(student)
        invite(student)
    monkeypatch.setattr(student_learning_export, "MAX_RECORDS", 1)
    assert student.get(PATH).status_code == 413


@pytest.mark.parametrize(
    "key", ["math-quadratic-param-written", "phys-ohm-experiment", "math-ineq-diff-proof"]
)
def test_subjective_export_preserves_pending_and_only_saved_self_checks(onboarded, key):
    _, attempt = begin(onboarded, key)
    submit(onboarded, attempt["id"], {**WRITTEN, **EXPERIMENT, **PROOF}[key])
    path = f"/attempts/{attempt['id']}/self-check"
    checklist = onboarded.data("GET", path)
    marks = [{"point_key": point["key"], "level": "partial"} for point in checklist["points"]]
    onboarded.data("PUT", path, json={"marks": marks})
    session = onboarded.data("GET", PATH)["sessions"][0]
    assert session["attempts"][0]["evaluation"]["state"] == "pending"
    assert session["self_checks"][0]["marks"] == marks
    assert "reference_steps" not in session["self_checks"][0]


def test_review_history_is_exported(onboarded, clock):
    _, _, result = solve(onboarded, "math-ineq-min", blank("5"))
    review = result["review_item"]
    clock.advance(days=2)
    _, attempt = begin(onboarded, "math-ineq-min", origin="review", review_item_id=review["id"])
    submit(onboarded, attempt["id"], blank("4"))
    onboarded.data("POST", f"/reviews/{review['id']}/complete", json={"attempt_id": attempt["id"]})
    data = onboarded.data("GET", PATH)
    assert data["reviews"][0]["id"] == review["id"]
    assert data["review_history"][0]["first_attempt_id"] == attempt["id"]


def test_export_is_owned_readonly_and_does_not_unlock_answers(onboarded, new_student, db):
    session, attempt = begin(onboarded, "math-mono-quadratic")
    onboarded.data(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        json={"base_revision": 0, "answer": choice("A"), "strokes": INK},
    )
    tutor(onboarded, session["id"], "request_hint")
    other = new_student()
    other.save_profile(json={"region_code": "CN-51", "subjects": ["math"]})
    _, foreign = begin(other, "math-mono-quadratic")
    before = [(a.id, a.status, a.answer_json) for a in db.scalars(select(Attempt))]
    response = onboarded.get(PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["profile"]["user_id"] == onboarded.user_id
    assert data["scope"] == "server_learning_records"
    exported = data["sessions"]
    assert len(exported) == 1 and exported[0]["session"]["id"] == session["id"]
    assert exported[0]["drafts"][0]["strokes"] == INK
    assert exported[0]["attempts"][0]["answer"] == choice("A")
    assert len(exported[0]["events"]) == 1
    assert not exported[0]["session"]["used_solution"]
    raw = json.dumps(data)
    assert foreign["id"] not in raw and other.user_id not in raw
    assert onboarded.token not in raw and '"answer_json"' not in raw
    assert all("request_id" not in item for item in exported[0]["attempts"])
    db.expire_all()
    assert [(a.id, a.status, a.answer_json) for a in db.scalars(select(Attempt))] == before


def test_empty_and_unauthorized_export(student, parent, reviewer, anon):
    assert student.data("GET", PATH)["sessions"] == []
    for actor in (parent, reviewer):
        response = actor.get(PATH)
        assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
    assert anon.get(PATH).status_code == 401
    assert student.get(PATH, params={"student_id": parent.user_id}).status_code == 422


@pytest.mark.parametrize("limit", ["rows", "bytes"])
def test_limit_fails_whole_export_without_changing_drafts(onboarded, db, monkeypatch, limit):
    from tutor_api.services import student_learning_export

    _, attempt = begin(onboarded, "math-mono-quadratic")
    monkeypatch.setattr(
        student_learning_export, "MAX_RECORDS" if limit == "rows" else "MAX_BYTES", 1
    )
    assert onboarded.get(PATH).status_code == 413
    assert (
        db.scalar(select(HandwritingDraft).where(HandwritingDraft.attempt_id == attempt["id"]))
        is not None
    )
