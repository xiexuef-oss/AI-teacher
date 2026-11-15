"""今日任务与学情摘要。两者都是只读的即时计算。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.services import progress_service, task_planner

router = APIRouter()


@router.get("/tasks/today")
def get_today_tasks(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(task_planner.today_tasks(ctx.db, ctx.student_id, now=ctx.now()))


@router.get("/progress/summary")
def get_progress_summary(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok(progress_service.summarize(ctx.db, ctx.settings, ctx.student_id, now=ctx.now()))
