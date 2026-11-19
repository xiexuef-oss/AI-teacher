from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import SessionCreateIn, TutorEventPage
from tutor_api.services import events, session_service

router = APIRouter(route_class=PrivateRoute)


@router.post("/sessions")
def create_session(body: SessionCreateIn, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key_digest: str):
        session = session_service.create_session(ctx.db, ctx.student_id, body, now=ctx.now())
        return session_service.serialize_session(ctx.db, session)

    return run_idempotent(ctx, body, 201, action)


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    session = session_service.get_owned_session(ctx.db, ctx.student_id, str(session_id))
    return ok(session_service.serialize_session(ctx.db, session))


@router.get("/sessions/{session_id}/events")
def list_session_events(
    session_id: UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    session = session_service.get_owned_session(ctx.db, ctx.student_id, str(session_id))
    items = events.list_events(ctx.db, session.id, after_seq=after_seq, limit=limit)
    return ok(TutorEventPage(items=items, last_seq=events.last_seq(ctx.db, session.id)))
