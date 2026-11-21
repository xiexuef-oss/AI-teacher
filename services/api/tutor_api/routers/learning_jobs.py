from base64 import b64encode
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, update

from tutor_api.db import new_id
from tutor_api.deps import Ctx, ok, student_ctx
from tutor_api.errors import conflict, not_found, unprocessable
from tutor_api.idempotency import run_idempotent
from tutor_api.models import (
    AuditLog,
    KnowledgeNode,
    LearningJob,
    LearningPackCommand,
    LearningPackCorrection,
    LearningPackOutbox,
    LearningPackPublication,
    LearningPackReturn,
    LearningPackReturnDetails,
    LearningPackReturnPhotos,
)
from tutor_api.private_route import PrivateRoute
from tutor_api.schemas import (
    LearningPackCorrectionRequest,
    LearningPackRequest,
    LearningPackSubmission,
)
from tutor_api.services.learning_jobs import cancel, enqueue
from tutor_api.services.learning_pack_evidence import paper_evidence
from tutor_api.services.learning_pack_worker import SAMPLE_MINUTES
from tutor_api.services.paper_review_schedule import rebuild
from tutor_api.services.profile_service import get_profile
from tutor_api.services.scan_service import blob as student_image_blob
from tutor_api.services.weekly_snapshots import refresh_confirmed_week

router = APIRouter(route_class=PrivateRoute)


@router.get("/learning/review-schedule")
def get_paper_review_schedule(ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    schedule = rebuild(paper_evidence(ctx.db, ctx.student_id))
    if not schedule:
        return ok({"items": []})
    titles = dict(
        ctx.db.execute(
            select(KnowledgeNode.id, KnowledgeNode.title).where(KnowledgeNode.id.in_(schedule))
        ).all()
    )
    return ok(
        {
            "items": [
                {
                    "knowledge_id": node,
                    "title": titles[node],
                    "stage": review.stage,
                    "due_on": review.due_on.isoformat(),
                    "estimated_anchor": review.estimated_anchor,
                }
                for node, review in sorted(
                    schedule.items(), key=lambda row: (row[1].due_on, row[0])
                )
                if node in titles
            ]
        }
    )


@router.get("/learning/packs")
def list_learning_packs(after: UUID | None = None, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    query = (
        select(LearningJob.id)
        .join(LearningPackPublication, LearningPackPublication.job_id == LearningJob.id)
        .where(LearningJob.student_id == ctx.student_id, LearningJob.status == "succeeded")
        .order_by(LearningJob.id)
        .limit(51)
    )
    if after is not None:
        query = query.where(LearningJob.id > str(after))
    ids = list(ctx.db.scalars(query))
    return ok({"ids": ids[:50], **({"next_cursor": ids[49]} if len(ids) > 50 else {})})


@router.post("/learning/packs")
def create_learning_pack(
    body: LearningPackRequest, ctx: Ctx = Depends(student_ctx)
) -> JSONResponse:
    def action(key: str) -> dict:
        profile = get_profile(ctx.db, ctx.student_id)
        if profile.learning_settings_json is None:
            raise conflict("learning_settings_required", "请先保存学习安排")
        now = ctx.now()
        job_id = enqueue(ctx.db, ctx.student_id, key, now)
        ctx.db.add(
            LearningPackCommand(
                job_id=job_id,
                input_json={
                    "settings": profile.learning_settings_json,
                    "profile_revision": profile.revision,
                    "region_code": profile.region_code,
                    "exam_year": profile.exam_year,
                    "curriculum_version": profile.curriculum_version,
                    "subjects": profile.subjects_json,
                    "school_minutes": body.school_minutes,
                },
            )
        )
        ctx.db.flush()
        ctx.db.add(LearningPackOutbox(job_id=job_id, created_at=now))
        return _status(ctx, job_id)

    return run_idempotent(ctx, body, 202, action)


def _published(ctx: Ctx, job_id: UUID, *columns):
    row = ctx.db.execute(
        select(*columns)
        .select_from(LearningPackPublication)
        .join(LearningJob, LearningJob.id == LearningPackPublication.job_id)
        .where(
            LearningJob.id == str(job_id),
            LearningJob.student_id == ctx.student_id,
            LearningJob.status == "succeeded",
        )
    ).one_or_none()
    if row is None:
        raise not_found()
    return row


@router.get("/learning/packs/{job_id}/student-pdf")
def download_student_pdf(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    pdf, manifest = _published(
        ctx, job_id, LearningPackPublication.student_pdf, LearningPackPublication.manifest_json
    )
    return _pdf_response(pdf, manifest, "student_sha256")


@router.get("/learning/packs/{job_id}/solution-pdf")
def download_solution_pdf(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    (manifest,) = _published(ctx, job_id, LearningPackPublication.manifest_json)
    revision = manifest["revision"]
    required = {(item["code"], item["question_version_id"]) for item in manifest["items"]}
    confirmed = set(
        ctx.db.execute(
            select(LearningPackReturn.code, LearningPackReturn.question_version_id).where(
                LearningPackReturn.job_id == str(job_id), LearningPackReturn.revision == revision
            )
        )
    )
    if not _abandoned(ctx, job_id) and (not required or not required <= confirmed):
        raise conflict("paper_returns_incomplete", "请先确认回收纸包内全部题目")
    (pdf,) = _published(ctx, job_id, LearningPackPublication.solution_pdf)
    return _pdf_response(pdf, manifest, "solution_sha256")


def _abandoned(ctx: Ctx, job_id: UUID, *, lock: bool = False) -> bool:
    query = (
        select(AuditLog.id)
        .where(
            AuditLog.actor_id == ctx.student_id,
            AuditLog.target_type == "learning_pack",
            AuditLog.target_id == str(job_id),
            AuditLog.action == "learning_pack.abandoned",
        )
        .limit(1)
    )
    return ctx.db.scalar(query.with_for_update() if lock else query) is not None


def _lock_pack_job(ctx: Ctx, job_id: UUID) -> None:
    owner_job = (
        update(LearningJob)
        .where(LearningJob.id == str(job_id), LearningJob.student_id == ctx.student_id)
        .values(status=LearningJob.status)
    )
    if ctx.db.execute(owner_job).rowcount != 1:
        raise not_found()


@router.post("/learning/packs/{job_id}/abandon")
def abandon_pack(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key: str) -> dict:
        _lock_pack_job(ctx, job_id)
        (manifest,) = _published(ctx, job_id, LearningPackPublication.manifest_json)
        if not _abandoned(ctx, job_id, lock=True):
            ctx.db.add(
                AuditLog(
                    id=new_id(),
                    actor_id=ctx.student_id,
                    action="learning_pack.abandoned",
                    target_type="learning_pack",
                    target_id=str(job_id),
                    detail_json={"revision": manifest["revision"], "used_solution": True},
                    request_id=ctx.request_id,
                    created_at=ctx.now(),
                )
            )
        return _status(ctx, str(job_id))

    return run_idempotent(ctx, None, 200, action)


def _pdf_response(pdf: bytes, manifest: dict, digest_key: str) -> JSONResponse:
    return ok(
        {
            "revision": manifest["revision"],
            "sha256": manifest[digest_key],
            "content_base64": b64encode(pdf).decode("ascii"),
        }
    )


@router.get("/learning/packs/{job_id}/items/{code}")
def resolve_pack_item(
    job_id: UUID,
    code: Annotated[str, Path(pattern=r"^[0-9]{3}$")],
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    return ok(_pack_item(ctx, job_id, code))


def _pack_item(ctx: Ctx, job_id: UUID, code: str) -> dict:
    for item in _pack_items(ctx, job_id):
        if item["code"] == code:
            return item
    raise not_found()


def _pack_items(ctx: Ctx, job_id: UUID) -> list[dict]:
    (manifest,) = _published(ctx, job_id, LearningPackPublication.manifest_json)
    return [_item_location(manifest["revision"], item) for item in manifest["items"]]


def _item_location(revision: int, item: dict) -> dict:
    return {
        "revision": revision,
        "code": item["code"],
        "question_version_id": item["question_version_id"],
    }


@router.get("/learning/packs/{job_id}/page")
def resolve_pack_page(
    job_id: UUID,
    token: Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")],
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    (manifest,) = _published(ctx, job_id, LearningPackPublication.manifest_json)
    for item in manifest["items"]:
        if item["page_token"] == token or token in item.get("continuation_tokens", ()):
            return ok(_item_location(manifest["revision"], item))
    raise not_found()


@router.get("/learning/packs/{job_id}/items")
def list_pack_items(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    return ok({"items": _pack_items(ctx, job_id)})


@router.get("/learning/packs/{job_id}/items/{code}/returns")
def get_pack_return(
    job_id: UUID,
    code: Annotated[str, Path(pattern=r"^[0-9]{3}$")],
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    item = _pack_item(ctx, job_id, code)
    evidence = paper_evidence(ctx.db, ctx.student_id, pack_id=str(job_id), code=code)
    if not evidence:
        raise not_found()
    record = evidence[0]
    if (
        record.pack_revision != item["revision"]
        or record.question_version_id != item["question_version_id"]
    ):
        raise not_found()
    return ok(
        {
            "item": item,
            "transcript": record.transcript,
            "transcript_revision": record.transcript_revision,
            "confirmed_at": record.confirmed_at.isoformat(),
        }
    )


def _return_record(ctx: Ctx, job_id: UUID, code: str, *, lock: bool = False) -> dict:
    item = _pack_item(ctx, job_id, code)
    record = ctx.db.get(LearningPackReturn, (str(job_id), code), with_for_update=lock)
    if record is None or (
        record.revision != item["revision"]
        or record.question_version_id != item["question_version_id"]
    ):
        raise not_found()
    query = (
        select(LearningPackCorrection)
        .where(LearningPackCorrection.job_id == str(job_id), LearningPackCorrection.code == code)
        .order_by(LearningPackCorrection.revision.desc())
        .limit(1)
    )
    latest = ctx.db.scalar(query.with_for_update() if lock else query)
    return {
        "item": item,
        "transcript": latest.transcript if latest else record.transcript,
        "transcript_revision": latest.revision if latest else 0,
        "confirmed_at": record.confirmed_at.isoformat(),
    }


@router.put("/learning/packs/{job_id}/items/{code}/returns")
def correct_pack_return(
    job_id: UUID,
    code: Annotated[str, Path(pattern=r"^[0-9]{3}$")],
    body: LearningPackCorrectionRequest,
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    def action(_key: str) -> dict:
        _lock_pack_job(ctx, job_id)
        current = _return_record(ctx, job_id, code, lock=True)
        if body.expected_revision != current["transcript_revision"]:
            raise conflict(
                "paper_return_revision_conflict",
                "转写已在其他设备更新",
                {
                    "server_return": current,
                },
            )
        revision = body.expected_revision + 1
        ctx.db.add(
            LearningPackCorrection(
                job_id=str(job_id),
                code=code,
                revision=revision,
                transcript=body.transcript,
                actor_id=ctx.student_id,
                corrected_at=ctx.now(),
            )
        )
        ctx.db.flush()
        refresh_confirmed_week(
            ctx.db,
            ctx.settings,
            ctx.student_id,
            datetime.fromisoformat(current["confirmed_at"]),
            ctx.now(),
        )
        return {**current, "transcript": body.transcript, "transcript_revision": revision}

    return run_idempotent(ctx, body, 200, action)


@router.post("/learning/packs/{job_id}/items/{code}/returns")
def submit_pack_return(
    job_id: UUID,
    code: Annotated[str, Path(pattern=r"^[0-9]{3}$")],
    body: LearningPackSubmission,
    ctx: Ctx = Depends(student_ctx),
) -> JSONResponse:
    def action(_key: str) -> dict:
        # Lock the owner-scoped pack job before checking the item's unique slot.
        _lock_pack_job(ctx, job_id)
        item = _pack_item(ctx, job_id, code)
        now = ctx.now()
        if body.completed_on is not None and body.completed_on > (now + timedelta(hours=8)).date():
            raise unprocessable("completed_on", "作答日期不能在未来")
        if _abandoned(ctx, job_id, lock=True):
            raise conflict("paper_pack_abandoned", "这份纸包已结束独立作答")
        existing = ctx.db.scalar(
            select(LearningPackReturn.code)
            .where(LearningPackReturn.job_id == str(job_id), LearningPackReturn.code == code)
            .with_for_update()
        )
        if existing is not None:
            raise conflict("paper_return_exists", "这道纸包题已提交回收")
        photos = [str(media_id) for media_id in body.photo_ids or []]
        if len(set(photos)) != len(photos):
            raise unprocessable("photo_ids", "作答照片不能重复")
        if photos:
            blobs = [student_image_blob(ctx, media_id) for media_id in photos]
            if sum(photo.size_bytes for photo in blobs) > 16 * 1024 * 1024:
                raise unprocessable("photo_ids", "作答照片合计不能超过 16 MiB")
            if len({photo.sha256 for photo in blobs}) != len(blobs):
                raise unprocessable("photo_ids", "作答照片不能重复")
            for media_id in photos:
                student_image_blob(ctx, media_id, uploaded=True)
        ctx.db.add(
            LearningPackReturn(
                job_id=str(job_id),
                **item,
                transcript=body.transcript,
                confirmed_at=now,
            )
        )
        if photos or body.completed_on is not None or body.independence is not None:
            ctx.db.flush()
        if photos:
            ctx.db.add(
                LearningPackReturnPhotos(job_id=str(job_id), code=code, media_ids_json=photos)
            )
        if body.completed_on is not None or body.independence is not None:
            ctx.db.add(
                LearningPackReturnDetails(
                    job_id=str(job_id),
                    code=code,
                    completed_on=body.completed_on,
                    independence=body.independence or "unknown",
                )
            )
        return item

    return run_idempotent(ctx, body.model_dump(mode="json", exclude_none=True), 201, action)


def _status(ctx: Ctx, job_id: str) -> dict:
    row = (
        ctx.db.execute(
            select(LearningJob.id, LearningJob.status, LearningJob.attempts).where(
                LearningJob.id == job_id, LearningJob.student_id == ctx.student_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found()
    result = dict(row)
    if row["status"] != "succeeded":
        return result
    plan = ctx.db.scalar(
        select(LearningPackCommand.plan_json).where(LearningPackCommand.job_id == job_id)
    )
    if plan is None:
        return result
    published = ctx.db.scalar(
        select(LearningPackPublication.job_id).where(LearningPackPublication.job_id == job_id)
    )
    if published:
        result["pack_result"] = "published"
    elif plan.get("deferred_reason") == "awaiting_return":
        result["pack_result"] = "awaiting_return"
    elif plan["remaining_minutes"] < SAMPLE_MINUTES:
        result["pack_result"] = "insufficient_budget"
    else:
        result["pack_result"] = "no_printable_item"
    reviews = plan.get("reviews")
    if reviews:
        titles = dict(
            ctx.db.execute(
                select(KnowledgeNode.id, KnowledgeNode.title).where(
                    KnowledgeNode.id.in_([review["knowledge_id"] for review in reviews])
                )
            ).all()
        )
        result["reviews"] = [
            {**review, "title": titles.get(review["knowledge_id"], "知识点")} for review in reviews
        ]
    return result


@router.get("/learning/jobs/{job_id}")
def get_learning_job(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    status = _status(ctx, str(job_id))
    return ok(status, headers={"Retry-After": "2"})


@router.post("/learning/jobs/{job_id}/cancel")
def cancel_learning_job(job_id: UUID, ctx: Ctx = Depends(student_ctx)) -> JSONResponse:
    def action(_key: str) -> dict:
        if not cancel(ctx.db, ctx.student_id, str(job_id)):
            _status(ctx, str(job_id))
            raise conflict("learning_job_finished", "学习任务已结束")
        return _status(ctx, str(job_id))

    return run_idempotent(ctx, None, 200, action)
