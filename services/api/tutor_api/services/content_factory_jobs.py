"""Persistent transitions for the independent research job queue."""

import re
from datetime import datetime, timedelta
from typing import Any, Literal
from unicodedata import normalize
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.deps import Ctx
from tutor_api.errors import ApiError, conflict, not_found
from tutor_api.models import (
    AuditLog,
    ContentFactoryJob,
    ContentFactorySource,
    ContentFactorySourceOriginal,
    KnowledgeNode,
)
from tutor_api.schemas import RegionCode
from tutor_api.services.content_factory_sources import source_permits
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.services.document_parser_process import parse_isolated

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=10)
RETRY_DELAY = timedelta(minutes=1)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["analyze_source"]
    source_id: UUID
    region_code: RegionCode


def job_state(job: ContentFactoryJob) -> dict:
    return {"id": job.id, "kind": job.kind, "status": job.status, "attempts": job.attempts}


def enqueue(ctx: Ctx, request: JobRequest) -> dict:
    source = str(request.source_id)
    now = ctx.now()
    if not source_permits(ctx.db, source, "internal_analysis", request.region_code, now):
        raise ApiError(403, "forbidden", "题源在所选地区缺少有效的内部分析许可")
    job = ContentFactoryJob(
        id=new_id(),
        requested_by=ctx.actor_id,
        source_id=source,
        kind=request.kind,
        parameters_json={"region_code": request.region_code},
        status="queued",
        attempts=0,
        available_at=now,
    )
    ctx.db.add(job)
    return job_state(job)


def get_job(ctx: Ctx, job_id: str) -> dict:
    job = ctx.db.get(ContentFactoryJob, job_id)
    if job is None or job.requested_by != ctx.actor_id:
        raise not_found()
    state = job_state(job)
    region = job.parameters_json.get("region_code")
    if (
        job.status == "review_required"
        and job.result_json is not None
        and job.source_id is not None
        and isinstance(region, str)
        and source_permits(ctx.db, job.source_id, "internal_analysis", region, ctx.now())
    ):
        state["result"] = dict(job.result_json)
        if "document" in state["result"] and not _can_read_original(
            ctx.db, job.source_id, region, ctx.now()
        ):
            del state["result"]["document"]
    return state


def _can_read_original(db, source_id, region, now, *, lock=False) -> bool:
    return all(
        source_permits(db, source_id, operation, region, now, lock=lock)
        for operation in ("read", "store_original")
    )


def _knowledge_suggestions(db: Session, pages: list[dict]) -> list[dict]:
    def searchable(value: str) -> str:
        return " ".join(normalize("NFKC", value).casefold().split())

    texts = [searchable(page["text"]) for page in pages]
    nodes = db.execute(select(KnowledgeNode.id, KnowledgeNode.title, KnowledgeNode.subject))
    matches = []
    for node_id, title, subject in nodes:
        label = searchable(title)
        if len(label) < 3:
            continue
        pattern = re.escape(label)
        if label.isascii():
            pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
        match = re.compile(pattern).search
        matched_pages = [index for index, text in enumerate(texts, 1) if match(text)]
        if matched_pages:
            matches.append(
                {
                    "knowledge_id": node_id,
                    "title": title,
                    "subject": subject,
                    "matched_pages": matched_pages,
                }
            )
    return sorted(matches, key=lambda item: (-len(item["matched_pages"]), item["knowledge_id"]))[
        :20
    ]


def process_one(
    factory, clock, settings=None, *, job_id: str | None = None, mock_gateway=None
) -> bool:
    """Analyze metadata and, where authorized, the temporary original."""
    now = clock()
    job = ContentFactoryJob
    query = (
        select(job.id)
        .where(
            job.kind == "analyze_source",
            or_(
                and_(job.status == "running", job.lease_until <= now),
                and_(job.status.in_(("queued", "retry_wait")), job.available_at <= now),
            ),
        )
        .order_by(job.available_at, job.id)
        .limit(1)
    )
    if job_id is not None:
        query = query.where(job.id == job_id)
    with factory.begin() as db:
        selected = db.scalar(query)
        if selected is None:
            return False
        token = claim(db, selected, now)
        if token is None:
            return False
        task = db.get_one(job, selected, with_for_update=True)
        source = (
            db.get(ContentFactorySource, task.source_id, with_for_update=True)
            if task.source_id is not None
            else None
        )
        region = task.parameters_json.get("region_code")
        now = clock()
        result = None
        if (
            source is not None
            and isinstance(region, str)
            and source_permits(db, source.id, "internal_analysis", region, now, lock=True)
        ):
            result = {
                "level": "metadata",
                "source_id": source.id,
                "title": source.title,
                "source_class": source.source_class,
                "sha256": source.sha256,
                "region_code": region,
            }
        original = None
        if (
            result is not None
            and settings is not None
            and _can_read_original(db, source.id, region, now, lock=True)
        ):
            stored = db.get(ContentFactorySourceOriginal, (source.id, region), with_for_update=True)
            if stored is not None and stored.expires_at > now:
                original = (stored.source_id, stored.content, stored.kind, stored.expires_at)
        if original is None:
            return finish(db, selected, token, now, result=result)

    source_id, data, kind, expires_at = original

    def still_authorized() -> bool:
        now = clock()
        with factory() as db:
            return (
                expires_at > now
                and db.scalar(
                    select(job.id).where(
                        job.id == selected,
                        job.status == "running",
                        job.lease_token == token,
                        job.lease_until > now,
                    )
                )
                is not None
                and source_permits(db, source_id, "internal_analysis", region, now)
                and _can_read_original(db, source_id, region, now)
            )

    try:
        pages = parse_isolated(data, kind, settings)["pages"]
        if mock_gateway is not None and not mock_gateway.external_calls_possible:
            pages = recognize_pages(
                pages,
                data,
                kind,
                settings.model_copy(update={"import_ocr_mode": "mock"}),
                mock_gateway,
                parse_isolated,
                selected,
                checkpoint=still_authorized,
            )
        result["document"] = {
            "pages": len(pages),
            "text_chars": sum(len(page["text"].strip()) for page in pages),
            "needs_ocr_pages": sum(page["method"] in {"unavailable", "ocr_mock"} for page in pages),
        }
    except DocumentParseError:
        result = None

    with factory.begin() as db:
        now = clock()
        active = db.scalar(
            select(job.id)
            .where(
                job.id == selected,
                job.status == "running",
                job.lease_token == token,
                job.lease_until > now,
            )
            .with_for_update()
        )
        if active is None:
            return False
        if (
            expires_at <= now
            or not source_permits(db, source_id, "internal_analysis", region, now, lock=True)
            or not _can_read_original(db, source_id, region, now, lock=True)
            or db.get(ContentFactorySourceOriginal, (source_id, region), with_for_update=True)
            is None
        ):
            result = None
        if result is not None:
            result["document"]["knowledge_suggestions"] = _knowledge_suggestions(db, pages)
        return finish(db, selected, token, now, result=result)


def claim(db: Session, job_id: str, now: datetime) -> str | None:
    job = ContentFactoryJob
    target = update(job).where(job.id == job_id)
    expired = and_(job.status == "running", job.lease_until <= now)
    db.execute(
        target.where(expired, job.attempts >= MAX_ATTEMPTS).values(
            status="failed", lease_token=None, lease_until=None
        )
    )
    token = new_id()
    changed = db.execute(
        target.where(
            job.attempts < MAX_ATTEMPTS,
            or_(expired, and_(job.status.in_(("queued", "retry_wait")), job.available_at <= now)),
        ).values(
            status="running", attempts=job.attempts + 1, lease_token=token, lease_until=now + LEASE
        )
    )
    return token if changed.rowcount == 1 else None


def finish(
    db: Session,
    job_id: str,
    token: str,
    now: datetime,
    *,
    result: dict[str, Any] | None = None,
    retryable: bool = False,
) -> bool:
    job = ContentFactoryJob
    if result is not None:
        status = "review_required"
    elif retryable:
        status = case((job.attempts >= MAX_ATTEMPTS, "failed"), else_="retry_wait")
    else:
        status = "failed"
    changed = db.execute(
        update(job)
        .where(
            job.id == job_id,
            job.status == "running",
            job.lease_token == token,
            job.lease_until > now,
        )
        .values(
            status=status,
            result_json=result,
            available_at=now + RETRY_DELAY,
            lease_token=None,
            lease_until=None,
        )
    )
    return changed.rowcount == 1


def cancel(db: Session, actor_id: str, job_id: str) -> bool:
    job = ContentFactoryJob
    changed = db.execute(
        update(job)
        .where(
            job.id == job_id,
            job.requested_by == actor_id,
            job.status.in_(("queued", "running", "retry_wait")),
        )
        .values(status="cancelled", lease_token=None, lease_until=None)
    )
    return changed.rowcount == 1


def cancel_owned_job(ctx: Ctx, job_id: str) -> dict:
    changed = cancel(ctx.db, ctx.actor_id, job_id)
    job = ctx.db.scalar(
        select(ContentFactoryJob)
        .where(ContentFactoryJob.id == job_id, ContentFactoryJob.requested_by == ctx.actor_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise not_found()
    if job.status != "cancelled":
        raise conflict("content_factory_job_state_conflict", "当前任务状态不允许取消")
    if changed:
        ctx.db.add(
            AuditLog(
                id=new_id(),
                actor_id=ctx.actor_id,
                action="content_factory_job_cancelled",
                target_type="cf_job",
                target_id=job_id,
                request_id=ctx.request_id,
                created_at=ctx.now(),
            )
        )
    return job_state(job)
