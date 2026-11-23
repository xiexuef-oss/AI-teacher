"""内容审核后台的接口（PRD P0 第 9 条、docs/03 P11）。只有 reviewer 与 admin 可用。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from tutor_api.deps import Ctx, ok, reviewer_ctx
from tutor_api.errors import ApiError
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import (
    AdminQuestionEditIn,
    AdminQuestionImportIn,
    QuestionStatus,
    ReviewBatchIn,
    ReviewDecisionIn,
    SourceCategory,
    Subject,
)
from tutor_api.services import content_factory_jobs, review_service
from tutor_api.services.content_factory_originals import OriginalUpload, upload_original
from tutor_api.services.content_factory_question_types import (
    QuestionTypeDraft,
    QuestionTypeReview,
    create_question_type,
    list_knowledge_nodes,
    question_type_detail,
    review_question_type,
)
from tutor_api.services.content_factory_roles import (
    ContentFactoryRole,
    list_content_factory_roles,
    require_content_factory_role,
    set_role_assignment,
)
from tutor_api.services.content_factory_sources import (
    ContentFactoryPermissionReview,
    list_source_permissions,
    register_source,
    review_permission,
)

router = APIRouter(route_class=PrivateRoute)


@router.post("/admin/content-factory/sources/{source_id}/original")
def upload_content_factory_original(
    source_id: UUID, body: OriginalUpload, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return run_idempotent(ctx, body, 200, lambda _: upload_original(ctx, str(source_id), body))


@router.post("/admin/content-factory/jobs")
def create_content_factory_job(
    body: content_factory_jobs.JobRequest, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return run_idempotent(ctx, body, 202, lambda _: content_factory_jobs.enqueue(ctx, body))


@router.get("/admin/content-factory/jobs/{job_id}")
def get_content_factory_job(job_id: UUID, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return ok(content_factory_jobs.get_job(ctx, str(job_id)))


@router.post("/admin/content-factory/jobs/{job_id}/cancel")
def cancel_content_factory_job(job_id: UUID, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return run_idempotent(
        ctx, None, 200, lambda _: content_factory_jobs.cancel_owned_job(ctx, str(job_id))
    )


@router.post("/admin/content-factory/question-types/{question_type_id}/review")
def review_content_factory_question_type(
    question_type_id: UUID, body: QuestionTypeReview, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "reviewer")
    return run_idempotent(
        ctx, body, 200, lambda _: review_question_type(ctx, str(question_type_id), body)
    )


@router.get("/admin/content-factory/question-types/{question_type_id}")
def get_content_factory_question_type(
    question_type_id: UUID, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    roles = list_content_factory_roles(ctx.db, ctx.principal)
    if not {"editor", "reviewer"}.intersection(roles):
        raise ApiError(403, "forbidden", "当前角色无权访问")
    return ok(question_type_detail(ctx.db, str(question_type_id)))


@router.get("/admin/content-factory/knowledge-nodes")
def list_content_factory_knowledge_nodes(
    subject: Subject, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return ok({"items": list_knowledge_nodes(ctx.db, subject)})


@router.post("/admin/content-factory/question-types")
def create_content_factory_question_type(
    body: QuestionTypeDraft, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")

    def create(_key_digest: str):
        result = create_question_type(ctx, body)
        return {"id": result.id, "status": result.status}

    return run_idempotent(ctx, body, 201, create)


@router.get("/admin/content-factory/source-permissions")
def list_content_factory_source_permissions(
    source_id: UUID, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "reviewer")
    return ok({"items": list_source_permissions(ctx, str(source_id))})


@router.post("/admin/content-factory/source-permissions")
def review_content_factory_source_permission(
    body: ContentFactoryPermissionReview, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "reviewer")
    return run_idempotent(ctx, body, 200, lambda _: review_permission(ctx, body))


class ContentFactorySourceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    source_class: Literal["original", "licensed", "open", "public_reference"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/admin/content-factory/sources")
def register_content_factory_source(
    body: ContentFactorySourceRegistration, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    require_content_factory_role(ctx.db, ctx.principal, "editor")
    return run_idempotent(
        ctx,
        body,
        201,
        lambda _: register_source(ctx, body.title, body.source_class, body.sha256),
    )


class ContentFactoryRoleAssignmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: ContentFactoryRole
    enabled: StrictBool


@router.post("/admin/content-factory/role-assignments")
def set_content_factory_role_assignment(
    body: ContentFactoryRoleAssignmentCommand, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    if ctx.principal.role != "admin":
        raise ApiError(403, "forbidden", "当前角色无权访问")
    return run_idempotent(
        ctx,
        body,
        200,
        lambda _: set_role_assignment(ctx, str(body.user_id), body.role, body.enabled),
    )


@router.get("/admin/content-factory/roles/me")
def get_my_content_factory_roles(ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return ok({"roles": list_content_factory_roles(ctx.db, ctx.principal)})


@router.post("/admin/question-reviews/batch")
def review_batch(body: ReviewBatchIn, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return run_idempotent(ctx, body, 200, lambda _: review_service.decide_batch(ctx, body))


@router.post("/admin/question-imports")
def import_question_draft(
    body: AdminQuestionImportIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return review_service.import_draft(
            ctx.db, actor_id=ctx.actor_id, body=body, now=ctx.now(), request_id=ctx.request_id
        )

    return run_idempotent(ctx, body, 201, action)


@router.get("/admin/questions")
def list_admin_questions(
    status: QuestionStatus | None = None,
    subject: Subject | None = None,
    source_category: SourceCategory | None = None,
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(reviewer_ctx),
) -> JSONResponse:
    return ok(
        review_service.list_questions(
            ctx.db,
            status=status,
            subject=subject,
            source_category=source_category,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/admin/questions/{question_id}")
def get_admin_question(question_id: UUID, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return ok(review_service.question_detail(ctx.db, str(question_id)))


@router.post("/admin/questions/{question_id}/review")
def review_question(
    question_id: UUID, body: ReviewDecisionIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return review_service.decide(
            ctx.db,
            actor_id=ctx.actor_id,
            question_id=str(question_id),
            body=body,
            now=ctx.now(),
            request_id=ctx.request_id,
        )

    return run_idempotent(ctx, body, 200, action)


@router.post("/admin/questions/{question_id}/versions")
def create_question_version(
    question_id: UUID, body: AdminQuestionEditIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return review_service.create_version(
            ctx.db,
            actor_id=ctx.actor_id,
            question_id=str(question_id),
            body=body,
            now=ctx.now(),
            request_id=ctx.request_id,
        )

    return run_idempotent(ctx, body, 201, action)


@router.get("/admin/questions/{question_id}/versions/{version}")
def get_question_version(
    question_id: UUID, version: int = Path(ge=1), ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return ok(review_service.version_snapshot(ctx.db, str(question_id), version))
