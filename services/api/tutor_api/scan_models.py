"""Local-only temporary scan state; never a question draft."""

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.db import Base, UTCDateTime


class ScanRecord(Base):
    __tablename__ = "proto_scan_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    media_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict] = mapped_column(JSON)
