"""Bounded, read-only archive of the student's currently accessible media."""

import base64
import hashlib
import io
import json
import zipfile

from tutor_api.blob_store import (
    BlobListingTooLarge,
    BlobNotFound,
    BlobStorageUnavailable,
    _listing_visible,
)
from tutor_api.errors import ApiError
from tutor_api.schemas import StudentMediaExportOut
from tutor_api.services import media_service

MAX_OBJECTS = 1000
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024


def _too_large():
    return ApiError(413, "export_too_large", "媒体超过本次导出上限，未生成不完整档案")


def export(ctx):
    if ctx.request.query_params:
        raise ApiError(422, "invalid_export_parameters", "导出只使用当前学生身份，不接受筛选参数")
    store = media_service.store(ctx)
    metadata = dict(
        format_version=1,
        scope="server_current_student_media",
        owner_id=ctx.student_id,
        exported_at=ctx.now().isoformat(),
        history_complete=False,
        consistent_snapshot=False,
    )
    objects = []
    seen_ids = set()
    output = io.BytesIO()
    try:
        rows = store.list_owned(owner=ctx.student_id, now=ctx.now(), limit=MAX_OBJECTS)
        # ponytail: bounded in-memory ZIP; use a persisted export job for larger backups.
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for blob, state in rows:
                if not _listing_visible(
                    blob, state, ctx.student_id, ctx.now(), ctx.settings.media_max_bytes
                ):
                    raise ValueError("Media ownership or lifetime changed")
                if blob.purpose not in {"ocr_source", "handwriting"}:
                    continue
                media_id = blob.id
                if media_id in seen_ids:
                    raise ValueError("Invalid media identity or state")
                seen_ids.add(media_id)
                item = dict(
                    media_id=media_id,
                    purpose=blob.purpose,
                    mime=blob.mime,
                    size_bytes=blob.size_bytes,
                    sha256=blob.sha256,
                    expires_at=blob.expires_at.isoformat(),
                    state=state,
                    file_name=None,
                    availability="not_uploaded" if state == "reserved" else "awaiting_confirmation",
                )
                if state == "ready" or (state == "pending" and blob.purpose == "ocr_source"):
                    data = store.read(
                        media_id,
                        owner=ctx.student_id,
                        now=ctx.now(),
                        temporary=blob.purpose == "ocr_source",
                    )
                    if (
                        len(data) != blob.size_bytes
                        or hashlib.sha256(data).hexdigest() != blob.sha256
                    ):
                        raise ValueError("Media bytes do not match")
                    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
                        blob.mime, "bin"
                    )
                    name = f"media/{media_id}.{extension}"
                    if output.tell() + len(data) > MAX_ARCHIVE_BYTES:
                        raise _too_large()
                    archive.writestr(name, data)
                    item.update(file_name=name, availability="included")
                objects.append(item)
            metadata.update(objects_count=len(objects), files_count=len(archive.infolist()))
            manifest = dict(
                **metadata,
                objects=objects,
                excluded=[
                    "expired_or_deleted_media",
                    "reviewer_media",
                    "cleared_history",
                    "unsynced_device_images",
                    "credentials_and_storage_details",
                ],
            )
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            )
        content = output.getvalue()
        if len(content) > MAX_ARCHIVE_BYTES:
            raise _too_large()
    except BlobListingTooLarge:
        raise _too_large() from None
    except (BlobNotFound, BlobStorageUnavailable, OSError, ValueError, TypeError):
        raise ApiError(
            503, "export_unavailable", "媒体暂时无法完整验证，未生成不完整档案，请稍后重试"
        ) from None
    return StudentMediaExportOut(
        **metadata,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        archive_base64=base64.b64encode(content).decode("ascii"),
    )
