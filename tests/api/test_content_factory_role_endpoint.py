from sqlalchemy import select

from tutor_api.models import AuditLog, ContentFactoryRoleAssignment

PATH = "/admin/content-factory/roles/me"
ASSIGNMENTS = "/admin/content-factory/role-assignments"


def test_platform_admin_can_grant_and_revoke_with_idempotent_receipt(admin, reviewer, student, db):
    command = {"user_id": reviewer.user_id, "role": "editor", "enabled": True}
    reviewer.error("POST", ASSIGNMENTS, json=command, expect=403)
    admin.error("POST", ASSIGNMENTS, json={**command, "user_id": student.user_id}, expect=404)
    assert admin.data("POST", ASSIGNMENTS, json=command, key="cf-grant") == {"roles": ["editor"]}
    assert reviewer.data("GET", PATH) == {"roles": ["editor"]}
    assert admin.data("POST", ASSIGNMENTS, json={**command, "enabled": False}) == {"roles": []}
    assert admin.data("POST", ASSIGNMENTS, json=command, key="cf-grant") == {"roles": ["editor"]}
    assert reviewer.data("GET", PATH) == {"roles": []}
    events = list(db.scalars(select(AuditLog).where(AuditLog.target_id == reviewer.user_id)))
    assert len(events) == 2
    assert all(
        e.actor_id == admin.user_id and e.action == "content_factory_role_changed" for e in events
    )
    assert {e.detail_json["enabled"] for e in events} == {True, False}


def test_roles_are_private_and_reflect_only_current_grants(reviewer, student, parent, db, clock):
    student.error("GET", PATH, expect=403)
    parent.error("GET", PATH, expect=403)
    assert reviewer.data("GET", PATH) == {"roles": []}
    grant = ContentFactoryRoleAssignment(
        user_id=reviewer.user_id,
        cf_role="publisher",
        assigned_by=reviewer.user_id,
        assigned_at=clock.now(),
    )
    db.add(grant)
    db.commit()
    response = reviewer.request("GET", PATH)
    assert response.status_code == 200
    assert response.json()["data"] == {"roles": ["publisher"]}
    assert response.headers["Cache-Control"] == "no-store"
    db.delete(grant)
    db.commit()
    assert reviewer.data("GET", PATH) == {"roles": []}
