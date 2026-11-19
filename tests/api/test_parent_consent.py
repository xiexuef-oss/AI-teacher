"""家长绑定：学生明确授权、可撤销（PRD §3、US-06、docs/04 parent_student_links）。

原型阶段的授权方式：学生自己生成一次性邀请码，家长输入。监护授权方案（Q-03）没有冻结，
这里不做任何年龄判断，也不代表法定的监护人核验。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from support.api import ApiClient
from support.parents import authorize, invite, link, links_of, new_identity, revoke, weekly, z
from tutor_api.models import AuditLog, ParentInvite, ParentStudentLink, User

CODE = re.compile(r"^[23456789A-HJKMNP-Z]{10}$")  # 去掉了容易看错的 0 O 1 I L


def _redeem(parent: ApiClient, code: str, *, expect: int = 201, **kwargs):
    if expect == 201:
        return parent.data("POST", "/parents/links", expect=201, json={"code": code}, **kwargs)
    return parent.error("POST", "/parents/links", expect=expect, json={"code": code}, **kwargs)


# ---------------------------------------------------------------- 身份与角色


def test_a_local_identity_can_be_a_parent(client):
    identity = ApiClient(client).data(
        "POST",
        "/dev/local-identities",
        expect=201,
        auth=False,
        key=False,
        params={"role": "parent"},
    )

    assert identity["role"] == "parent"


def test_a_parent_cannot_use_the_student_or_admin_endpoints(parent):
    calls = [
        ("GET", "/profile", None),
        ("GET", "/tasks/today", None),
        ("GET", "/questions", None),
        ("GET", "/progress/summary", None),
        ("GET", "/reviews/due", None),
        ("POST", "/sessions", {"question_id": str(uuid.uuid4()), "origin": "practice"}),
        ("POST", "/me/parent-invites", None),
        ("GET", "/me/parent-links", None),
        ("POST", f"/me/parent-links/{uuid.uuid4()}/revoke", None),
        ("GET", "/admin/questions", None),
    ]
    for method, path, body in calls:
        assert parent.error(method, path, expect=403, json=body)["code"] == "forbidden", path


def test_the_parent_endpoints_are_closed_to_everyone_but_parents(onboarded, reviewer, admin, anon):
    other = uuid.uuid4()
    calls = [
        ("GET", "/parents/students", None),
        ("GET", f"/parents/students/{other}/weekly", None),
        ("POST", "/parents/links", {"code": "ABCDE23456"}),
    ]
    for who in (onboarded, reviewer, admin):
        for method, path, body in calls:
            assert who.error(method, path, expect=403, json=body)["code"] == "forbidden", path
    for method, path, body in calls:
        assert anon.error(method, path, expect=401, json=body)["code"] == "unauthenticated"


# ---------------------------------------------------------------- 邀请码


def test_a_student_can_create_a_one_time_invite_code(onboarded, db, clock):
    created = invite(onboarded)

    assert CODE.match(created["code"])
    assert created["created_at"] == z(clock.now())
    assert created["expires_at"] == z(clock.now() + timedelta(hours=24))
    row = db.scalar(select(ParentInvite))
    assert row.student_id == onboarded.user_id
    assert row.code_hash == hashlib.sha256(created["code"].encode()).hexdigest()
    assert row.redeemed_at is None and row.revoked_at is None
    # 明文不落库：这一行的任何一列都不等于邀请码
    stored = [str(getattr(row, column.name)) for column in ParentInvite.__table__.columns]
    assert created["code"] not in stored


def test_every_code_is_different_and_a_new_one_voids_the_students_old_one(onboarded, parent):
    first, second = invite(onboarded), invite(onboarded)

    assert first["code"] != second["code"]
    assert _redeem(parent, first["code"], expect=404)["code"] == "invite_invalid"
    assert link(parent, second["code"])["student_id"] == onboarded.user_id


def test_a_new_code_from_one_student_does_not_void_another_students_code(
    onboarded, new_student, parent
):
    other = new_student()
    mine, theirs = invite(onboarded), invite(other)

    invite(other)  # 另一个学生又生成了一个：只作废他自己的

    assert link(parent, mine["code"])["student_id"] == onboarded.user_id
    assert _redeem(parent, theirs["code"], expect=404)["code"] == "invite_invalid"


def test_an_invite_expires(onboarded, parent, clock):
    created = invite(onboarded)
    clock.advance(hours=24, seconds=1)

    assert _redeem(parent, created["code"], expect=404)["code"] == "invite_invalid"
    assert links_of(onboarded)["pending_invite"] is None


def test_an_invite_still_works_just_before_it_expires(onboarded, parent, clock):
    created = invite(onboarded)
    clock.advance(hours=23, minutes=59)

    assert link(parent, created["code"])["student_id"] == onboarded.user_id


def test_the_invite_lifetime_is_configurable(custom_app, clock):
    raw = custom_app(parent_invite_ttl_minutes=30)
    student, parent = new_identity(raw), new_identity(raw, "parent")

    created = invite(student)
    assert created["expires_at"] == z(clock.now() + timedelta(minutes=30))
    clock.advance(minutes=31)
    assert _redeem(parent, created["code"], expect=404)["code"] == "invite_invalid"


def test_a_code_can_only_be_used_once(onboarded, parent, new_parent, clock):
    created = invite(onboarded)
    clock.advance(minutes=3)

    linked = link(parent, created["code"])

    assert linked["student_id"] == onboarded.user_id
    assert linked["linked_at"] == z(clock.now())
    assert _redeem(new_parent(), created["code"], expect=404)["code"] == "invite_invalid"


def test_the_formatting_of_a_typed_code_is_forgiven(onboarded, parent):
    code = invite(onboarded)["code"]

    typed = f"  {code[:5].lower()} - {code[5:].lower()} "

    assert link(parent, typed)["student_id"] == onboarded.user_id


@pytest.mark.parametrize(
    ("code", "expect"),
    [
        ("ZZZZZZZZZZ", 404),  # 格式对，但没有这个码
        ("SHORT", 404),
        ("0O1ILABCDE", 404),  # 含不会出现在邀请码里的字符
        ("", 422),
        ("x" * 41, 422),
    ],
)
def test_wrong_codes_are_all_turned_away_alike(parent, code, expect):
    error = _redeem(parent, code, expect=expect)

    assert error["code"] == ("invite_invalid" if expect == 404 else "validation_error")


def test_only_students_create_invites_and_only_parents_redeem_them(onboarded, parent):
    assert parent.error("POST", "/me/parent-invites", expect=403)["code"] == "forbidden"
    assert _redeem(onboarded, "ABCDE23456", expect=403)["code"] == "forbidden"


def test_redeeming_while_already_linked_is_a_conflict_and_keeps_the_new_code(onboarded, parent):
    authorize(onboarded, parent)
    again = invite(onboarded)

    error = _redeem(parent, again["code"], expect=409)

    assert error["code"] == "already_linked"
    assert links_of(onboarded)["pending_invite"]["id"] == again["id"], "邀请码保持没用过"


def test_one_parent_can_follow_several_students_and_a_student_can_have_several_parents(
    onboarded, new_student, new_parent, parent
):
    second_student, second_parent = new_student(), new_parent()

    authorize(onboarded, parent)
    authorize(second_student, parent)
    authorize(onboarded, second_parent)

    followed = parent.data("GET", "/parents/students")["items"]
    assert {item["student_id"] for item in followed} == {onboarded.user_id, second_student.user_id}
    assert {link_["parent_id"] for link_ in links_of(onboarded)["links"]} == {
        parent.user_id,
        second_parent.user_id,
    }
    assert [
        item["student_id"] for item in second_parent.data("GET", "/parents/students")["items"]
    ] == [onboarded.user_id]


# ---------------------------------------------------------------- 学生看得到的授权


def test_the_student_sees_who_they_authorized_but_never_the_code(onboarded, parent, clock):
    assert links_of(onboarded) == {"links": [], "pending_invite": None, "parent_invite_revision": 0}

    created = invite(onboarded)
    waiting = links_of(onboarded)
    assert waiting["links"] == []
    assert waiting["pending_invite"] == {
        "id": created["id"],
        "created_at": created["created_at"],
        "expires_at": created["expires_at"],
    }
    assert created["code"] not in json.dumps(waiting)

    clock.advance(minutes=5)
    linked = link(parent, created["code"])
    done = links_of(onboarded)
    (entry,) = done["links"]
    assert entry["parent_id"] == parent.user_id
    assert entry["consent_at"] == created["created_at"], "同意的时间是学生生成邀请码的时间"
    assert entry["consent_at"] != entry["linked_at"], "不是家长输入的时间"
    assert entry["linked_at"] == linked["linked_at"]
    assert entry["revoked_at"] is None and entry["parent_label"] is None
    assert done["pending_invite"] is None


def test_the_parents_own_name_is_shown_when_it_has_one(onboarded, parent, db):
    db.get(User, parent.user_id).display_name = "妈妈"
    db.commit()

    authorize(onboarded, parent)

    assert links_of(onboarded)["links"][0]["parent_label"] == "妈妈"


def test_the_parent_sees_the_students_own_name_when_it_has_one(onboarded, parent):
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "grade": "G12",
            "subjects": ["math", "physics", "chemistry"],
            "display_name": "小明",
        }
    )

    linked = authorize(onboarded, parent)

    assert linked["display_name"] == "小明"
    assert parent.data("GET", "/parents/students")["items"][0]["display_name"] == "小明"


# ---------------------------------------------------------------- 撤销


def test_revoking_takes_effect_immediately(onboarded, parent):
    authorize(onboarded, parent)
    (entry,) = links_of(onboarded)["links"]
    assert weekly(parent, onboarded.user_id)["student_id"] == onboarded.user_id

    revoked = revoke(onboarded, entry["id"])

    assert revoked["id"] == entry["id"] and revoked["revoked_at"] is not None
    error = parent.error("GET", f"/parents/students/{onboarded.user_id}/weekly", expect=404)
    assert error["code"] == "not_found"
    assert parent.data("GET", "/parents/students")["items"] == []
    assert links_of(onboarded)["links"] == []


def test_only_the_student_who_granted_it_can_revoke(onboarded, new_student, parent, reviewer):
    authorize(onboarded, parent)
    (entry,) = links_of(onboarded)["links"]
    path = f"/me/parent-links/{entry['id']}/revoke"

    assert (
        new_student().error("POST", path, json={"expected_authorization_revision": 1}, expect=404)[
            "code"
        ]
        == "not_found"
    )
    assert parent.error("POST", path, expect=403)["code"] == "forbidden"
    assert reviewer.error("POST", path, expect=403)["code"] == "forbidden"
    assert len(links_of(onboarded)["links"]) == 1, "都没有撤销成功"
    assert weekly(parent, onboarded.user_id)["student_id"] == onboarded.user_id


def test_revoking_something_that_is_gone_is_404(onboarded, parent):
    authorize(onboarded, parent)
    (entry,) = links_of(onboarded)["links"]
    revoke(onboarded, entry["id"])

    again = onboarded.error(
        "POST",
        f"/me/parent-links/{entry['id']}/revoke",
        json={"expected_authorization_revision": 2},
        expect=404,
    )
    unknown = onboarded.error(
        "POST",
        f"/me/parent-links/{uuid.uuid4()}/revoke",
        json={"expected_authorization_revision": 1},
        expect=404,
    )

    assert again["code"] == unknown["code"] == "not_found"


def test_revoking_with_the_same_key_twice_replays_the_first_answer(onboarded, parent):
    authorize(onboarded, parent)
    (entry,) = links_of(onboarded)["links"]
    path = f"/me/parent-links/{entry['id']}/revoke"
    key = f"revoke-{uuid.uuid4()}"

    first = onboarded.post(
        path, json={"expected_authorization_revision": entry["authorization_revision"]}, key=key
    )
    second = onboarded.post(
        path, json={"expected_authorization_revision": entry["authorization_revision"]}, key=key
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"


def test_creating_redeeming_and_revoking_all_need_an_idempotency_key(onboarded, parent):
    assert onboarded.error(
        "POST",
        "/me/parent-invites",
        json={"expected_parent_invite_revision": 0},
        expect=400,
        key=False,
    )["code"] == ("idempotency_key_required")
    assert parent.error(
        "POST", "/parents/links", expect=400, json={"code": "ABCDE23456"}, key=False
    )["code"] == ("idempotency_key_required")
    assert onboarded.error(
        "POST",
        f"/me/parent-links/{uuid.uuid4()}/revoke",
        json={"expected_authorization_revision": 1},
        expect=400,
        key=False,
    )["code"] == ("idempotency_key_required")


def test_the_same_key_creates_one_invite_and_links_once(onboarded, parent, db):
    key = f"invite-{uuid.uuid4()}"
    first = onboarded.post(
        "/me/parent-invites", json={"expected_parent_invite_revision": 0}, key=key
    )
    second = onboarded.post(
        "/me/parent-invites", json={"expected_parent_invite_revision": 0}, key=key
    )

    assert first.json() == second.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert db.scalar(select(func.count()).select_from(ParentInvite)) == 1

    code = first.json()["data"]["code"]
    redeem_key = f"redeem-{uuid.uuid4()}"
    one = parent.post("/parents/links", json={"code": code}, key=redeem_key)
    two = parent.post("/parents/links", json={"code": code}, key=redeem_key)
    assert one.json() == two.json() and two.headers["idempotency-replayed"] == "true"
    assert db.scalar(select(func.count()).select_from(ParentStudentLink)) == 1


def test_a_revoked_parent_can_be_authorized_again_with_a_new_code(onboarded, parent, db, clock):
    first = authorize(onboarded, parent)
    (entry,) = links_of(onboarded)["links"]
    revoke(onboarded, entry["id"])
    clock.advance(days=1)

    second = authorize(onboarded, parent)

    assert second["linked_at"] > first["linked_at"]
    assert weekly(parent, onboarded.user_id)["student_id"] == onboarded.user_id
    db.expire_all()
    (row,) = db.scalars(select(ParentStudentLink)).all()
    assert row.revoked_at is None, "同一对家长和学生只有一行，重新授权时重新打开它"
    assert row.consent_at == clock.now(), "同意的时间是这一次的，不是第一次的"


# ---------------------------------------------------------------- 审计


def test_consent_events_are_audited_without_the_code(onboarded, parent, db):
    created = invite(onboarded)
    link(parent, created["code"])
    (entry,) = links_of(onboarded)["links"]
    revoke(onboarded, entry["id"])

    rows = list(db.scalars(select(AuditLog).where(AuditLog.action.like("parent.%"))))

    by_action = {row.action: row for row in rows}
    assert set(by_action) == {"parent.invite_created", "parent.link_created", "parent.link_revoked"}
    assert by_action["parent.invite_created"].actor_id == onboarded.user_id
    assert by_action["parent.link_created"].actor_id == parent.user_id
    assert by_action["parent.link_revoked"].actor_id == onboarded.user_id
    assert created["code"] not in json.dumps([row.detail_json for row in rows])
