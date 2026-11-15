"""家长周报与绑定授权（PRD P0 第 8 条）。

学生一侧（/me/...）：生成邀请码、看自己授权过谁、撤销。家长一侧（/parents/...）：输入邀请码、
看已授权的学生、看某一周的汇总。授权是学生做的、可撤销；家长只看汇总。规则见 services/parent_service。
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, parent_ctx, student_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import ParentInviteOut, ParentInviteRedeemIn
from tutor_api.services import parent_service, weekly_service

router = APIRouter()


# ---------------------------------------------------------------- 学生：授权与撤销


@router.post("/me/parent-invites")
def create_parent_invite(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key_digest: str):
        invite, code = parent_service.create_invite(
            ctx.db, ctx.settings, ctx.student_id, now=ctx.now(), request_id=ctx.request_id
        )
        return ParentInviteOut(
            id=invite.id, code=code, created_at=invite.created_at, expires_at=invite.expires_at
        )

    return run_idempotent(ctx, None, 201, action)


@router.get("/me/parent-links")
def list_parent_links(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(parent_service.list_links(ctx.db, ctx.student_id, now=ctx.now()))


@router.post("/me/parent-links/{link_id}/revoke")
def revoke_parent_link(link_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key_digest: str):
        return parent_service.revoke_link(
            ctx.db, ctx.student_id, str(link_id), now=ctx.now(), request_id=ctx.request_id
        )

    return run_idempotent(ctx, None, 200, action)


# ---------------------------------------------------------------- 家长：绑定与查看


@router.post("/parents/links")
def redeem_parent_invite(
    body: ParentInviteRedeemIn, ctx: Ctx = Depends(parent_ctx)
) -> JSONResponse:
    def action(_key_digest: str):
        return parent_service.redeem_invite(
            ctx.db, ctx.actor_id, body.code, now=ctx.now(), request_id=ctx.request_id
        )

    return run_idempotent(ctx, body, 201, action)


@router.get("/parents/students")
def list_parent_students(ctx: Ctx = Depends(parent_ctx)) -> JSONResponse:
    return ok(parent_service.list_students(ctx.db, ctx.actor_id))


@router.get("/parents/students/{student_id}/weekly")
def get_parent_weekly(
    student_id: UUID, week_start: date | None = None, ctx: Ctx = Depends(parent_ctx)
) -> JSONResponse:
    return ok(
        weekly_service.weekly_report(
            ctx.db,
            ctx.settings,
            ctx.actor_id,
            str(student_id),
            week_start,
            now=ctx.now(),
        )
    )
