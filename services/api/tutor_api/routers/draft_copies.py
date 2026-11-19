from uuid import UUID

from fastapi import APIRouter, Depends, Query

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.routers.attempts import enforce_draft_size
from tutor_api.schemas import DraftCopyCreateIn
from tutor_api.services import question_service, session_service

router = APIRouter(route_class=PrivateRoute)


@router.post("/attempts/{attempt_id}/copies", dependencies=[Depends(enforce_draft_size)])
def create_copy(attempt_id: UUID, body: DraftCopyCreateIn, ctx: Ctx = Depends(student_ctx)):
    identifier = str(attempt_id)
    # Keep ownership before replay; status/revision belong only to the first action.
    session_service.get_owned_attempt(ctx.db, ctx.student_id, identifier)
    return run_idempotent(
        ctx,
        body,
        201,
        lambda _: session_service.create_draft_copy(
            ctx.db, ctx.student_id, identifier, body, now=ctx.now()
        ),
    )


@router.get("/questions/{question_id}/drafts")
def list_drafts(
    question_id: UUID,
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(student_ctx),
):
    return ok(
        session_service.list_question_drafts(
            ctx.db, ctx.student_id, str(question_id), cursor=cursor, limit=limit
        )
    )


@router.get("/sessions/{session_id}/question")
def get_session_question(session_id: UUID, ctx: Ctx = Depends(student_ctx)):
    session = session_service.get_owned_session(ctx.db, ctx.student_id, str(session_id))
    question = question_service.get_published_question(ctx.db, session.question_id)
    return ok(
        question_service.serialize_question(
            ctx.db,
            question,
            question_service.student_scope(ctx.db, ctx.student_id),
            version_no=session.question_version,
        )
    )
