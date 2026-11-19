"""Append immutable weekly summaries after the reporting week closes."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tutor_api.errors import not_found
from tutor_api.models import ParentStudentLink, User, WeeklyReportSnapshot
from tutor_api.schemas import ParentWeeklyOut
from tutor_api.services.parent_service import require_link
from tutor_api.services.weekly_service import build_weekly_report
from tutor_api.settings import Settings


def refresh_confirmed_week(
    db: Session, settings: Settings, student_id: str, confirmed_at: datetime, now: datetime
) -> None:
    local_date = confirmed_at.astimezone(
        timezone(timedelta(minutes=settings.report_utc_offset_minutes))
    ).date()
    week = local_date - timedelta(days=local_date.weekday())
    if db.get(WeeklyReportSnapshot, (student_id, week, 1)) is not None:
        save_snapshot(db, settings, student_id, week, now)


def generate_due_snapshots(factory, settings: Settings, now: datetime) -> int:
    local = now.astimezone(timezone(timedelta(minutes=settings.report_utc_offset_minutes)))
    monday = local.date() - timedelta(days=local.weekday())
    if local.date() == monday and local.hour < 7:
        return 0
    week = monday - timedelta(days=7)
    already_saved = (
        select(WeeklyReportSnapshot.student_id)
        .where(
            WeeklyReportSnapshot.student_id == ParentStudentLink.student_id,
            WeeklyReportSnapshot.week_start == week,
        )
        .exists()
    )
    with factory() as db:
        students = list(
            db.scalars(
                select(ParentStudentLink.student_id)
                .join(User, User.id == ParentStudentLink.student_id)
                .where(
                    ParentStudentLink.revoked_at.is_(None),
                    ParentStudentLink.consent_at <= now,
                    User.role == "student",
                    ~already_saved,
                )
                .distinct()
                .order_by(ParentStudentLink.student_id)
                .limit(25)
            )
        )
    for student_id in students:
        with factory() as db:
            save_snapshot(db, settings, student_id, week, now)
            db.commit()
    return len(students)


def read_snapshot(
    db: Session, parent_id: str, student_id: str, week_start: date, revision: int | None
) -> dict:
    _, student = require_link(db, parent_id, student_id)
    query = (
        select(WeeklyReportSnapshot)
        .where(
            WeeklyReportSnapshot.student_id == student_id,
            WeeklyReportSnapshot.week_start == week_start,
        )
        .order_by(WeeklyReportSnapshot.revision.desc())
        .limit(1)
    )
    if revision is not None:
        query = query.where(WeeklyReportSnapshot.revision == revision)
    snapshot = db.scalar(query)
    if snapshot is None:
        raise not_found()
    return {
        "revision": snapshot.revision,
        "report": ParentWeeklyOut(
            student_id=student.id,
            student_display_name=student.display_name,
            generated_at=snapshot.generated_at,
            **snapshot.summary_json,
        ).model_dump(mode="json"),
    }


def save_snapshot(
    db: Session, settings: Settings, student_id: str, week_start: date, now: datetime
) -> WeeklyReportSnapshot:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(User).where(User.id == student_id).values(updated_at=User.updated_at))
    student = db.scalar(
        select(User).where(User.id == student_id, User.role == "student").with_for_update()
    )
    if student is None:
        raise ValueError("Student does not exist")
    report = build_weekly_report(db, settings, student, week_start, now=now)
    if not report.is_complete:
        raise ValueError("The reporting week is still open")
    summary = report.model_dump(
        mode="json", exclude={"student_id", "student_display_name", "generated_at"}
    )
    latest = db.scalar(
        select(WeeklyReportSnapshot)
        .where(
            WeeklyReportSnapshot.student_id == student_id,
            WeeklyReportSnapshot.week_start == week_start,
        )
        .order_by(WeeklyReportSnapshot.revision.desc())
        .limit(1)
        .with_for_update()
    )
    if latest is not None and (latest.summary_json == summary or latest.generated_at > now):
        return latest
    snapshot = WeeklyReportSnapshot(
        student_id=student_id,
        week_start=week_start,
        revision=1 if latest is None else latest.revision + 1,
        summary_json=summary,
        generated_at=now,
    )
    db.add(snapshot)
    db.flush()
    return snapshot
