"""Read-only, bounded export of the authenticated student's learning records."""

from uuid import UUID

from sqlalchemy import select

from ai_gateway.budget import STUDENT_SCOPE
from tutor_api.diagnostic_models import DiagnosticItem, DiagnosticRun
from tutor_api.errors import ApiError
from tutor_api.gateway_io import pseudonym
from tutor_api.models import (
    Attempt,
    AttemptSelfCheck,
    HandwritingDraft,
    ModelBudgetUsage,
    ModelCallAudit,
    ParentInvite,
    ParentStudentLink,
    ReviewCompletionRecord,
    ReviewItem,
    StudySession,
    TutorEventRow,
)
from tutor_api.schemas import (
    ExportLearningSessionOut,
    ExportModelBudgetDayOut,
    ExportModelCallOut,
    ExportModelUsageOut,
    ExportParentAccessInviteOut,
    ExportParentAccessLinkOut,
    ExportParentAccessRecordsOut,
    ExportReviewHistoryOut,
    ExportScanPayloadOut,
    ExportSelfCheckOut,
    ExportStoredScanOut,
    StudentLearningExportOut,
)
from tutor_api.services import (
    diagnostic_service,
    events,
    profile_service,
    review_scheduler,
    session_service,
)

MAX_RECORDS = 10_000
MAX_BYTES = 32 * 1024 * 1024


def _stored_scans(ctx, rows):
    if ctx.settings.env != "local":
        return None
    from tutor_api.scan_models import ScanRecord

    result = []
    for row in rows(
        select(ScanRecord)
        .where(ScanRecord.owner_id == ctx.student_id)
        .order_by(ScanRecord.expires_at, ScanRecord.id)
    ):
        try:
            value = ExportScanPayloadOut.model_validate(row.payload)
            if value.id != UUID(row.id):
                raise ValueError("Stored scan identity mismatch")
            result.append(
                ExportStoredScanOut(
                    media_id=row.media_id,
                    expires_at=row.expires_at,
                    scan=value.model_dump(mode="json", exclude_defaults=True),
                )
            )
        except (ValueError, TypeError):
            raise ApiError(
                503, "export_unavailable", "部分学习记录暂时无法验证，未生成不完整导出，请稍后重试"
            ) from None
    return result


def export(ctx):
    if ctx.request.query_params:
        raise ApiError(422, "invalid_export_parameters", "导出只使用当前学生身份，不接受筛选参数")
    connection = ctx.db.connection()
    # sqlite3 legacy transaction control does not BEGIN for SELECT. Keep every
    # section on one WAL snapshot while other devices continue to write.
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN")
    remaining = MAX_RECORDS

    def rows(statement):
        nonlocal remaining
        result = list(ctx.db.scalars(statement.limit(remaining + 1)))
        remaining -= len(result)
        if remaining < 0:
            raise ApiError(413, "export_too_large", "学习记录超过本次导出上限，未生成不完整文件")
        return result

    owned = StudySession.student_id == ctx.student_id
    sessions = []
    for session in rows(
        select(StudySession).where(owned).order_by(StudySession.created_at, StudySession.id)
    ):
        attempts = rows(
            select(Attempt)
            .join(StudySession)
            .where(owned, Attempt.session_id == session.id)
            .order_by(Attempt.attempt_no)
        )
        drafts = rows(
            select(HandwritingDraft)
            .join(Attempt)
            .join(StudySession)
            .where(owned, Attempt.session_id == session.id)
            .order_by(HandwritingDraft.attempt_id)
        )
        by_id = {attempt.id: attempt for attempt in attempts}
        checks = rows(
            select(AttemptSelfCheck)
            .join(Attempt)
            .join(StudySession)
            .where(owned, Attempt.session_id == session.id)
            .order_by(AttemptSelfCheck.attempt_id)
        )
        event_rows = rows(
            select(TutorEventRow)
            .join(StudySession)
            .where(owned, TutorEventRow.session_id == session.id)
            .order_by(TutorEventRow.seq_no)
        )
        for row in event_rows:
            events._validator().validate(row.event_json)
        sessions.append(
            ExportLearningSessionOut(
                session=session_service.serialize_session(ctx.db, session),
                attempts=[
                    session_service.serialize_attempt(ctx.db, attempt) for attempt in attempts
                ],
                drafts=[
                    session_service.serialize_draft(by_id[draft.attempt_id], draft)
                    for draft in drafts
                ],
                self_checks=[
                    ExportSelfCheckOut(
                        attempt_id=check.attempt_id,
                        marks=check.marks_json,
                        saved_at=check.updated_at,
                    )
                    for check in checks
                ],
                events=[row.event_json for row in event_rows],
            )
        )
    reviews = rows(
        select(ReviewItem)
        .where(ReviewItem.student_id == ctx.student_id)
        .order_by(ReviewItem.created_at, ReviewItem.id)
    )
    history = rows(
        select(ReviewCompletionRecord)
        .join(Attempt, Attempt.id == ReviewCompletionRecord.first_attempt_id)
        .join(StudySession)
        .where(owned, ReviewCompletionRecord.student_id == ctx.student_id)
        .order_by(ReviewCompletionRecord.review_id, ReviewCompletionRecord.first_attempt_id)
    )
    diagnostic_runs = rows(
        select(DiagnosticRun)
        .where(DiagnosticRun.student_id == ctx.student_id)
        .order_by(DiagnosticRun.created_at, DiagnosticRun.id)
    )
    rows(
        select(DiagnosticItem).join(DiagnosticRun).where(DiagnosticRun.student_id == ctx.student_id)
    )
    result = StudentLearningExportOut(
        exported_at=ctx.now(),
        profile=profile_service.serialize_profile(
            ctx.db, profile_service.get_profile(ctx.db, ctx.student_id)
        ),
        sessions=sessions,
        reviews=[
            review_scheduler.serialize(ctx.db, item, now=ctx.now(), settings=ctx.settings)
            for item in reviews
        ],
        review_history=[
            ExportReviewHistoryOut.model_validate(row, from_attributes=True) for row in history
        ],
        diagnostic_runs=[diagnostic_service.serialize_run(ctx.db, run) for run in diagnostic_runs],
        diagnostic_workspace=diagnostic_service.workspace(ctx.db, ctx.student_id),
        parent_access_records=ExportParentAccessRecordsOut(
            links=[
                ExportParentAccessLinkOut.model_validate(row, from_attributes=True)
                for row in rows(
                    select(ParentStudentLink)
                    .where(ParentStudentLink.student_id == ctx.student_id)
                    .order_by(ParentStudentLink.created_at, ParentStudentLink.id)
                )
            ],
            invites=[
                ExportParentAccessInviteOut.model_validate(row, from_attributes=True)
                for row in rows(
                    select(ParentInvite)
                    .where(ParentInvite.student_id == ctx.student_id)
                    .order_by(ParentInvite.created_at, ParentInvite.id)
                )
            ],
        ),
        stored_scan_records=_stored_scans(ctx, rows),
        model_usage=_model_usage(ctx, rows),
    )
    # ponytail: synchronous in-memory export; stream larger histories when needed.
    if len(result.model_dump_json().encode("utf-8")) > MAX_BYTES:
        raise ApiError(413, "export_too_large", "学习记录超过本次导出上限，未生成不完整文件")
    return result


def _model_usage(ctx, rows):
    key = pseudonym(ctx.request.app.state.pseudonym_secret, ctx.student_id)
    return ExportModelUsageOut(
        calls=[
            ExportModelCallOut.model_validate(row, from_attributes=True)
            for row in rows(
                select(ModelCallAudit)
                .where(ModelCallAudit.student_pseudonym == key)
                .order_by(ModelCallAudit.created_at, ModelCallAudit.id)
            )
        ],
        budget_days=[
            ExportModelBudgetDayOut.model_validate(row, from_attributes=True)
            for row in rows(
                select(ModelBudgetUsage)
                .where(ModelBudgetUsage.scope == STUDENT_SCOPE, ModelBudgetUsage.scope_key == key)
                .order_by(ModelBudgetUsage.usage_date, ModelBudgetUsage.id)
            )
        ],
    )
