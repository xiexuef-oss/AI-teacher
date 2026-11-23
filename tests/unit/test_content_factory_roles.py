import pytest

from tutor_api.auth import Principal
from tutor_api.errors import ApiError
from tutor_api.models import ContentFactoryRoleAssignment
from tutor_api.services.content_factory_roles import require_content_factory_role


@pytest.mark.parametrize("role", ["editor", "reviewer", "publisher", "admin"])
def test_content_factory_roles_require_explicit_assignment(db, reviewer, clock, role):
    principal = Principal(user_id=reviewer.user_id, role="reviewer")
    with pytest.raises(ApiError):
        require_content_factory_role(db, principal, role)
    db.add(
        ContentFactoryRoleAssignment(
            user_id=reviewer.user_id,
            cf_role=role,
            assigned_by=reviewer.user_id,
            assigned_at=clock.now(),
        )
    )
    db.flush()
    require_content_factory_role(db, principal, role)
    for other in {"editor", "reviewer", "publisher", "admin"} - {role}:
        with pytest.raises(ApiError):
            require_content_factory_role(db, principal, other)
    for outside in ("student", "parent"):
        with pytest.raises(ApiError):
            require_content_factory_role(
                db, Principal(user_id=reviewer.user_id, role=outside), role
            )
