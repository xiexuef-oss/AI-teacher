"""ORM 模型。表名、列名、长度与 migrations/001 ~ 004 保持一致（tests/migrations 对照）。

只为本切片用到的表建了模型；media_assets、question_curriculum_mappings、
model_routes 在迁移里已有结构，等对应功能实现时再加模型。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.db import Base, UTCDateTime

_ID = CHAR(36)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    email_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    learning_settings_json: Mapped[dict | None] = mapped_column(JSON)

    user_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parent_invite_revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    grade: Mapped[str | None] = mapped_column(String(8))
    # V1.2 遗留字段，仅保留兼容；新逻辑一律使用 region_code
    region: Mapped[str | None] = mapped_column(String(64))
    curriculum_version: Mapped[str | None] = mapped_column(String(32))
    region_code: Mapped[str | None] = mapped_column(String(8))
    exam_year: Mapped[int | None] = mapped_column(SmallInteger)
    exam_year_source: Mapped[str | None] = mapped_column(String(16))
    exam_scheme_code: Mapped[str | None] = mapped_column(String(32))
    subjects_json: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LearningJob(Base):
    __tablename__ = "learning_jobs"
    __table_args__ = (
        UniqueConstraint("student_id", "command_key", name="uq_learning_job_command"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    command_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    lease_token: Mapped[str | None] = mapped_column(_ID)


class LearningPackCommand(Base):
    __tablename__ = "learning_pack_commands"

    job_id: Mapped[str] = mapped_column(_ID, ForeignKey("learning_jobs.id"), primary_key=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    plan_json: Mapped[dict | None] = mapped_column(JSON)


class LearningPackOutbox(Base):
    __tablename__ = "learning_pack_outbox"
    __table_args__ = (
        Index("ix_learning_pack_outbox_pending", "delivered_at", "created_at", "job_id"),
    )

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("learning_pack_commands.job_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class LearningPackPhotoOcr(Base):
    __tablename__ = "learning_pack_photo_ocr"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("learning_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    pack_id: Mapped[str] = mapped_column(_ID, ForeignKey("learning_pack_publications.job_id"))
    code: Mapped[str] = mapped_column(CHAR(3))
    item_json: Mapped[dict] = mapped_column(JSON)
    photo_ids_json: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    candidate: Mapped[str | None] = mapped_column(Text)
    pages_json: Mapped[dict[str, str] | None] = mapped_column(JSON)


class LearningPackRenderCheckpoint(Base):
    __tablename__ = "learning_pack_render_checkpoints"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("learning_pack_commands.job_id", ondelete="CASCADE"), primary_key=True
    )
    input_sha256: Mapped[str] = mapped_column(CHAR(64))
    student_pdf: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"))
    manifest_json: Mapped[list[dict]] = mapped_column(JSON)


class SchoolMaterialCommand(Base):
    __tablename__ = "school_material_commands"

    job_id: Mapped[str] = mapped_column(_ID, ForeignKey("learning_jobs.id"), primary_key=True)
    media_id: Mapped[str] = mapped_column(_ID)


class SchoolMaterialResult(Base):
    __tablename__ = "school_material_results"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("school_material_commands.job_id"), primary_key=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    pages_json: Mapped[list] = mapped_column(JSON)


class SchoolMaterialCorrection(Base):
    __tablename__ = "school_material_corrections"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("school_material_results.job_id", ondelete="CASCADE"), primary_key=True
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SchoolMaterialConfirmation(Base):
    __tablename__ = "school_material_confirmations"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("school_material_results.job_id", ondelete="CASCADE"), primary_key=True
    )
    source_revision: Mapped[str] = mapped_column(String(64), primary_key=True)
    items_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LearningPackPublication(Base):
    __tablename__ = "learning_pack_publications"

    job_id: Mapped[str] = mapped_column(_ID, ForeignKey("learning_jobs.id"), primary_key=True)
    student_pdf: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"))
    solution_pdf: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"))
    manifest_json: Mapped[dict] = mapped_column(JSON)


class LearningPackReturn(Base):
    __tablename__ = "learning_pack_returns"

    job_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("learning_pack_publications.job_id"), primary_key=True
    )
    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    question_version_id: Mapped[str] = mapped_column(_ID, ForeignKey("question_versions.id"))
    transcript: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LearningPackReturnPhotos(Base):
    __tablename__ = "learning_pack_return_photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "code"], ["learning_pack_returns.job_id", "learning_pack_returns.code"]
        ),
    )

    job_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    media_ids_json: Mapped[list[str]] = mapped_column(JSON)


class LearningPackReturnDetails(Base):
    __tablename__ = "learning_pack_return_details"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "code"], ["learning_pack_returns.job_id", "learning_pack_returns.code"]
        ),
    )

    job_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    completed_on: Mapped[date | None] = mapped_column(Date)
    independence: Mapped[str] = mapped_column(String(16))


class LearningPackCorrection(Base):
    __tablename__ = "learning_pack_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "code"], ["learning_pack_returns.job_id", "learning_pack_returns.code"]
        ),
    )

    job_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    corrected_at: Mapped[datetime] = mapped_column(UTCDateTime)


class WeeklyReportSnapshot(Base):
    __tablename__ = "weekly_report_snapshots"

    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary_json: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (UniqueConstraint("subject", "code", name="uq_knowledge_subject_code"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    subject: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("prereq_id", "target_id", name="uq_knowledge_edge"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    prereq_id: Mapped[str] = mapped_column(_ID, ForeignKey("knowledge_nodes.id"))
    target_id: Mapped[str] = mapped_column(_ID, ForeignKey("knowledge_nodes.id"))


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_delivery", "status", "subject", "answer_mode"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    subject: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(24))
    answer_mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    grade: Mapped[str | None] = mapped_column(String(8))
    source_type: Mapped[str] = mapped_column(String(24))
    source_category: Mapped[str] = mapped_column(String(16))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_year: Mapped[int | None] = mapped_column(SmallInteger)
    source_license: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(500))
    variant_of_id: Mapped[str | None] = mapped_column(_ID, ForeignKey("questions.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(_ID)
    reviewed_by: Mapped[str | None] = mapped_column(_ID)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class QuestionVersion(Base):
    __tablename__ = "question_versions"
    __table_args__ = (UniqueConstraint("question_id", "version", name="uq_question_version"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    version: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    teaching_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(_ID)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class QuestionKnowledge(Base):
    __tablename__ = "question_knowledge"

    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(
        _ID, ForeignKey("knowledge_nodes.id"), primary_key=True
    )


class Solution(Base):
    __tablename__ = "solutions"
    __table_args__ = (UniqueConstraint("question_id", "version", "kind", name="uq_solution"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    conditions_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(_ID)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Rubric(Base):
    __tablename__ = "rubrics"
    __table_args__ = (UniqueConstraint("question_id", "version", name="uq_rubric"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    version: Mapped[int] = mapped_column(Integer)
    rubric_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StudySession(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        Index("ix_sessions_student_created", "student_id", "created_at"),
        Index("ix_sessions_student_question", "student_id", "question_id"),
        Index("ix_sessions_review_owner", "student_id", "review_item_id", "id"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    question_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    origin: Mapped[str] = mapped_column(String(16))
    review_item_id: Mapped[str | None] = mapped_column(_ID)
    parent_session_id: Mapped[str | None] = mapped_column(_ID)
    assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    used_solution: Mapped[bool] = mapped_column(Boolean, default=False)
    independent_ended: Mapped[bool] = mapped_column(Boolean, default=False)
    hint_level_revealed: Mapped[int] = mapped_column(Integer, default=0)
    confused_streak: Mapped[int] = mapped_column(Integer, default=0)
    needs_human_help: Mapped[bool] = mapped_column(Boolean, default=False)
    region_code_snapshot: Mapped[str | None] = mapped_column(String(8))
    exam_year_snapshot: Mapped[int | None] = mapped_column(SmallInteger)
    exam_scheme_code_snapshot: Mapped[str | None] = mapped_column(String(32))
    curriculum_version_snapshot: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "attempt_no", name="uq_attempt_no"),
        UniqueConstraint("session_id", "submission_no", name="uq_attempt_submission"),
        UniqueConstraint("request_id", name="uq_attempt_request"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    session_id: Mapped[str] = mapped_column(_ID, ForeignKey("study_sessions.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    submission_no: Mapped[int | None] = mapped_column(Integer)
    copied_from_attempt_id: Mapped[str | None] = mapped_column(
        _ID, ForeignKey("attempts.id", name="fk_attempt_copy_source")
    )
    copied_from_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    answer_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    used_solution: Mapped[bool] = mapped_column(Boolean, default=False)
    independent: Mapped[bool | None] = mapped_column(Boolean)
    evaluation_state: Mapped[str | None] = mapped_column(String(16))
    outcome: Mapped[str | None] = mapped_column(String(24))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    evaluation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 提交所用幂等键的摘要（按用户加盐），保证同一次提交只落一次评估
    request_id: Mapped[str | None] = mapped_column(String(128))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class HandwritingDraft(Base):
    __tablename__ = "handwriting_drafts"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_draft_attempt"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(_ID, ForeignKey("attempts.id"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    strokes_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    media_key: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AttemptSelfCheck(Base):
    """解答题提交后，学生对照要点做的自查（PRD P0 第 3、4 条，migrations/003）。

    一份作答至多一行，改了整体替换。只记每个要点"做到 / 做到一部分 / 没做到"：不折算成分数，
    不进任何正确率。要点本身不存在这里，按作答所属会话固定的题目版本去 rubrics 里取。
    """

    __tablename__ = "attempt_self_checks"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_self_check_attempt"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(_ID, ForeignKey("attempts.id"))
    marks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ParentStudentLink(Base):
    """家长与学生的绑定（docs/04：仅明确授权、可撤销；PRD P0 第 8 条，migrations/001）。

    授权是学生做的（生成邀请码），家长输入之后才有这一行。撤销后立即失去访问权限：所有读取都要带
    `revoked_at IS NULL`。同一对家长和学生只有一行——重新授权时重新打开它，`consent_at`、`created_at` 都换成这一次的。
    """

    __tablename__ = "parent_student_links"
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_parent_student"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    authorization_revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    parent_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    consent_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ParentInvite(Base):
    """学生生成的一次性家长邀请码（PRD P0 第 8 条，migrations/004）。只存哈希，明文只在创建时返回一次。"""

    __tablename__ = "parent_invites"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_parent_invite_code"),
        Index("ix_parent_invites_student", "student_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(CHAR(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    redeemed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    redeemed_by: Mapped[str | None] = mapped_column(_ID, ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TutorEventRow(Base):
    __tablename__ = "tutor_events"
    __table_args__ = (UniqueConstraint("session_id", "seq_no", name="uq_event_seq"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    session_id: Mapped[str] = mapped_column(_ID, ForeignKey("study_sessions.id"))
    seq_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(24))
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("student_id", "question_id", name="uq_review_student_question"),
        Index("ix_review_due", "student_id", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    stage: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_result: Mapped[str | None] = mapped_column(String(16))
    last_attempt_id: Mapped[str | None] = mapped_column(_ID)
    origin_session_id: Mapped[str | None] = mapped_column(_ID)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ReviewCompletionRecord(Base):
    """Durable first-submission evidence; legacy unknowns never invent outcomes."""

    __tablename__ = "review_completion_history"

    review_id: Mapped[str] = mapped_column(_ID, ForeignKey("review_items.id"), primary_key=True)
    first_attempt_id: Mapped[str] = mapped_column(_ID, ForeignKey("attempts.id"), primary_key=True)
    student_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id"))
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    state: Mapped[str] = mapped_column(String(24))
    result: Mapped[str | None] = mapped_column(String(16))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_target", "target_type", "target_id"),
        Index("ix_audit_actor", "actor_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(_ID)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(48))
    target_id: Mapped[str | None] = mapped_column(_ID)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ExamRegionRule(Base):
    __tablename__ = "exam_region_rules"
    __table_args__ = (
        UniqueConstraint(
            "region_code",
            "exam_year",
            "subject",
            "scheme_code",
            "version",
            name="uq_exam_region_rule",
        ),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(8))
    exam_year: Mapped[int] = mapped_column(SmallInteger)
    subject: Mapped[str] = mapped_column(String(16))
    scheme_code: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    effective_from: Mapped[date | None] = mapped_column(Date)
    official_source: Mapped[str | None] = mapped_column(String(500))
    official_source_url: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(_ID)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class QuestionRegionApplicability(Base):
    __tablename__ = "question_region_applicability"
    __table_args__ = (
        UniqueConstraint("question_id", "recommended_region_code", name="uq_question_region"),
        Index("ix_qra_region", "recommended_region_code", "review_status"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    question_id: Mapped[str] = mapped_column(_ID, ForeignKey("questions.id"))
    origin_region_code: Mapped[str | None] = mapped_column(String(8))
    recommended_region_code: Mapped[str] = mapped_column(String(8))
    exam_year_from: Mapped[int | None] = mapped_column(SmallInteger)
    exam_year_to: Mapped[int | None] = mapped_column(SmallInteger)
    review_status: Mapped[str] = mapped_column(String(16), default="draft")
    note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(_ID)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ModelCallAudit(Base):
    __tablename__ = "model_call_audits"
    __table_args__ = (
        Index("ix_model_audit_created", "created_at"),
        Index("ix_model_audit_request", "request_id"),
        Index("ix_model_audit_student", "student_pseudonym", "created_at"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128))
    trace_id: Mapped[str] = mapped_column(String(64))
    student_pseudonym: Mapped[str] = mapped_column(String(64))
    task_type: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(48))
    provider_calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    image_units: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    schema_valid: Mapped[bool | None] = mapped_column(Boolean)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ModelBudgetUsage(Base):
    __tablename__ = "model_budget_usage"
    __table_args__ = (UniqueConstraint("scope", "scope_key", "usage_date", name="uq_model_budget"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str] = mapped_column(String(64))
    usage_date: Mapped[date] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class IdempotencyReceipt(Base):
    """业务事务内的正式回执；reserved只能存在于未提交事务中。"""

    __tablename__ = "idempotency_receipts"
    __table_args__ = (UniqueConstraint("actor_id", "key_digest", name="uq_receipt_actor_key"),)
    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    actor_id: Mapped[str] = mapped_column(_ID)
    key_digest: Mapped[str] = mapped_column(CHAR(64))
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    state: Mapped[str] = mapped_column(String(16))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
