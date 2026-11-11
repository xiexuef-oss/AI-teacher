from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.schemas import AnswerMode, QuestionScope, SourceCategory, Subject
from tutor_api.services import question_service

router = APIRouter()


@router.get("/questions")
def list_questions(
    subject: Subject | None = None,
    answer_mode: AnswerMode | None = None,
    source_category: SourceCategory | None = None,
    scope: QuestionScope = "all",
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    page = question_service.list_questions(
        ctx.db,
        question_service.student_scope(ctx.db, ctx.student_id),
        subject=subject,
        answer_mode=answer_mode,
        source_category=source_category,
        scope_filter=scope,
        cursor=cursor,
        limit=limit,
    )
    return ok(page)


@router.get("/questions/{question_id}")
def get_question(question_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    question = question_service.get_published_question(ctx.db, str(question_id))
    scope = question_service.student_scope(ctx.db, ctx.student_id)
    return ok(question_service.serialize_question(ctx.db, question, scope))
