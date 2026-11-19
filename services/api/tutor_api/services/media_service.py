"""Local private attachments. DB visibility and replay receipts commit together."""

import base64
import binascii
import hashlib
import io
from contextlib import suppress
from datetime import datetime, timedelta

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from tutor_api.blob_store import BlobNotFound
from tutor_api.db import new_id
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.media_models import MediaAsset
from tutor_api.models import AuditLog, Question, QuestionVersion


def store(ctx):
    value = getattr(ctx.request.app.state, "media_store", None)
    if ctx.settings.env != "local" or value is None:
        raise ApiError(501, "not_implemented", "本地附件存储未启用；不连接外部对象存储")
    return value


def info(blob):
    return {
        "media_id": blob.id,
        "mime": blob.mime,
        "size_bytes": blob.size_bytes,
        "sha256": blob.sha256,
        "expires_at": blob.expires_at.isoformat(),
    }


def create_upload(ctx, body):
    value = store(ctx)
    if body.purpose != "question_attachment":
        raise ApiError(501, "not_implemented", "当前仅实现审核后台附件；拍题和手写备份尚未接入")
    if body.size_bytes > ctx.settings.media_max_bytes:
        raise ApiError(413, "payload_too_large", "媒体超过本地配置上限")
    blob = value.reserve(
        owner=ctx.actor_id,
        purpose=body.purpose,
        mime=body.mime,
        size_bytes=body.size_bytes,
        sha256=body.sha256,
        expires_at=ctx.now() + timedelta(seconds=ctx.settings.media_temporary_ttl_seconds),
        now=ctx.now(),
    )
    return {
        "media_id": blob.id,
        "upload_url": f"/api/v1/media/{blob.id}/content",
        "upload_method": "PUT",
        "expires_at": blob.expires_at.isoformat(),
        "max_bytes": ctx.settings.media_max_bytes,
    }


def validate_static_image(data, mime, max_bytes, max_pixels):
    if len(data) > max_bytes:
        raise ValueError("image_bounds")
    with Image.open(io.BytesIO(data)) as image:
        if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
            raise ValueError("animated_image")
        if image.width * image.height > max_pixels or image.format != {
            "image/png": "PNG",
            "image/jpeg": "JPEG",
            "image/webp": "WEBP",
        }.get(mime):
            raise ValueError("image_bounds")
        image.verify()


def upload(ctx, id, body):
    value = store(ctx)
    try:
        blob = value.stat(id, owner=ctx.actor_id, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    if blob.purpose != "question_attachment" or blob.mime not in {
        "image/png",
        "image/jpeg",
        "image/webp",
    }:
        raise unprocessable("media_id", "不是可上传的审核附件")
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise unprocessable("content_base64", "媒体编码无效") from None
    if len(data) > ctx.settings.media_max_bytes:
        raise ApiError(413, "payload_too_large", "媒体超过本地配置上限")
    try:
        validate_static_image(
            data, blob.mime, ctx.settings.media_max_bytes, ctx.settings.media_max_pixels
        )
        value.put(id, owner=ctx.actor_id, data=data, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise unprocessable("content_base64", "图片格式、大小或摘要不匹配") from None
    return info(blob)


def confirm(ctx, id, body):
    value = store(ctx)
    try:
        staged = value.stat(id, owner=ctx.actor_id, now=ctx.now())
        if staged.purpose != "question_attachment" or staged.mime not in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise unprocessable("media_id", "不是审核附件")
        blob = value.confirm(id, owner=ctx.actor_id, sha256=body.sha256, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    except ValueError:
        raise unprocessable("sha256", "媒体尚未上传或摘要不匹配") from None
    existing = ctx.db.get(MediaAsset, id)
    if existing is not None:
        if existing.owner_id != ctx.actor_id or existing.deleted_at is not None:
            raise not_found()
    else:
        ctx.db.add(
            MediaAsset(
                id=id,
                owner_id=ctx.actor_id,
                object_key=id,
                mime=blob.mime,
                sha256=blob.sha256,
                size_bytes=blob.size_bytes,
                purpose="question_attachment",
                created_at=ctx.now(),
                deleted_at=None,
            )
        )
    ctx.db.flush()
    return info(blob)


def owned(ctx, id):
    value = store(ctx)
    asset = ctx.db.get(MediaAsset, id)
    if asset is None or asset.owner_id != ctx.actor_id or asset.deleted_at is not None:
        raise not_found()
    try:
        value.stat(asset.object_key, owner=asset.owner_id, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    return asset


def referenced_asset(ctx, question_id, id, *, published=False):
    from tutor_api.services.review_service import _current

    question = ctx.db.scalar(_current(ctx.db, select(Question).where(Question.id == question_id)))
    if question is None or (published and question.status != "published"):
        raise not_found()
    version = ctx.db.scalar(
        _current(
            ctx.db,
            select(QuestionVersion).where(
                QuestionVersion.question_id == question_id,
                QuestionVersion.version == question.version,
            ),
        )
    )
    if version is None or id not in {
        a.get("media_id") for a in version.content_json.get("attachments", [])
    }:
        raise not_found()
    asset = ctx.db.scalar(_current(ctx.db, select(MediaAsset).where(MediaAsset.id == id)))
    if asset is None or asset.deleted_at is not None:
        raise not_found()
    return question, asset


def content(ctx, id, question_id=None):
    value = store(ctx)
    asset = owned(ctx, id) if question_id is None else referenced_asset(ctx, question_id, id)[1]
    try:
        data = value.read(asset.object_key, owner=asset.owner_id, now=ctx.now())
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            raise ValueError("image_digest")
        validate_static_image(
            data, asset.mime, ctx.settings.media_max_bytes, ctx.settings.media_max_pixels
        )
    except (
        BlobNotFound,
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ):
        raise not_found() from None
    return {
        "media_id": asset.id,
        "mime": asset.mime,
        "content_base64": base64.b64encode(data).decode(),
    }


def review_declaration(db, question, asset, actor_id, now):
    from tutor_api.services.review_service import _current

    if (
        not actor_id
        or (question.created_by is not None and question.created_by == actor_id)
        or asset.deleted_at is not None
    ):
        return False
    row = db.scalar(
        _current(
            db,
            select(AuditLog)
            .where(
                AuditLog.action == "media.review_confirmed",
                AuditLog.target_type == "question",
                AuditLog.target_id == question.id,
                AuditLog.actor_id == actor_id,
                AuditLog.detail_json["version"].as_integer() == question.version,
                AuditLog.detail_json["media_id"].as_string() == asset.id,
                AuditLog.detail_json["sha256"].as_string() == asset.sha256,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1),
        )
    )
    if row is None:
        return False
    try:
        expires = datetime.fromisoformat(row.detail_json["expires_at"])
        return expires > now
    except (ValueError, KeyError, TypeError):
        return False


def require_media_review(db, question, actor_id, now):
    from tutor_api.services.review_service import _current

    version = db.scalar(
        _current(
            db,
            select(QuestionVersion).where(
                QuestionVersion.question_id == question.id,
                QuestionVersion.version == question.version,
            ),
        )
    )
    for item in version.content_json.get("attachments", []) if version else []:
        id = item.get("media_id")
        if id is None:
            continue
        asset = db.scalar(_current(db, select(MediaAsset).where(MediaAsset.id == id)))
        if asset is None or not review_declaration(db, question, asset, actor_id, now):
            raise ApiError(
                422,
                "media_review_required",
                "须由独立审校员逐图查看并明确声明当前版本，图片删除或过期后须重新处理",
            )


def confirm_review(ctx, question_id, id, body):
    from tutor_api.services.review_service import _lock_question, require_independent

    store(ctx)
    question = _lock_question(ctx.db, question_id)
    if question is None:
        raise not_found()
    if question.version != body.expected_version:
        raise conflict("version_conflict", "题目版本已变化，请重新查看当前版本")
    if question.status not in {"draft", "reviewed"}:
        raise conflict("invalid_transition", "仅待审或已二审题目可补充当前版本的审校声明")
    require_independent(question, ctx.actor_id)
    _, asset = referenced_asset(ctx, question_id, id)
    if body.sha256 != asset.sha256:
        raise conflict("media_digest_conflict", "附件摘要已变化，请重新查看")
    content(ctx, id, question_id)  # Old files must also pass static-image validation.
    try:
        blob = store(ctx).stat(asset.object_key, owner=asset.owner_id, now=ctx.now())
    except BlobNotFound:
        raise not_found() from None
    result = {
        "question_id": question.id,
        "version": question.version,
        "media_id": id,
        "sha256": asset.sha256,
        "actor_id": ctx.actor_id,
        "expires_at": blob.expires_at.isoformat(),
    }
    ctx.db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="media.review_confirmed",
            target_type="question",
            target_id=question.id,
            detail_json=result,
            request_id=ctx.request_id,
            created_at=ctx.now(),
        )
    )
    ctx.db.flush()
    return result


def student_content(ctx, question_id, id):
    question, asset = referenced_asset(ctx, question_id, id, published=True)
    if not review_declaration(ctx.db, question, asset, question.reviewed_by, ctx.now()):
        raise not_found()
    try:
        return content(ctx, id, question_id)
    except ApiError as error:
        if error.status_code == 501:
            raise not_found() from None
        raise


def delete(ctx, id):
    value = store(ctx)
    asset = ctx.db.get(MediaAsset, id)
    if asset is None or asset.owner_id != ctx.actor_id:
        raise not_found()
    if asset.deleted_at is None:
        try:
            value.stat(asset.object_key, owner=asset.owner_id, now=ctx.now())
        except BlobNotFound:
            raise not_found() from None
        asset.deleted_at = ctx.now()
    ctx.db.flush()
    return {"media_id": id, "deleted": True}


def purge_deleted(ctx, id):
    asset = ctx.db.get(MediaAsset, id)
    if asset is not None and asset.owner_id == ctx.actor_id and asset.deleted_at is not None:
        with suppress(BlobNotFound, OSError):
            store(ctx).delete(asset.object_key, owner=asset.owner_id, now=ctx.now())


def cleanup(factory, value, now):
    if value is None:
        return 0
    with factory() as db:
        assets = list(db.scalars(select(MediaAsset)))
        for asset in assets:
            if asset.deleted_at is None:
                try:
                    value.stat(asset.object_key, owner=asset.owner_id, now=now)
                except BlobNotFound:
                    asset.deleted_at = now
        db.commit()
        for asset in assets:
            if asset.deleted_at is not None:
                with suppress(BlobNotFound, OSError):
                    value.delete(asset.object_key, owner=asset.owner_id, now=now)
    return value.cleanup(now=now)


def validate_attachments(db, actor_id, attachments, previous=()):
    from tutor_api.services.review_service import _current

    allowed = {item.get("media_id") for item in previous}
    for item in attachments:
        id = item.media_id
        if id is None:
            continue
        asset = db.scalar(_current(db, select(MediaAsset).where(MediaAsset.id == id)))
        if (
            asset is None
            or asset.deleted_at is not None
            or (asset.owner_id != actor_id and id not in allowed)
        ):
            raise unprocessable(
                "content.attachments", "新增附件必须为本人已确认的媒体；原题附件可保留"
            )
