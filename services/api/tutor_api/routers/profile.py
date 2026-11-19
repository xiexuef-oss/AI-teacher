from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import ProfileUpdateIn
from tutor_api.services import profile_service, student_learning_export, student_media_export

router = APIRouter(route_class=PrivateRoute)


@router.get("/profile/media-export")
def get_media_export(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(student_media_export.export(ctx))


@router.get("/profile/learning-export")
def get_learning_export(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(student_learning_export.export(ctx))


@router.get("/profile")
def get_profile(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    profile = profile_service.get_profile(ctx.db, ctx.student_id)
    return ok(profile_service.serialize_profile(ctx.db, profile))


@router.put("/profile")
def update_profile(body: ProfileUpdateIn, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key_digest: str):
        profile = profile_service.update_profile(
            ctx.db, ctx.student_id, body, now=ctx.now(), request_id=ctx.request_id
        )
        return profile_service.serialize_profile(ctx.db, profile)

    return run_idempotent(ctx, body, 200, action)
