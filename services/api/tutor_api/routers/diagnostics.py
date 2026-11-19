from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import DiagnosticCreateIn, DiagnosticRevisionIn
from tutor_api.services import diagnostic_service as service

router = APIRouter(route_class=PrivateRoute)


@router.get("/diagnostics")
def workspace(ctx: Ctx = Depends(student_ctx)):
    return ok(service.workspace(ctx.db, ctx.student_id))


@router.post("/diagnostics")
def create(body: DiagnosticCreateIn, ctx: Ctx = Depends(student_ctx)):
    return run_idempotent(
        ctx, body, 201, lambda _: service.create(ctx.db, ctx.student_id, body, ctx.now())
    )


@router.get("/diagnostics/history")
def history(
    cursor: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(student_ctx),
):
    return ok(
        service.history(ctx.db, ctx.student_id, cursor=str(cursor) if cursor else None, limit=limit)
    )


@router.get("/diagnostics/{diagnostic_id}")
def get_run(diagnostic_id: UUID, ctx: Ctx = Depends(student_ctx)):
    return ok(
        service.serialize_run(ctx.db, service.owned_run(ctx.db, ctx.student_id, str(diagnostic_id)))
    )


@router.post("/diagnostics/{diagnostic_id}/items/{position}/session")
def open_session(
    diagnostic_id: UUID,
    body: DiagnosticRevisionIn,
    position: int = Path(ge=1, le=3),
    ctx: Ctx = Depends(student_ctx),
):
    return run_idempotent(
        ctx,
        body,
        200,
        lambda _: service.open_session(
            ctx.db, ctx.student_id, str(diagnostic_id), position, body, ctx.now()
        ),
    )


@router.post("/diagnostics/{diagnostic_id}/abandon")
def abandon(diagnostic_id: UUID, body: DiagnosticRevisionIn, ctx: Ctx = Depends(student_ctx)):
    return run_idempotent(
        ctx,
        body,
        200,
        lambda _: service.abandon(ctx.db, ctx.student_id, str(diagnostic_id), body, ctx.now()),
    )
