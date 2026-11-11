"""内容审核后台的接口（PRD P0 第 9 条、docs/03 P11）。只有 reviewer 与 admin 可用。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, reviewer_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import (
    AdminQuestionEditIn,
    QuestionStatus,
    ReviewDecisionIn,
    SourceCategory,
    Subject,
)
from tutor_api.services import review_service

router = APIRouter()


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
