from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.deps import Ctx
from tutor_api.errors import ApiError, not_found, unprocessable
from tutor_api.models import (
    AuditLog,
    ContentFactorySource,
    ContentFactorySourceOriginal,
    ContentFactorySourcePermission,
)
from tutor_api.schemas import RegionCode


class ContentFactoryPermissionReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: UUID
    operation: Literal[
        "read",
        "internal_analysis",
        "store_original",
        "transform",
        "generate_variants",
        "print_pdf",
        "commercial_distribution",
        "send_to_external_ai",
    ]
    region_code: RegionCode
    decision: Literal["grant", "revoke"]
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=512)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


def review_permission(ctx: Ctx, command: ContentFactoryPermissionReview) -> dict[str, str]:
    db = ctx.db
    now = ctx.now()
    source_id = str(command.source_id)
    if db.get_bind().dialect.name == "sqlite":
        db.execute(
            update(ContentFactorySource)
            .where(ContentFactorySource.id == source_id)
            .values(title=ContentFactorySource.title)
        )
    source = db.get(ContentFactorySource, source_id, with_for_update=True)
    if source is None:
        raise not_found()
    if source.created_by == ctx.actor_id:
        raise ApiError(403, "forbidden", "不得审校本人登记的题源")

    scope = (source_id, command.operation, command.region_code)
    permission = db.get(ContentFactorySourcePermission, scope, with_for_update=True)
    if command.decision == "grant":
        if command.evidence_ref is None:
            raise unprocessable("evidence_ref", "许可须有证据引用")
        start, end = command.valid_from, command.valid_until
        if start is None or end is None or end <= max(start, now):
            raise unprocessable("valid_until", "许可须有有效且未过期的起止时间")
        if permission is None:
            permission = ContentFactorySourcePermission(
                source_id=source_id, operation=command.operation, region_code=command.region_code
            )
            db.add(permission)
        permission.evidence_ref = command.evidence_ref
        permission.reviewed_by = ctx.actor_id
        permission.valid_from, permission.valid_until = start, end
        permission.revoked_at = None
    else:
        if permission is None:
            raise not_found()
        if permission.revoked_at is not None:
            return {"id": source_id}
        permission.revoked_at = now
        if command.operation == "store_original":
            db.execute(
                delete(ContentFactorySourceOriginal).where(
                    ContentFactorySourceOriginal.source_id == source_id,
                    ContentFactorySourceOriginal.region_code == command.region_code,
                )
            )
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="content_factory_permission_reviewed",
            target_type="cf_source",
            target_id=source_id,
            request_id=ctx.request_id,
            detail_json=command.model_dump(mode="json", exclude_none=True),
            created_at=now,
        )
    )
    return {"id": source_id}


def register_source(ctx: Ctx, title: str, source_class: str, sha256: str) -> dict[str, str]:
    source_id = new_id()
    now = ctx.now()
    ctx.db.add(
        ContentFactorySource(
            id=source_id,
            title=title,
            source_class=source_class,
            sha256=sha256,
            created_by=ctx.actor_id,
            created_at=now,
        )
    )
    ctx.db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="content_factory_source_registered",
            target_type="cf_source",
            target_id=source_id,
            request_id=ctx.request_id,
            created_at=now,
        )
    )
    return {"id": source_id}


def source_permits(
    db: Session, source_id: str, operation: str, region_code: str, now: datetime, *, lock=False
) -> bool:
    permission = ContentFactorySourcePermission
    query = select(permission.source_id).where(
        permission.source_id == source_id,
        permission.operation == operation,
        permission.region_code == region_code,
        permission.revoked_at.is_(None),
        permission.valid_from <= now,
        permission.valid_until > now,
    )
    return db.scalar(query.with_for_update() if lock else query) is not None


def list_source_permissions(ctx: Ctx, source_id: str) -> list[dict[str, str]]:
    if ctx.db.get(ContentFactorySource, source_id) is None:
        raise not_found()
    now = ctx.now()
    permission = ContentFactorySourcePermission
    records = ctx.db.scalars(
        select(permission)
        .where(permission.source_id == source_id)
        .order_by(permission.region_code, permission.operation)
    )
    items = []
    for record in records:
        if record.revoked_at is not None:
            status = "revoked"
        elif now < record.valid_from:
            status = "scheduled"
        elif now >= record.valid_until:
            status = "expired"
        else:
            status = "active"
        items.append(
            {
                "operation": record.operation,
                "region_code": record.region_code,
                "status": status,
                "evidence_ref": record.evidence_ref,
                "valid_from": record.valid_from.isoformat(),
                "valid_until": record.valid_until.isoformat(),
            }
        )
    return items
