from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.errors import ApiError
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import AttemptCreateIn, DraftSyncIn, SelfCheckSaveIn, SubmitIn
from tutor_api.services import self_check_service, session_service

router = APIRouter(route_class=PrivateRoute)


async def enforce_draft_size(request: Request) -> None:
    """草稿体积上限，先于字段验证和业务写入；接收期边界由HTTP门控处理。"""
    limit = request.app.state.settings.max_draft_bytes
    declared = request.headers.get("content-length", "")
    if (declared.isdigit() and int(declared) > limit) or len(await request.body()) > limit:
        raise ApiError(
            413, "payload_too_large", f"草稿超过了 {limit} 字节的上限", {"max_bytes": limit}
        )


@router.post("/attempts")
def create_attempt(body: AttemptCreateIn, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key_digest: str):
        attempt = session_service.create_attempt(
            ctx.db, ctx.student_id, body.session_id, now=ctx.now()
        )
        return session_service.serialize_attempt(ctx.db, attempt)

    return run_idempotent(ctx, body, 201, action)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    attempt, _ = session_service.get_owned_attempt(ctx.db, ctx.student_id, str(attempt_id))
    return ok(session_service.serialize_attempt(ctx.db, attempt))


@router.get("/attempts/{attempt_id}/draft")
def get_draft(attempt_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    attempt, _ = session_service.get_owned_attempt(ctx.db, ctx.student_id, str(attempt_id))
    return ok(
        session_service.serialize_draft(attempt, session_service.get_draft(ctx.db, attempt.id))
    )


@router.put("/attempts/{attempt_id}/draft", dependencies=[Depends(enforce_draft_size)])
def sync_draft(
    attempt_id: UUID, body: DraftSyncIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return session_service.sync_draft(
            ctx.db, ctx.student_id, str(attempt_id), body, now=ctx.now()
        )

    return run_idempotent(ctx, body, 200, action)


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: UUID, body: SubmitIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    def action(key_digest: str):
        return session_service.submit_attempt(
            ctx.db,
            ctx.settings,
            ctx.student_id,
            str(attempt_id),
            body,
            key_digest=key_digest,
            request_id=ctx.request_id,
            now=ctx.now(),
        )

    return run_idempotent(ctx, body, 200, action)


@router.get("/attempts/{attempt_id}/self-check")
def get_self_check(attempt_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(self_check_service.get_self_check(ctx.db, ctx.student_id, str(attempt_id)))


@router.put("/attempts/{attempt_id}/self-check")
def save_self_check(
    attempt_id: UUID, body: SelfCheckSaveIn, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return self_check_service.save_self_check(
            ctx.db, ctx.student_id, str(attempt_id), body, now=ctx.now()
        )

    return run_idempotent(ctx, body, 200, action)
