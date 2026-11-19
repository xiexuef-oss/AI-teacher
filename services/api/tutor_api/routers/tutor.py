from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, student_ctx
from tutor_api.gateway_io import pseudonym
from tutor_api.idempotency import run_idempotent
from tutor_api.receipts import SqlReceiptStore
from tutor_api.schemas import TutorActionIn
from tutor_api.services import orchestrator, question_service, session_service
from tutor_api.services.durable_rephrase import run_durable_rephrase

router = APIRouter()


@router.post("/tutor/sessions/{session_id}/next")
def tutor_next(
    session_id: UUID, body: TutorActionIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    state = ctx.request.app.state
    invocation_store = getattr(state, "invocation_store", None)
    if invocation_store is not None and body.action == "mark_confused":
        session = session_service.get_owned_session(ctx.db, ctx.student_id, str(session_id))
        version = question_service.get_version(
            ctx.db, session.question_id, session.question_version
        )
        if not (version.teaching_json or {}).get("concept_rephrase"):
            return run_durable_rephrase(ctx, body, invocation_store)

    def action(_key_digest: str):
        context = orchestrator.TutorContext(
            db=ctx.db,
            settings=ctx.settings,
            gateway=state.gateway,
            student_id=ctx.student_id,
            pseudonym=pseudonym(state.pseudonym_secret, ctx.student_id),
            request_id=ctx.request_id,
            now=ctx.now(),
            allow_gateway=not isinstance(getattr(state, "receipt_store", None), SqlReceiptStore),
        )
        return orchestrator.next_step(context, str(session_id), body)

    return run_idempotent(ctx, body, 200, action)
