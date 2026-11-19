"""Fixed diagnostic plans; attempts and drafts remain in the normal solve tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.db import Base, UTCDateTime


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"
    __table_args__ = (Index("ix_diagnostic_student_created", "student_id", "created_at"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(16))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    abandoned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DiagnosticState(Base):
    __tablename__ = "diagnostic_states"

    student_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    current_run_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("diagnostic_runs.id"))


class DiagnosticItem(Base):
    __tablename__ = "diagnostic_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["question_id", "question_version"],
            ["question_versions.question_id", "question_versions.version"],
            name="fk_diagnostic_question_version",
        ),
        UniqueConstraint("session_id", name="uq_diagnostic_session"),
        UniqueConstraint("run_id", "question_id", name="uq_diagnostic_question"),
    )

    run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("diagnostic_runs.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(CHAR(36))
    question_version: Mapped[int] = mapped_column(Integer)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    session_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("study_sessions.id"))
