import base64
import binascii
from datetime import datetime, timedelta
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from tutor_api.deps import Ctx
from tutor_api.errors import ApiError, not_found, unprocessable
from tutor_api.models import (
    ContentFactorySource,
    ContentFactorySourceOriginal,
    ContentFactorySourcePermission,
)
from tutor_api.schemas import DocImportUploadIn, RegionCode
from tutor_api.services.document_import_service import detect_kind


class OriginalUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=256)
    content_base64: str = Field(min_length=4, max_length=22_369_624)
    region_code: RegionCode

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        return DocImportUploadIn.safe_display_filename(value)


def upload_original(ctx: Ctx, source_id: str, request: OriginalUpload) -> dict[str, str]:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise unprocessable("content_base64", "文件编码无效") from None
    original = store_original(ctx, source_id, request.region_code, request.filename, content)
    return {
        "source_id": original.source_id,
        "region_code": original.region_code,
        "expires_at": original.expires_at.isoformat(),
    }


def store_original(
    ctx: Ctx, source_id: str, region_code: str, filename: str, content: bytes
) -> ContentFactorySourceOriginal:
    db = ctx.db
    now = ctx.now()
    if db.get_bind().dialect.name == "sqlite":
        db.execute(
            update(ContentFactorySource)
            .where(ContentFactorySource.id == source_id)
            .values(title=ContentFactorySource.title)
        )
    source = db.get(ContentFactorySource, source_id, with_for_update=True)
    if source is None or source.created_by != ctx.actor_id:
        raise not_found()
    permit = db.get(
        ContentFactorySourcePermission,
        (source_id, "store_original", region_code),
        with_for_update=True,
    )
    if (
        permit is None
        or permit.revoked_at is not None
        or not permit.valid_from <= now < permit.valid_until
    ):
        raise ApiError(403, "forbidden", "题源在所选地区缺少有效的原件留存许可")
    if not content or len(content) > ctx.settings.import_max_file_bytes:
        raise unprocessable("content_base64", "单个文件超过大小限制或为空")
    if sha256(content).hexdigest() != source.sha256:
        raise unprocessable("content_base64", "文件摘要与题源登记不一致")
    kind = detect_kind(filename, content, ctx.settings)
    original = ContentFactorySourceOriginal(
        source_id=source_id,
        region_code=region_code,
        kind=kind,
        content=content,
        expires_at=min(
            permit.valid_until, now + timedelta(minutes=ctx.settings.import_temporary_ttl_minutes)
        ),
    )
    return db.merge(original)


def purge_expired(db: Session, now: datetime) -> int:
    original = ContentFactorySourceOriginal
    return db.execute(delete(original).where(original.expires_at <= now)).rowcount
