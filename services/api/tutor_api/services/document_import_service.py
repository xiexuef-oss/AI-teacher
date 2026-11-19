"""本地文档导入工作区。原始文件临时存于 proto_ 表，不进入正式题库。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import zipfile
from datetime import UTC, timedelta
from pathlib import PurePosixPath

from sqlalchemy import delete, select, update

from tutor_api.db import new_id
from tutor_api.deps import Ctx
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.models import AuditLog
from tutor_api.proto_models import (
    DocumentImportBatch,
    DocumentImportCandidate,
    DocumentImportFile,
    DocumentImportJob,
    DocumentImportOcrAttempt,
    IdempotencyRecord,
)
from tutor_api.schemas import DocImportCandidatesEditIn, DocImportJobCreateIn, DocImportUploadIn
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.review_service import check_import_source

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "json": "application/json",
}


def options(settings, now) -> dict:
    now = now.astimezone(UTC).replace(microsecond=now.microsecond // 1000 * 1000)
    return {
        "server_time": now.isoformat(timespec="milliseconds"),
        "creation_deadline": (
            now + timedelta(minutes=settings.import_temporary_ttl_minutes)
        ).isoformat(timespec="milliseconds"),
        "max_file_bytes": settings.import_max_file_bytes,
        "max_job_bytes": settings.import_max_job_bytes,
        "max_files": settings.import_max_files,
        "max_pages": settings.import_max_pages,
        "max_candidates": settings.import_max_candidates,
        "temporary_ttl_minutes": settings.import_temporary_ttl_minutes,
        "file_kinds": list(_MIME),
        "ocr_mode": settings.import_ocr_mode,
        "doc_converter_available": bool(
            settings.import_doc_converter and settings.import_doc_converter.is_file()
        ),
    }


def owned_job(ctx: Ctx, job_id: str) -> DocumentImportJob:
    job = ctx.db.get(DocumentImportJob, job_id)
    if job is None or job.actor_id != ctx.actor_id or job.expires_at <= ctx.now():
        raise not_found()
    return job


def job_files(db, job_id: str) -> list[DocumentImportFile]:
    files = list(
        db.scalars(
            select(DocumentImportFile)
            .where(DocumentImportFile.job_id == job_id)
            .order_by(DocumentImportFile.created_at, DocumentImportFile.id)
        )
    )
    uploads = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.target_id == job_id, AuditLog.action == "document_import.upload"
            )
        )
    )
    positions = {}
    for entry in uploads:
        detail = entry.detail_json or {}
        if detail.get("file_id") in positions:
            positions[detail["file_id"]] = None
        else:
            positions[detail.get("file_id")] = detail.get("revision")
    known = all(isinstance(positions.get(file.id), int) for file in files) and len(
        {positions.get(file.id) for file in files}
    ) == len(files)
    if known:
        files.sort(key=lambda file: positions[file.id])
    for file in files:
        file._upload_order_known = known
    return files


def job_candidates(db, job_id: str) -> list[DocumentImportCandidate]:
    return list(
        db.scalars(
            select(DocumentImportCandidate)
            .where(DocumentImportCandidate.job_id == job_id)
            .order_by(DocumentImportCandidate.ordinal, DocumentImportCandidate.id)
        )
    )


def summary(db, job: DocumentImportJob) -> dict:
    files, candidates = job_files(db, job.id), job_candidates(db, job.id)
    return {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "revision": job.revision,
        "file_count": len(files),
        "processed_files": sum(f.status not in {"pending", "processing"} for f in files),
        "candidate_count": len(candidates),
        "confirmed_count": sum(c.confirmed_by is not None for c in candidates),
        "imported_count": sum(c.question_id is not None for c in candidates),
        "failed_count": sum(f.status == "failed" for f in files)
        + sum(c.error_json is not None for c in candidates),
        "message": job.message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "expires_at": job.expires_at.isoformat(),
    }


def file_view(file: DocumentImportFile) -> dict:
    return {
        "id": file.id,
        "filename": file.filename,
        "kind": file.kind,
        "media_type": file.media_type,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "status": file.status,
        "problems": file.problems_json,
        "pages": file.pages_json,
        "original_available": file.content is not None,
    }


def candidate_view(candidate: DocumentImportCandidate) -> dict:
    return {
        "id": candidate.id,
        "title": candidate.title,
        "text": candidate.text,
        "locations": candidate.locations_json,
        "warnings": candidate.warnings_json,
        "payload": candidate.payload_json,
        "confirmed": candidate.confirmed_by is not None,
        "confirmed_by": candidate.confirmed_by,
        "question_id": candidate.question_id,
        "error": candidate.error_json,
    }


def detail(ctx: Ctx, job_id: str) -> dict:
    job = owned_job(ctx, job_id)
    return {
        "job": summary(ctx.db, job),
        "defaults": job.defaults_json,
        "files": [file_view(f) for f in job_files(ctx.db, job.id)],
        "candidates": [candidate_view(c) for c in job_candidates(ctx.db, job.id)],
    }


def list_jobs(ctx: Ctx, cursor: str | None, limit: int) -> dict:
    try:
        offset = int(cursor or "0")
        if offset < 0 or offset > 1_000_000:
            raise ValueError()
    except ValueError:
        raise unprocessable("cursor", "分页游标无效") from None
    rows = list(
        ctx.db.scalars(
            select(DocumentImportJob)
            .where(
                DocumentImportJob.actor_id == ctx.actor_id, DocumentImportJob.expires_at > ctx.now()
            )
            .order_by(DocumentImportJob.created_at.desc(), DocumentImportJob.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "items": [summary(ctx.db, job) for job in rows[:limit]],
        "next_cursor": str(offset + limit) if len(rows) > limit else None,
    }


def audit(ctx: Ctx, job: DocumentImportJob, action: str, extra: dict | None = None) -> None:
    ctx.db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="document_import." + action,
            target_type="document_import",
            target_id=job.id,
            detail_json={"revision": job.revision, **(extra or {})},
            request_id=ctx.request_id,
            created_at=ctx.now(),
        )
    )


def create_job(ctx: Ctx, body: DocImportJobCreateIn) -> dict:
    check_import_source(body.defaults.source)
    if not body.title.strip():
        raise unprocessable("title", "任务名称不能为空")
    # Receipt lookup precedes this action. Acquire the prototype SQLite write lock
    # before reading wall time: a request waiting for another writer must not use
    # a timestamp captured before its fixed creation window expired.
    ctx.db.execute(
        update(DocumentImportJob)
        .where(DocumentImportJob.id == "")
        .values(revision=DocumentImportJob.revision)
    )
    now = ctx.now()
    now = now.astimezone(UTC).replace(microsecond=now.microsecond // 1000 * 1000)
    if body.creation_deadline <= now:
        raise ApiError(410, "import_creation_window_expired", "创建窗口已过期，请明确开始新的导入")
    if body.creation_deadline > now + timedelta(minutes=ctx.settings.import_temporary_ttl_minutes):
        raise unprocessable("creation_deadline", "创建期限超出当前服务端窗口")
    job = DocumentImportJob(
        id=new_id(),
        actor_id=ctx.actor_id,
        title=body.title.strip(),
        status="uploading",
        revision=1,
        defaults_json=body.defaults.model_dump(),
        created_at=now,
        updated_at=now,
        expires_at=body.creation_deadline,
    )
    ctx.db.add(job)
    ctx.db.flush()
    audit(ctx, job, "create")
    return summary(ctx.db, job)


def advance(ctx: Ctx, job: DocumentImportJob, revision: int) -> None:
    result = ctx.db.execute(
        update(DocumentImportJob)
        .where(DocumentImportJob.id == job.id, DocumentImportJob.revision == revision)
        .values(revision=revision + 1, updated_at=ctx.now())
    )
    if result.rowcount != 1:
        raise conflict("import_revision_conflict", "任务已更新，请刷新后再操作")


def require_state(job: DocumentImportJob, allowed: set[str]) -> None:
    if job.status not in allowed:
        raise conflict("invalid_transition", "当前任务状态不允许此操作", {"status": job.status})


def detect_kind(filename: str, data: bytes, settings) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower()
    kind = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    valid = False
    if kind == "pdf":
        valid = data.startswith(b"%PDF-")
    elif kind == "png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif kind == "jpeg":
        valid = data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
    elif kind == "doc":
        valid = data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif kind == "json":
        try:
            valid = data.decode("utf-8-sig").lstrip().startswith(("{", "["))
        except UnicodeDecodeError:
            valid = False
    elif kind == "docx" and data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries = z.infolist()
                valid = (
                    "word/document.xml" in z.namelist()
                    and "[Content_Types].xml" in z.namelist()
                    and len(entries) <= 2000
                    and sum(e.file_size for e in entries) <= settings.import_max_unpacked_bytes
                    and all(
                        ".." not in PurePosixPath(e.filename).parts
                        and not e.filename.startswith(("/", "\\"))
                        for e in entries
                    )
                )
        except (zipfile.BadZipFile, ValueError):
            valid = False
    if not valid or kind not in _MIME:
        raise unprocessable("filename", "文件格式不支持，或扩展名与文件内容不一致")
    return kind


def upload(ctx: Ctx, job_id: str, body: DocImportUploadIn) -> dict:
    job = owned_job(ctx, job_id)
    require_state(job, {"uploading"})
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise unprocessable("content_base64", "文件编码无效") from None
    if not data or len(data) > ctx.settings.import_max_file_bytes:
        raise unprocessable("content_base64", "单个文件超过大小限制或为空")
    files = job_files(ctx.db, job.id)
    if (
        len(files) >= ctx.settings.import_max_files
        or sum(f.size_bytes for f in files) + len(data) > ctx.settings.import_max_job_bytes
    ):
        raise unprocessable("content_base64", "任务的文件数量或总大小超过限制")
    kind = detect_kind(body.filename, data, ctx.settings)
    advance(ctx, job, body.expected_revision)
    file = DocumentImportFile(
        id=new_id(),
        job_id=job.id,
        filename=body.filename,
        kind=kind,
        media_type=_MIME[kind],
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content=data,
        status="pending",
        problems_json=[],
        pages_json=[],
        created_at=ctx.now(),
    )
    ctx.db.add(file)
    audit(ctx, job, "upload", {"file_id": file.id, "size_bytes": len(data)})
    ctx.db.flush()
    return {"job": summary(ctx.db, job), "file": file_view(file)}


def owned_file(ctx: Ctx, job_id: str, file_id: str) -> DocumentImportFile:
    job = owned_job(ctx, job_id)
    file = ctx.db.get(DocumentImportFile, file_id)
    if file is None or file.job_id != job.id:
        raise not_found()
    return file


def original(ctx: Ctx, job_id: str, file_id: str) -> dict:
    file = owned_file(ctx, job_id, file_id)
    if file.content is None:
        raise not_found()
    return {
        "filename": file.filename,
        "media_type": file.media_type,
        "content_base64": base64.b64encode(file.content).decode("ascii"),
    }


def enqueue(ctx: Ctx, job_id: str, revision: int) -> dict:
    job = owned_job(ctx, job_id)
    require_state(job, {"uploading"})
    if not job_files(ctx.db, job.id):
        raise unprocessable("files", "请先上传至少一个文件")
    advance(ctx, job, revision)
    job.status = "queued"
    job.message = "等待本地文档导入工作器处理"
    audit(ctx, job, "enqueue")
    ctx.db.flush()
    return summary(ctx.db, job)


def cancel(ctx: Ctx, job_id: str, revision: int) -> dict:
    job = owned_job(ctx, job_id)
    require_state(
        job, {"uploading", "queued", "processing", "needs_review", "partial_failure", "failed"}
    )
    advance(ctx, job, revision)
    job.status, job.message = "cancelled", "已取消尚未完成的工作，已导入的题目保持不变"
    job.lease_id = job.lease_until = None
    for file in job_files(ctx.db, job.id):
        if file.status in {"pending", "processing"}:
            file.status = "cancelled"
    audit(ctx, job, "cancel")
    ctx.db.flush()
    return summary(ctx.db, job)


def preview(ctx: Ctx, job_id: str, file_id: str, page: int, media_index: int | None = None) -> dict:
    file = owned_file(ctx, job_id, file_id)
    if file.content is None:
        raise not_found()
    try:
        result = parse_isolated(
            file.content, file.kind, ctx.settings, page=page, media_index=media_index
        )
    except DocumentParseError as error:
        raise unprocessable("page", f"{error.code}: {error.message}") from error
    return {
        "filename": f"preview-{page}.png",
        "media_type": "image/png",
        "content_base64": result["png"],
    }


def cleanup_expired(db, now) -> int:
    """清除过期本地工作区及原文件，不删除已经导入题库的题目；调用方提交。"""
    ids = list(db.scalars(select(DocumentImportJob.id).where(DocumentImportJob.expires_at <= now)))
    if ids:
        expired = set(ids)
        # 幂等响应也可能含提取文字/校对内容，不能在工作区到期后留下旁路副本。
        for record in db.scalars(select(IdempotencyRecord)):
            data = record.response_json.get("data", {})
            if isinstance(data, dict):
                nested = data.get("job")
                identifier = nested.get("id") if isinstance(nested, dict) else data.get("id")
                if identifier in expired:
                    db.delete(record)
        db.execute(delete(DocumentImportOcrAttempt).where(DocumentImportOcrAttempt.job_id.in_(ids)))
        db.execute(delete(DocumentImportBatch).where(DocumentImportBatch.job_id.in_(ids)))
        db.execute(delete(DocumentImportCandidate).where(DocumentImportCandidate.job_id.in_(ids)))
        db.execute(delete(DocumentImportFile).where(DocumentImportFile.job_id.in_(ids)))
        db.execute(delete(DocumentImportJob).where(DocumentImportJob.id.in_(ids)))
    return len(ids)


def edit_candidates(ctx: Ctx, job_id: str, body: DocImportCandidatesEditIn) -> dict:
    job = owned_job(ctx, job_id)
    require_state(job, {"needs_review", "partial_failure", "failed"})
    if ctx.db.scalar(
        select(DocumentImportBatch.key_digest).where(
            DocumentImportBatch.job_id == job_id, DocumentImportBatch.completed.is_(False)
        )
    ):
        raise conflict("batch_in_progress", "请先用原幂等键恢复未完成的批次，或取消任务")
    if len(body.items) > ctx.settings.import_max_candidates:
        raise unprocessable("items", "候选题数量超过限制")
    existing = {item.id: item for item in job_candidates(ctx.db, job_id)}
    files = {file.id: file for file in job_files(ctx.db, job_id)}
    retained = [item.id for item in body.items if item.id is not None]
    if len(set(retained)) != len(retained) or any(id not in existing for id in retained):
        raise unprocessable("items", "候选题 ID 重复或不属于当前任务")
    if any(item.question_id is not None and id not in retained for id, item in existing.items()):
        raise unprocessable("items", "已经导入的候选题不能删除")
    for item in body.items:
        previous = existing.get(item.id)
        if previous is not None and previous.question_id is not None:
            view = candidate_view(previous)
            if item.model_dump(mode="json", exclude_unset=True) != {
                key: view[key] for key in type(item).model_fields
            }:
                raise unprocessable("items", "已经导入的候选题不能修改，请到草稿编辑页操作")
        for location in item.locations:
            file = files.get(location.file_id)
            if file is None or location.page not in {page["number"] for page in file.pages_json}:
                raise unprocessable("locations", "原文定位不属于当前任务或页/片段不存在")
        if item.confirmed:
            if item.payload is None or not item.text.strip():
                raise unprocessable("confirmed", "确认前请补齐结构化题目和题面")
            if item.payload.question.content.stem != item.text:
                raise unprocessable("payload", "结构化题面与校对文本不一致，请同步修正")
            check_import_source(item.payload.source)
    advance(ctx, job, body.expected_revision)
    for id, previous in existing.items():
        if id not in retained:
            ctx.db.delete(previous)
    for index, item in enumerate(body.items):
        previous = existing.get(item.id)
        if previous is not None and previous.question_id is not None:
            continue
        candidate = previous or DocumentImportCandidate(
            id=new_id(), job_id=job_id, warnings_json=[]
        )
        candidate.ordinal, candidate.title, candidate.text = index, item.title, item.text
        candidate.locations_json = [location.model_dump() for location in item.locations]
        candidate.payload_json = (
            item.payload.model_dump(mode="json", exclude_unset=True) if item.payload else None
        )
        candidate.confirmed_by = ctx.actor_id if item.confirmed else None
        candidate.error_json = None
        ctx.db.add(candidate)
    audit(ctx, job, "edit_candidates", {"count": len(body.items)})
    ctx.db.flush()
    return detail(ctx, job_id)
