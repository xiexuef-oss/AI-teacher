from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, student_ctx
from tutor_api.gateway_io import pseudonym
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import TutorActionIn
from tutor_api.services import orchestrator

router = APIRouter()


@router.post("/tutor/sessions/{session_id}/next")
def tutor_next(
    session_id: UUID, body: TutorActionIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    state = ctx.request.app.state

    def action(_key_digest: str):
        context = orchestrator.TutorContext(
            db=ctx.db,
            settings=ctx.settings,
            gateway=state.gateway,
            student_id=ctx.student_id,
            pseudonym=pseudonym(state.pseudonym_secret, ctx.student_id),
            request_id=ctx.request_id,
            now=ctx.now(),
        )
        return orchestrator.next_step(context, str(session_id), body)

    return run_idempotent(ctx, body, 200, action)
