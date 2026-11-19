"""Private media metadata mapped to the existing 001 media_assets table."""

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.db import Base, UTCDateTime


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_media_object_key"),
        Index("ix_media_owner", "owner_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"))
    object_key: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(CHAR(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    purpose: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
