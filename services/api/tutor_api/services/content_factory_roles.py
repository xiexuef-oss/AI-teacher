"""Server-side authorization for Content Factory roles."""

from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tutor_api.auth import Principal
from tutor_api.db import new_id
from tutor_api.deps import REVIEW_ROLES, Ctx
from tutor_api.errors import ApiError, not_found
from tutor_api.models import AuditLog, ContentFactoryRoleAssignment, User

ContentFactoryRole = Literal["editor", "reviewer", "publisher", "admin"]


def list_content_factory_roles(db: Session, principal: Principal) -> list[str]:
    if principal.role not in REVIEW_ROLES:
        raise ApiError(403, "forbidden", "当前角色无权访问")
    return list(
        db.scalars(
            select(ContentFactoryRoleAssignment.cf_role)
            .where(ContentFactoryRoleAssignment.user_id == principal.user_id)
            .order_by(ContentFactoryRoleAssignment.cf_role)
        )
    )


def set_role_assignment(ctx: Ctx, user_id: str, role: ContentFactoryRole, enabled: bool):
    db = ctx.db
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(User).where(User.id == user_id).values(updated_at=User.updated_at))
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None or target.role not in REVIEW_ROLES or target.status != "active":
        raise not_found()
    assignment = db.get(ContentFactoryRoleAssignment, (user_id, role), with_for_update=True)
    if enabled != (assignment is not None):
        if assignment is None:
            db.add(
                ContentFactoryRoleAssignment(
                    user_id=user_id, cf_role=role, assigned_by=ctx.actor_id, assigned_at=ctx.now()
                )
            )
        else:
            db.delete(assignment)
        db.add(
            AuditLog(
                id=new_id(),
                actor_id=ctx.actor_id,
                action="content_factory_role_changed",
                target_type="user",
                target_id=user_id,
                detail_json={"role": role, "enabled": enabled},
                request_id=ctx.request_id,
                created_at=ctx.now(),
            )
        )
        db.flush()
    return {"roles": list_content_factory_roles(db, Principal(user_id, target.role))}


def require_content_factory_role(
    db: Session, principal: Principal, role: ContentFactoryRole
) -> None:
    if (
        principal.role not in REVIEW_ROLES
        or db.scalar(
            select(ContentFactoryRoleAssignment.user_id).where(
                ContentFactoryRoleAssignment.user_id == principal.user_id,
                ContentFactoryRoleAssignment.cf_role == role,
            )
        )
        is None
    ):
        raise ApiError(403, "forbidden", "当前角色无权访问")
