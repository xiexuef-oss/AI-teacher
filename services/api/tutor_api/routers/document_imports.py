"""审核员的本地文档导入任务。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse

from tutor_api.deps import Ctx, ok, reviewer_ctx
from tutor_api.idempotency import run_idempotent
from tutor_api.schemas import (
    DocImportCandidatesEditIn,
    DocImportJobCreateIn,
    DocImportRevisionIn,
    DocImportSubmitIn,
    DocImportUploadIn,
)
from tutor_api.services import document_import_service as service
from tutor_api.services.document_import_batch import submit

router = APIRouter()


@router.get("/admin/import-options")
def get_options(ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return ok(service.options(ctx.settings, ctx.now()))


@router.get("/admin/import-jobs")
def list_jobs(
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: Ctx = Depends(reviewer_ctx),
) -> JSONResponse:
    return ok(service.list_jobs(ctx, cursor, limit))


@router.post("/admin/import-jobs")
def create_job(body: DocImportJobCreateIn, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return run_idempotent(ctx, body, 201, lambda _: service.create_job(ctx, body))


@router.get("/admin/import-jobs/{job_id}")
def get_job(job_id: UUID, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return ok(service.detail(ctx, str(job_id)))


@router.post("/admin/import-jobs/{job_id}/files")
def upload_file(
    job_id: UUID, body: DocImportUploadIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return run_idempotent(ctx, body, 201, lambda _: service.upload(ctx, str(job_id), body))


@router.get("/admin/import-jobs/{job_id}/files/{file_id}/content")
def get_content(job_id: UUID, file_id: UUID, ctx: Ctx = Depends(reviewer_ctx)) -> JSONResponse:
    return ok(service.original(ctx, str(job_id), str(file_id)))


@router.get("/admin/import-jobs/{job_id}/files/{file_id}/previews/{page}")
def get_preview(
    job_id: UUID,
    file_id: UUID,
    page: int = Path(ge=1),
    media_index: int | None = Query(default=None, ge=0, le=99),
    ctx: Ctx = Depends(reviewer_ctx),
) -> JSONResponse:
    return ok(service.preview(ctx, str(job_id), str(file_id), page, media_index))


@router.post("/admin/import-jobs/{job_id}/process")
def process_job(
    job_id: UUID, body: DocImportRevisionIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return run_idempotent(
        ctx, body, 200, lambda _: service.enqueue(ctx, str(job_id), body.expected_revision)
    )


@router.post("/admin/import-jobs/{job_id}/cancel")
def cancel_job(
    job_id: UUID, body: DocImportRevisionIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return run_idempotent(
        ctx, body, 200, lambda _: service.cancel(ctx, str(job_id), body.expected_revision)
    )


@router.post("/admin/import-jobs/{job_id}/candidates")
def edit_candidates(
    job_id: UUID, body: DocImportCandidatesEditIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return run_idempotent(ctx, body, 200, lambda _: service.edit_candidates(ctx, str(job_id), body))


@router.post("/admin/import-jobs/{job_id}/submit")
def submit_candidates(
    job_id: UUID, body: DocImportSubmitIn, ctx: Ctx = Depends(reviewer_ctx)
) -> JSONResponse:
    return run_idempotent(ctx, body, 200, lambda digest: submit(ctx, str(job_id), body, digest))
