"""Receive and review private school materials under the student's ownership."""

from base64 import b64decode
from datetime import timedelta
from hashlib import sha256
from json import dumps
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased

from tutor_api.blob_store import BlobNotFound
from tutor_api.db import new_id
from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.idempotency import run_idempotent
from tutor_api.models import (
    AuditLog,
    LearningJob,
    SchoolMaterialCommand,
    SchoolMaterialConfirmation,
    SchoolMaterialCorrection,
    SchoolMaterialResult,
)
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import MediaBlobIn, _In
from tutor_api.services import media_service
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.document_split import split_pages
from tutor_api.services.learning_jobs import enqueue

router = APIRouter(route_class=PrivateRoute)
PURPOSE = "school_material"
MATERIAL_KINDS = {"application/pdf": "pdf", "image/jpeg": "jpeg", "image/png": "png"}


class SchoolMaterialUploadIn(_In):
    mime: Literal["application/pdf", "image/jpeg", "image/png"]
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SchoolMaterialSubmitIn(_In):
    media_id: UUID


@router.post("/school-materials")
def submit(body: SchoolMaterialSubmitIn, ctx: Ctx = Depends(student_ctx)):
    store = media_service.store(ctx)
    source = str(body.media_id)

    def action(_):
        now = ctx.now()
        try:
            blob = store.stat(source, owner=ctx.actor_id, now=now)
            if blob.purpose != PURPOSE:
                raise BlobNotFound()
            store.read(source, owner=ctx.actor_id, now=now, temporary=True)
        except BlobNotFound:
            raise not_found() from None
        job_id = enqueue(ctx.db, ctx.student_id, f"school-material:{source}", now)
        if ctx.db.get(SchoolMaterialCommand, job_id, with_for_update=True) is None:
            ctx.db.add(SchoolMaterialCommand(job_id=job_id, media_id=source))
        job = ctx.db.get_one(LearningJob, job_id, with_for_update=True)
        return {"id": job.id, "status": job.status, "attempts": job.attempts}

    return run_idempotent(ctx, body, 202, action)


def _result(ctx, job_id, *, lock=False):
    if lock and ctx.db.get_bind().dialect.name == "sqlite":
        owned = select(LearningJob.id).where(LearningJob.student_id == ctx.student_id)
        ctx.db.execute(
            update(SchoolMaterialResult)
            .where(
                SchoolMaterialResult.job_id == str(job_id), SchoolMaterialResult.job_id.in_(owned)
            )
            .values(expires_at=SchoolMaterialResult.expires_at)
        )
    query = (
        select(LearningJob.status, SchoolMaterialResult)
        .join(SchoolMaterialCommand, SchoolMaterialCommand.job_id == LearningJob.id)
        .outerjoin(SchoolMaterialResult, SchoolMaterialResult.job_id == LearningJob.id)
        .where(LearningJob.id == str(job_id), LearningJob.student_id == ctx.student_id)
    )
    row = ctx.db.execute(query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise not_found()
    status, result = row
    if status != "succeeded":
        raise conflict("school_material_pages_unavailable", "学校材料页面暂不可查看")
    if result is None or result.expires_at <= ctx.now():
        raise not_found()
    return result


def _corrections(job_id):
    return select(SchoolMaterialCorrection).where(SchoolMaterialCorrection.job_id == str(job_id))


def _current_pages(ctx, job_id):
    result = _result(ctx, job_id)
    candidate = aliased(SchoolMaterialCorrection)
    latest = (
        select(func.max(candidate.revision))
        .where(
            candidate.job_id == SchoolMaterialCorrection.job_id,
            candidate.page_number == SchoolMaterialCorrection.page_number,
        )
        .scalar_subquery()
    )
    corrections = {
        item.page_number: item
        for item in ctx.db.scalars(
            _corrections(job_id).where(SchoolMaterialCorrection.revision == latest)
        )
    }
    return [
        {**page, "text": item.text, "needs_ocr": False, "revision": item.revision}
        if (item := corrections.get(page["page_number"]))
        else page
        for page in result.pages_json
    ]


@router.get("/school-materials/{job_id}/pages")
def pages(job_id: UUID, ctx: Ctx = Depends(student_ctx)):
    return ok({"pages": _current_pages(ctx, job_id)})


@router.get("/school-materials/{job_id}/pages/{page_number}/preview")
def preview_page(job_id: UUID, page_number: int = Path(ge=1), ctx: Ctx = Depends(student_ctx)):
    result = _result(ctx, job_id)
    if not any(page["page_number"] == page_number for page in result.pages_json):
        raise not_found()
    command = ctx.db.get_one(SchoolMaterialCommand, str(job_id))
    store = media_service.store(ctx)
    now = ctx.now()
    try:
        blob = store.stat(command.media_id, owner=ctx.actor_id, now=now)
        if blob.purpose != PURPOSE:
            raise BlobNotFound()
        data = store.read(blob.id, owner=ctx.actor_id, now=now, temporary=True)
    except BlobNotFound:
        raise not_found() from None
    kind = MATERIAL_KINDS[blob.mime]
    try:
        preview = parse_isolated(data, kind, ctx.settings, page=page_number)["png"]
    except DocumentParseError as error:
        if error.code == "isolation_unavailable":
            raise ApiError(503, "service_unavailable", "学校材料预览暂不可用") from None
        if error.code == "preview_not_found":
            raise not_found() from None
        raise unprocessable("page_number", error.message) from None
    if min(result.expires_at, blob.expires_at) <= ctx.now():
        raise not_found()
    return ok({"media_id": blob.id, "mime": "image/png", "content_base64": preview})


@router.get("/school-materials/{job_id}/candidates")
def candidates(job_id: UUID, ctx: Ctx = Depends(student_ctx)):
    pages = _current_pages(ctx, job_id)
    revision = _source_revision({page["page_number"]: page.get("revision", 0) for page in pages})
    items = split_pages(
        [
            {
                "number": page["page_number"],
                "text": page["text"],
                "warnings": ["该页待 OCR 或人工转写。"] if page["needs_ocr"] else [],
            }
            for page in pages
        ]
    )
    if len(items) > ctx.settings.import_max_candidates:
        raise unprocessable("job_id", "分题候选超过上限，请拆分材料后重新上传")
    for item in items:
        item.pop("payload", None)
    data = {"items": items, "source_revision": revision}
    confirmation = ctx.db.get(SchoolMaterialConfirmation, (str(job_id), revision))
    if confirmation is not None:
        data["confirmed_items"] = confirmation.items_json
    return ok(data)


def _source_revision(revisions: dict[int, int]) -> str:
    return sha256(dumps(sorted(revisions.items())).encode()).hexdigest()


PageCoordinate = Annotated[float, Field(strict=True, ge=0, le=1)]


class SchoolMaterialRegionIn(_In):
    page: int = Field(strict=True, ge=1)
    kind: Literal["stem", "answer", "teacher_mark"]
    left: PageCoordinate
    top: PageCoordinate
    right: PageCoordinate
    bottom: PageCoordinate


class SchoolMaterialConfirmedItemIn(_In):
    text: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    pages: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=1, max_length=200)
    teacher_marks: str | None = Field(default=None, min_length=1, max_length=4000, pattern=r"\S")
    teacher_score: float | None = Field(
        default=None, strict=True, ge=0, le=99999.99, multiple_of=0.01
    )
    max_score: float | None = Field(default=None, strict=True, gt=0, le=99999.99, multiple_of=0.01)
    regions: list[SchoolMaterialRegionIn] | None = Field(default=None, min_length=1, max_length=20)


class SchoolMaterialConfirmationIn(_In):
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[SchoolMaterialConfirmedItemIn] = Field(min_length=1, max_length=200)


@router.put("/school-materials/{job_id}/confirmation")
def confirm_candidates(
    job_id: UUID, body: SchoolMaterialConfirmationIn, ctx: Ctx = Depends(student_ctx)
):
    def action(_):
        result = _result(ctx, job_id, lock=True)
        revisions = dict.fromkeys((page["page_number"] for page in result.pages_json), 0)
        correction = SchoolMaterialCorrection
        for page, revision in ctx.db.execute(
            select(correction.page_number, correction.revision)
            .where(correction.job_id == str(job_id))
            .with_for_update()
        ):
            revisions[page] = max(revisions[page], revision)
        current = _source_revision(revisions)
        if body.source_revision != current:
            raise conflict("school_material_revision_conflict", "页面已更新，请刷新分题后核对")
        if len(body.items) > ctx.settings.import_max_candidates or any(
            len(set(item.pages)) != len(item.pages) or not set(item.pages) <= revisions.keys()
            for item in body.items
        ):
            raise unprocessable("items", "分题数量或关联页码无效")
        if any(
            item.teacher_score is not None
            and item.max_score is not None
            and item.teacher_score > item.max_score
            for item in body.items
        ):
            raise unprocessable("items", "教师评分不能超过原件满分")
        if any(
            region.page not in item.pages
            or region.left >= region.right
            or region.top >= region.bottom
            for item in body.items
            for region in item.regions or ()
        ):
            raise unprocessable("items", "框选区域必须位于关联页且有面积")
        items = [item.model_dump(exclude_none=True) for item in body.items]
        previous = ctx.db.get(
            SchoolMaterialConfirmation, (str(job_id), current), with_for_update=True
        )
        if previous is None:
            ctx.db.add(
                SchoolMaterialConfirmation(
                    job_id=str(job_id),
                    source_revision=current,
                    items_json=items,
                    created_at=ctx.now(),
                )
            )
        elif previous.items_json != items:
            raise conflict("school_material_already_confirmed", "该页面版本的分题已确认")
        return {"source_revision": current, "item_count": len(items)}

    return run_idempotent(ctx, body.model_dump(exclude_none=True), 200, action)


class SchoolMaterialCorrectionIn(_In):
    expected_revision: int = Field(ge=0, strict=True)
    text: str = Field(min_length=1, max_length=16000, pattern=r"\S")


@router.put("/school-materials/{job_id}/pages/{page_number}/correction")
def correct_page(
    job_id: UUID,
    body: SchoolMaterialCorrectionIn,
    page_number: int = Path(ge=1),
    ctx: Ctx = Depends(student_ctx),
):
    def action(_):
        result = _result(ctx, job_id, lock=True)
        if not any(page["page_number"] == page_number for page in result.pages_json):
            raise not_found()
        latest = ctx.db.scalar(
            _corrections(job_id)
            .where(SchoolMaterialCorrection.page_number == page_number)
            .order_by(SchoolMaterialCorrection.revision.desc())
            .limit(1)
            .with_for_update()
        )
        revision = latest.revision if latest else 0
        if revision != body.expected_revision:
            raise conflict("school_material_revision_conflict", "页面已更新，请刷新后核对")
        ctx.db.add(
            SchoolMaterialCorrection(
                job_id=str(job_id),
                page_number=page_number,
                revision=revision + 1,
                text=body.text,
                created_at=ctx.now(),
            )
        )
        ctx.db.add(
            AuditLog(
                id=new_id(),
                actor_id=ctx.actor_id,
                action="school_material.page_corrected",
                target_type="school_material",
                target_id=str(job_id),
                detail_json={"page_number": page_number, "revision": revision + 1},
                request_id=ctx.request_id,
                created_at=ctx.now(),
            )
        )
        return {"page_number": page_number, "revision": revision + 1}

    return run_idempotent(ctx, body, 200, action)


@router.post("/school-materials/uploads")
def reserve(body: SchoolMaterialUploadIn, ctx: Ctx = Depends(student_ctx)):
    store = media_service.store(ctx)

    def action(_):
        limit = ctx.settings.media_max_bytes
        if body.size_bytes > limit:
            raise ApiError(413, "payload_too_large", "学校材料体积超过上限")
        now = ctx.now()
        blob = store.reserve(
            owner=ctx.actor_id,
            purpose=PURPOSE,
            mime=body.mime,
            size_bytes=body.size_bytes,
            sha256=body.sha256,
            now=now,
            expires_at=now + timedelta(seconds=ctx.settings.media_temporary_ttl_seconds),
        )
        return {
            "media_id": blob.id,
            "upload_url": f"/api/v1/school-materials/uploads/{blob.id}/content",
            "upload_method": "PUT",
            "expires_at": blob.expires_at.isoformat(),
            "max_bytes": limit,
        }

    return run_idempotent(ctx, body, 201, action)


@router.put("/school-materials/uploads/{media_id}/content")
def upload(media_id: UUID, body: MediaBlobIn, ctx: Ctx = Depends(student_ctx)):
    store = media_service.store(ctx)
    source = str(media_id)

    def action(_):
        try:
            blob = store.stat(source, owner=ctx.actor_id, now=ctx.now())
            if blob.purpose != PURPOSE:
                raise BlobNotFound()
        except BlobNotFound:
            raise not_found() from None
        try:
            data = b64decode(body.content_base64, validate=True)
            if len(data) != blob.size_bytes or sha256(data).hexdigest() != blob.sha256:
                raise ValueError("size or digest mismatch")
            kind = MATERIAL_KINDS[blob.mime]
            if kind == "pdf" and not data.startswith(b"%PDF-"):
                raise ValueError("invalid PDF header")
            settings = ctx.settings
            if kind != "pdf" and settings.media_max_pixels < settings.import_max_image_pixels:
                settings = settings.model_copy(
                    update={"import_max_image_pixels": settings.media_max_pixels}
                )
            page_count = len(parse_isolated(data, kind, settings)["pages"])
            if page_count < 1:
                raise ValueError("empty school material")
        except DocumentParseError as error:
            if error.code == "page_limit":
                raise ApiError(413, "payload_too_large", "学校材料页数超过上限") from None
            if error.code == "isolation_unavailable":
                raise ApiError(503, "service_unavailable", "学校材料校验暂不可用") from None
            raise unprocessable("content_base64", error.message) from None
        except (ValueError, OSError):
            raise unprocessable("content_base64", "学校材料格式、大小或摘要不匹配") from None
        try:
            store.put(source, owner=ctx.actor_id, data=data, now=ctx.now())
        except BlobNotFound:
            raise not_found() from None
        except OSError:
            raise ApiError(503, "service_unavailable", "学校材料存储暂不可用") from None
        return {**media_service.info(blob), "page_count": page_count}

    return run_idempotent(ctx, body, 200, action)
