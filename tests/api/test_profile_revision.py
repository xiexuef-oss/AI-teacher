"""303C: fixed receipts, explicit revision CAS, and private profile responses."""

import pytest
from sqlalchemy import select

from tutor_api.models import AuditLog, StudentProfile, User

BODY = {"region_code": "CN-51", "grade": "G12", "subjects": ["math"]}


def test_profile_receipt_replays_before_current_revision_check(student, db):
    first = student.request(
        "PUT", "/profile", json={**BODY, "expected_revision": 0}, key="profile-first"
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["revision"] == 1
    second = student.data(
        "PUT", "/profile", json={**BODY, "region_code": "CN-50", "expected_revision": 1}
    )
    assert second["revision"] == 2
    replay = student.request(
        "PUT", "/profile", json={**BODY, "expected_revision": 0}, key="profile-first"
    )
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.headers["Cache-Control"] == "no-store"
    assert student.data("GET", "/profile") == second
    assert (
        len(db.scalars(select(AuditLog).where(AuditLog.action == "profile.region_changed")).all())
        == 2
    )
    student.error(
        "PUT", "/profile", expect=409, json={**BODY, "expected_revision": 2}, key="profile-first"
    )


def test_stale_profile_write_changes_neither_user_nor_audit(student, db):
    latest = student.data(
        "PUT", "/profile", json={**BODY, "expected_revision": 0, "display_name": "最新"}
    )
    response = student.request(
        "PUT",
        "/profile",
        json={**BODY, "expected_revision": 0, "region_code": "CN-50", "display_name": "过期"},
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "profile_revision_conflict"
    assert error["details"] == {
        "expected_revision": 0,
        "server_revision": 1,
        "server_profile": latest,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert student.data("GET", "/profile") == latest
    assert db.get(User, student.user_id).display_name == "最新"
    assert (
        len(db.scalars(select(AuditLog).where(AuditLog.action == "profile.region_changed")).all())
        == 1
    )


def test_equal_timestamps_do_not_bypass_profile_revision(student):
    first = student.data("PUT", "/profile", json={**BODY, "expected_revision": 0})
    second = student.data("PUT", "/profile", json={**BODY, "expected_revision": 1})
    assert first["updated_at"] == second["updated_at"]
    assert (first["revision"], second["revision"]) == (1, 2)
    student.error("PUT", "/profile", expect=409, json={**BODY, "expected_revision": 1})


@pytest.mark.parametrize("revision", [None, True, False, -1, 0.0, "0"])
def test_profile_revision_requires_nonnegative_strict_integer(student, revision):
    student.error("PUT", "/profile", expect=422, json={**BODY, "expected_revision": revision})


def test_old_profile_clients_fail_explicitly(student):
    student.error("PUT", "/profile", expect=422, json=BODY)
    student.error("PUT", "/profile", expect=400, json={**BODY, "expected_revision": 0}, key=False)


def test_missing_profile_does_not_create_on_get_or_put(student, db):
    db.delete(db.get(StudentProfile, student.user_id))
    db.commit()
    student.error("GET", "/profile", expect=404)
    student.error("PUT", "/profile", expect=404, json={**BODY, "expected_revision": 0})
    assert db.get(StudentProfile, student.user_id) is None


def test_parent_cannot_read_or_save_profile(parent):
    parent.error("GET", "/profile", expect=403)
    parent.error("PUT", "/profile", expect=403, json={**BODY, "expected_revision": 0})


@pytest.mark.parametrize("durable", [False, True])
def test_profile_receipt_failure_rolls_back_user_profile_and_audit(student, db, app, durable):
    from tutor_api.receipts import LegacyProtoReceiptStore, SqlReceiptStore

    store = SqlReceiptStore() if durable else LegacyProtoReceiptStore()
    original_finish = store.finish

    def fail_finish(*args):
        raise RuntimeError("injected receipt persistence failure")

    store.finish = fail_finish
    app.state.receipt_store = store
    body = {**BODY, "expected_revision": 0, "display_name": "同事务"}
    with pytest.raises(RuntimeError, match="injected receipt"):
        student.request("PUT", "/profile", json=body, key="rollback-profile")
    unchanged = student.data("GET", "/profile")
    assert unchanged["revision"] == 0
    assert unchanged["region_code"] is None
    assert unchanged["display_name"] is None
    assert (
        db.scalars(select(AuditLog).where(AuditLog.action == "profile.region_changed")).all() == []
    )
    store.finish = original_finish
    first = student.request("PUT", "/profile", json=body, key="rollback-profile")
    replay = student.request("PUT", "/profile", json=body, key="rollback-profile")
    assert first.status_code == 200
    assert first.json()["data"]["revision"] == 1
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"


@pytest.mark.parametrize("same_key", [False, True])
def test_local_concurrent_profile_saves_are_serialized(student, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def save(index):
        barrier.wait(timeout=5)
        return student.request(
            "PUT",
            "/profile",
            json={**BODY, "expected_revision": 0},
            key="concurrent-profile" if same_key else f"concurrent-profile-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(save, [0, 1]))
    assert sorted(r.status_code for r in responses) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert responses[0].json() == responses[1].json()
        assert sum(r.headers.get("Idempotency-Replayed") == "true" for r in responses) == 1
    assert student.data("GET", "/profile")["revision"] == 1
