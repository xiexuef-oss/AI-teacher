"""只存在于本地 SQLite 原型里的表（ADR-006）。

它们不进生产迁移：真实登录由身份服务提供（Q-03），幂等键在生产环境放 Redis（docs/02）。
表名统一以 proto_ 开头，tests/migrations 会确认它们没有混进 migrations/*.sql。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, Integer, String, UniqueConstraint
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
