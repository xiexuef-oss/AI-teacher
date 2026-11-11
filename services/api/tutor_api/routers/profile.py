from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.schemas import ProfileUpdateIn
from tutor_api.services import profile_service

router = APIRouter()


@router.get("/profile")
def get_profile(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    profile = profile_service.get_profile(ctx.db, ctx.student_id)
    return ok(profile_service.serialize_profile(ctx.db, profile))


@router.put("/profile")
def update_profile(body: ProfileUpdateIn, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    with ctx.transaction():
        profile = profile_service.update_profile(
            ctx.db, ctx.student_id, body, now=ctx.now(), request_id=ctx.request_id
        )
        payload = profile_service.serialize_profile(ctx.db, profile)
    return ok(payload)
