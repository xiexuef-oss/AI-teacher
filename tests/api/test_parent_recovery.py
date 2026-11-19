"""Fixed parent intents cannot revoke or invalidate newer student authorizations."""

import pytest
from sqlalchemy import select

from tutor_api.models import AuditLog


def generate(student, *, key=None):
    state = student.data("GET", "/me/parent-links")
    return student.data(
        "POST",
        "/me/parent-invites",
        expect=201,
        json={"expected_parent_invite_revision": state["parent_invite_revision"]},
        key=key,
    )


def redeem(parent, invite):
    return parent.data("POST", "/parents/links", expect=201, json={"code": invite["code"]})


def only_link(student):
    return student.data("GET", "/me/parent-links")["links"][0]


def revoke_body(link):
    return {"expected_authorization_revision": link["authorization_revision"]}


def test_delayed_never_executed_revoke_cannot_revoke_new_authorization(student, parent, db):
    redeem(parent, generate(student))
    initial = only_link(student)
    delayed_body = revoke_body(initial)
    student.data("POST", f"/me/parent-links/{initial['id']}/revoke", json=delayed_body)
    redeem(parent, generate(student))
    current = only_link(student)
    assert current["id"] == initial["id"]
    assert current["authorization_revision"] == initial["authorization_revision"] + 2
    before = len(db.scalars(select(AuditLog)).all())
    error = student.error(
        "POST",
        f"/me/parent-links/{initial['id']}/revoke",
        expect=409,
        json=delayed_body,
        key="delayed-never-executed-revoke",
    )
    assert error["code"] == "authorization_revision_conflict"
    assert error["details"]["server_link"] == current
    assert only_link(student) == current
    assert len(db.scalars(select(AuditLog)).all()) == before
    assert len(parent.data("GET", "/parents/students")["items"]) == 1


def test_old_successful_revoke_receipt_replays_without_touching_new_grant(student, parent):
    redeem(parent, generate(student))
    initial = only_link(student)
    path = f"/me/parent-links/{initial['id']}/revoke"
    body = revoke_body(initial)
    first = student.request("POST", path, json=body, key="successful-old-revoke")
    assert first.status_code == 200
    redeem(parent, generate(student))
    current = only_link(student)
    replay = student.request("POST", path, json=body, key="successful-old-revoke")
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.headers["Cache-Control"] == "no-store"
    assert only_link(student) == current
    assert len(parent.data("GET", "/parents/students")["items"]) == 1


def test_delayed_generate_cannot_invalidate_newer_invite(student, parent, db):
    source = student.data("GET", "/me/parent-links")["parent_invite_revision"]
    delayed_body = {"expected_parent_invite_revision": source}
    latest = generate(student)
    before = student.data("GET", "/me/parent-links")
    audit_count = len(db.scalars(select(AuditLog)).all())
    error = student.error(
        "POST",
        "/me/parent-invites",
        expect=409,
        json=delayed_body,
        key="delayed-never-executed-generate",
    )
    assert error["code"] == "parent_invite_revision_conflict"
    assert "code" not in error["details"]
    assert student.data("GET", "/me/parent-links") == before
    assert len(db.scalars(select(AuditLog)).all()) == audit_count
    assert redeem(parent, latest)["student_id"] == student.user_id


def test_invite_generation_does_not_modify_profile_edit_revision(student):
    profile = student.data("GET", "/profile")
    old_generation = student.data("GET", "/me/parent-links")["parent_invite_revision"]
    first = generate(student)
    assert first["parent_invite_revision"] == old_generation + 1
    assert student.data("GET", "/profile") == profile


@pytest.mark.parametrize("value", [None, True, False, -1, 1.0, "1"])
def test_invite_generation_revision_is_a_strict_integer(student, value):
    student.error(
        "POST",
        "/me/parent-invites",
        expect=422,
        json={"expected_parent_invite_revision": value},
    )


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.0, "1"])
def test_authorization_revision_is_a_strict_positive_integer(student, parent, value):
    redeem(parent, generate(student))
    owned = only_link(student)
    student.error(
        "POST",
        f"/me/parent-links/{owned['id']}/revoke",
        expect=422,
        json={"expected_authorization_revision": value},
    )


def test_parent_still_cannot_create_or_revoke_student_authorization(parent):
    parent.error(
        "POST",
        "/me/parent-invites",
        expect=403,
        json={"expected_parent_invite_revision": 0},
    )


def test_cross_owner_revoke_is_indistinguishable_from_absent(student, parent, new_student):
    from uuid import uuid4

    redeem(parent, generate(student))
    owned = only_link(student)
    other = new_student()
    known = other.error(
        "POST",
        f"/me/parent-links/{owned['id']}/revoke",
        expect=404,
        json=revoke_body(owned),
    )
    absent = other.error(
        "POST",
        f"/me/parent-links/{uuid4()}/revoke",
        expect=404,
        json=revoke_body(owned),
    )
    assert (known["code"], known["message"], known["details"]) == (
        absent["code"],
        absent["message"],
        absent["details"],
    )


def test_missing_old_none_bodies_are_explicitly_rejected(student):
    from uuid import uuid4

    for path in ["/me/parent-invites", f"/me/parent-links/{uuid4()}/revoke"]:
        response = student.request("POST", path)
        assert response.status_code == 422
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("operation", ["generate", "redeem", "revoke"])
def test_parent_receipt_failure_rolls_back_all_effects(
    student, parent, db, app, durable, operation
):
    from tutor_api.receipts import LegacyProtoReceiptStore, SqlReceiptStore

    invitation = generate(student)
    if operation == "revoke":
        redeem(parent, invitation)
    before = student.data("GET", "/me/parent-links")
    count = len(db.scalars(select(AuditLog)).all())
    if operation == "generate":
        caller, path, body = (
            student,
            "/me/parent-invites",
            {"expected_parent_invite_revision": before["parent_invite_revision"]},
        )
    elif operation == "redeem":
        caller, path, body = parent, "/parents/links", {"code": invitation["code"]}
    else:
        owned = before["links"][0]
        caller, path, body = student, f"/me/parent-links/{owned['id']}/revoke", revoke_body(owned)
    store = SqlReceiptStore() if durable else LegacyProtoReceiptStore()
    finish = store.finish
    app.state.receipt_store = store

    def fail(*_args):
        raise RuntimeError("injected parent receipt failure")

    store.finish = fail
    with pytest.raises(RuntimeError, match="injected parent receipt"):
        caller.request("POST", path, json=body, key="parent-failed-receipt")
    assert student.data("GET", "/me/parent-links") == before
    assert len(db.scalars(select(AuditLog)).all()) == count
    store.finish = finish
    first = caller.request("POST", path, json=body, key="parent-failed-receipt")
    assert first.status_code == (200 if operation == "revoke" else 201)
    replay = caller.request("POST", path, json=body, key="parent-failed-receipt")
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
