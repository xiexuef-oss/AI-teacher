"""Student-owned temporary scan Mock. No OCR and no draft creation."""

import base64
import binascii
from datetime import timedelta

from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select, update

from tutor_api.blob_store import BlobNotFound
from tutor_api.db import new_id
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.models import Question, QuestionVersion
from tutor_api.scan_models import ScanRecord
from tutor_api.services import media_service

NOTICE = "本地Mock未实际识别图片；请手工输入并确认题干。仅匹配已发布自编工程样题，不代表学科审校。"


def cleanup(db, value, now):
    db.execute(delete(ScanRecord).where(ScanRecord.expires_at <= now))
    db.commit()
    if value is not None:
        value.cleanup(now=now)


def store(ctx):
    if not ctx.settings.scan_mock_enabled:
        raise ApiError(501, "not_implemented", "本地拍题Mock未启用；没有实际OCR")
    value = media_service.store(ctx)
    cleanup(ctx.db, value, ctx.now())
    return value


def blob(ctx, media_id, *, uploaded=False):
    value = media_service.store(ctx)
    try:
        item = value.stat(media_id, owner=ctx.actor_id, now=ctx.now())
        if item.purpose != "ocr_source":
            raise BlobNotFound()
        if uploaded:
            value.read(media_id, owner=ctx.actor_id, now=ctx.now(), temporary=True)
        return item
    except BlobNotFound:
        raise not_found() from None


def create_upload(ctx, body):
    if body.purpose != "scan":
        raise unprocessable("purpose", "学生拍题仅允许scan用途")
    if body.size_bytes > ctx.settings.media_max_bytes:
        raise ApiError(413, "payload_too_large", "图片超过本地上限")
    item = media_service.store(ctx).reserve(
        owner=ctx.actor_id,
        purpose="ocr_source",
        mime=body.mime,
        size_bytes=body.size_bytes,
        sha256=body.sha256,
        now=ctx.now(),
        expires_at=ctx.now() + timedelta(seconds=ctx.settings.media_temporary_ttl_seconds),
    )
    return {
        "media_id": item.id,
        "upload_url": f"/api/v1/scans/uploads/{item.id}/content",
        "upload_method": "PUT",
        "expires_at": item.expires_at.isoformat(),
        "max_bytes": ctx.settings.media_max_bytes,
    }


def preview_upload(ctx, media_id):
    item = blob(ctx, media_id)
    try:
        data = media_service.store(ctx).read(
            media_id, owner=ctx.actor_id, now=ctx.now(), temporary=True
        )
    except BlobNotFound:
        raise not_found() from None
    return {
        "media_id": item.id,
        "mime": item.mime,
        "content_base64": base64.b64encode(data).decode("ascii"),
    }


def upload(ctx, media_id, body):
    item = blob(ctx, media_id)
    try:
        data = base64.b64decode(body.content_base64, validate=True)
        media_service.validate_static_image(
            data, item.mime, ctx.settings.media_max_bytes, ctx.settings.media_max_pixels
        )
        media_service.store(ctx).put(media_id, owner=ctx.actor_id, data=data, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    except (
        ValueError,
        binascii.Error,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        raise unprocessable("content_base64", "图片格式、大小或摘要不匹配") from None
    return media_service.info(item)


def create(ctx, body):
    item = blob(ctx, str(body.media_id), uploaded=True)
    id = new_id()
    payload = dict(
        id=id,
        status="needs_confirmation",
        confidence=None,
        low_confidence=True,
        stem_text="",
        expressions=[],
        matched_question_id=None,
        error_code=None,
        mock_notice=NOTICE,
    )
    ctx.db.add(
        ScanRecord(
            id=id,
            owner_id=ctx.actor_id,
            media_id=item.id,
            expires_at=item.expires_at,
            payload=payload,
        )
    )
    return payload


def owned(ctx, id):
    row = ctx.db.get(ScanRecord, id)
    if row is None or row.owner_id != ctx.actor_id or row.expires_at <= ctx.now():
        raise not_found()
    blob(ctx, row.media_id, uploaded=True)
    return row


def confirm(ctx, id, body):
    row = owned(ctx, id)
    if row.payload["status"] == "confirmed":
        raise conflict("scan_already_confirmed", "扫描已确认")
    stem = body.stem_text.strip()
    if not stem:
        raise unprocessable("stem_text", "请输入题干")
    candidates = []
    for question, version in ctx.db.execute(
        select(Question, QuestionVersion)
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Question.id)
            & (QuestionVersion.version == Question.version),
        )
        .where(Question.status == "published", Question.source_type == "self_authored")
    ):
        if version.content_json.get("stem", "").strip() == stem:
            candidates.append(question.id)
    match = candidates[0] if len(candidates) == 1 and not body.expressions else None
    payload = {
        **row.payload,
        "status": "confirmed",
        "stem_text": stem,
        "expressions": [e.model_dump() for e in body.expressions],
        "matched_question_id": match,
    }
    # A stale concurrent reader must not overwrite the first explicit confirmation.
    changed = ctx.db.execute(
        update(ScanRecord)
        .where(
            ScanRecord.id == id,
            ScanRecord.owner_id == ctx.actor_id,
            ScanRecord.expires_at > ctx.now(),
            ScanRecord.payload["status"].as_string() == "needs_confirmation",
        )
        .values(payload=payload)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise conflict("scan_already_confirmed", "扫描已确认")
    return {"scan": payload, "question_id": match, "draft_question_id": None}
