"""只存在于本地 SQLite 原型里的表（ADR-006）。

它们不进生产迁移：真实登录由身份服务提供（Q-03），幂等键在生产环境放 Redis（docs/02）。
表名统一以 proto_ 开头，tests/migrations 会确认它们没有混进 migrations/*.sql。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.db import Base, UTCDateTime


class LocalIdentity(Base):
    """本地身份 Mock 发放的 bearer。只保存 token 的 SHA-256。"""

    __tablename__ = "proto_local_identities"

    token_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(CHAR(36), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class IdempotencyRecord(Base):
    """非幂等动作的去重记录：同一用户、同一幂等键只执行一次，之后重放首次的响应。"""

    __tablename__ = "proto_idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_proto_idempotency"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(CHAR(36))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DocumentImportJob(Base):
    """本地导入任务；生产任务队列与留存策略另行冻结。"""

    __tablename__ = "proto_document_import_jobs"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(CHAR(36), index=True)
    title: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="uploading", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    defaults_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(String(1000))
    lease_id: Mapped[str | None] = mapped_column(CHAR(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class DocumentImportFile(Base):
    __tablename__ = "proto_document_import_files"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("proto_document_import_jobs.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16))
    media_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    # 原始文件有界保存在本地临时任务中，详情响应不带原始数据。
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    problems_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    pages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DocumentImportOcrAttempt(Base):
    """Local page dispatch metadata; recognized text stays in the expiring file workspace."""

    __tablename__ = "proto_document_import_ocr_attempts"

    file_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("proto_document_import_files.id"), primary_key=True
    )
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("proto_document_import_jobs.id"), index=True
    )
    lease_id: Mapped[str] = mapped_column(CHAR(36))
    request_digest: Mapped[str] = mapped_column(CHAR(64))
    trace_id: Mapped[str] = mapped_column(CHAR(36))
    state: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DocumentImportCandidate(Base):
    __tablename__ = "proto_document_import_candidates"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("proto_document_import_jobs.id"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    locations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confirmed_by: Mapped[str | None] = mapped_column(CHAR(36))
    question_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("questions.id"))
    error_json: Mapped[dict[str, str] | None] = mapped_column(JSON)


class DocumentImportBatch(Base):
    """批次意图先落盘，逐题结果与题目同事务；进程退出后以原幂等键恢复。"""

    __tablename__ = "proto_document_import_batches"
    key_digest: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("proto_document_import_jobs.id"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
