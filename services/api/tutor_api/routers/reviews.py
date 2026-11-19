from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import ReviewCompleteIn, ReviewScope, ReviewStateOut
from tutor_api.services import review_scheduler

router = APIRouter(route_class=PrivateRoute)


@router.get("/reviews/due")
def list_due_reviews(
    scope: ReviewScope = "due",
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    page = review_scheduler.list_reviews(
        ctx.db,
        ctx.student_id,
        scope=scope,
        cursor=cursor,
        limit=limit,
        now=ctx.now(),
        settings=ctx.settings,
    )
    return ok(page)


@router.get("/reviews/{review_id}/state")
def get_review_state(review_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    item = review_scheduler.get_owned_item(ctx.db, ctx.student_id, str(review_id))
    return ok(
        ReviewStateOut(
            id=item.id,
            question_id=item.question_id,
            status=item.status,
            stage=item.stage,
            total_stages=len(ctx.settings.review_intervals),
            due_at=item.due_at,
            last_result=item.last_result,
            last_attempt_id=item.last_attempt_id,
            updated_at=item.updated_at,
        )
    )


@router.post("/reviews/{review_id}/complete")
def complete_review(
    review_id: UUID, body: ReviewCompleteIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return review_scheduler.complete(
            ctx.db,
            ctx.settings,
            student_id=ctx.student_id,
            review_id=str(review_id),
            attempt_id=body.attempt_id.lower(),
            now=ctx.now(),
        )

    return run_idempotent(ctx, body, 200, action)
