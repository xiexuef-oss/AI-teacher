from sqlalchemy import select

from tutor_api.models import ContentFactorySource, ContentFactorySourcePermission

PATH = "/admin/content-factory/sources"


def test_registration_requires_editor_and_creates_no_permissions(admin, reviewer, student, db):
    body = {"title": "自编工程样张", "source_class": "original", "sha256": "a" * 64}
    student.error("POST", PATH, json=body, expect=403)
    reviewer.error("POST", PATH, json=body, expect=403)
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": reviewer.user_id, "role": "editor", "enabled": True},
    )
    reviewer.error("POST", PATH, json={**body, "source_class": "private_student"}, expect=422)
    source = reviewer.data("POST", PATH, json=body, key="cf-source", expect=201)
    assert reviewer.data("POST", PATH, json=body, key="cf-source", expect=201) == source
    assert db.get_one(ContentFactorySource, source["id"]).created_by == reviewer.user_id
    assert list(db.scalars(select(ContentFactorySourcePermission))) == []
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": reviewer.user_id, "role": "editor", "enabled": False},
    )
    reviewer.error("POST", PATH, json=body, key="cf-source", expect=403)
