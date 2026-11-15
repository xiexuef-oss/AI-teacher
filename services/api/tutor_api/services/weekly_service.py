"""家长周报（PRD P0 第 8 条、US-06、docs/03 P10）：已授权学生某一周的汇总。

只有计数和比例。没有具体题目、作答内容、提示原文、草稿和笔迹，也没有每次练习的时间；不是官方成绩，没有排名，
没有连续天数。口径与学情页一致（`progress_service`）：只有确定判定的作答进比例；独立正确率和辅助正确率分开；
样本不足 `progress_min_samples` 时只给计数，比例是 null；解答题、实验题和证明题不自动评分，只数提交了几份。

一周从周一 00:00 到下周一 00:00，按 `report_utc_offset_minutes` 划分（默认 UTC+8）。
先检查授权再检查参数：没授权的家长连"这个日期合不合法"都问不出来。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.errors import unprocessable
from tutor_api.models import StudySession
from tutor_api.schemas import ParentWeeklyOut, PreviousWeekOut, WeeklyTrend
from tutor_api.services import grading, parent_service, progress_service
from tutor_api.settings import Settings

DISCLAIMER = (
    "这些数字来自练习反馈，不是官方成绩，也不代表短期内一定提分。样本少的时候只显示计数，比例是“信息不足”。"
    "周报只有汇总，不含具体题目、作答内容和草稿笔迹；解答题、实验题和证明题不自动评分，只数提交了几份。"
)
# 独立正确率比上一周高或低这么多（5 个百分点）才算变了，否则是"差不多"
TREND_THRESHOLD = 0.05


def trend_of(previous: float | None, current: float | None) -> WeeklyTrend:
    """两周里有一周样本不足（比例是 None）就是 unknown——不拿一个不可靠的数去比。"""
    if previous is None or current is None:
        return "unknown"
    delta = round(current - previous, 4)
    if delta >= TREND_THRESHOLD:
        return "up"
    if delta <= -TREND_THRESHOLD:
        return "down"
    return "flat"


def _window(
    settings: Settings, week_start: date | None, now: datetime
) -> tuple[date, datetime, datetime, timezone]:
    offset = timezone(timedelta(minutes=settings.report_utc_offset_minutes))
    local_today = now.astimezone(offset).date()
    this_monday = local_today - timedelta(days=local_today.weekday())
    if week_start is None:
        start_date = this_monday
    else:
        if week_start.weekday() != 0:
            raise unprocessable("week_start", "week_start 必须是周一")
        if week_start > this_monday:
            raise unprocessable("week_start", "这一周还没有开始")
        start_date = week_start

    def at_midnight(day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=offset).astimezone(UTC)

    return start_date, at_midnight(start_date), at_midnight(start_date + timedelta(days=7)), offset


def weekly_report(
    db: Session,
    settings: Settings,
    parent_id: str,
    student_id: str,
    week_start: date | None,
    *,
    now: datetime,
) -> ParentWeeklyOut:
    _, student = parent_service.require_link(db, parent_id, student_id)
    start_date, start, end, offset = _window(settings, week_start, now)
    min_samples = settings.progress_min_samples

    records = progress_service.load_records(db, student_id, since=start, until=end)
    rows = progress_service.verified_rows(records)
    first = [row for row in rows if row.attempt_no == 1]
    stat = progress_service.rate_stat
    independent = stat((r for r in rows if r.independent), progress_service.is_correct, min_samples)

    previous_records = progress_service.load_records(
        db, student_id, since=start - timedelta(days=7), until=start
    )
    previous_independent = stat(
        (r for r in progress_service.verified_rows(previous_records) if r.independent),
        progress_service.is_correct,
        min_samples,
    )

    sessions_count = (
        db.scalar(
            select(func.count())
            .select_from(StudySession)
            .where(
                StudySession.student_id == student_id,
                StudySession.created_at >= start,
                StudySession.created_at < end,
            )
        )
        or 0
    )
    return ParentWeeklyOut(
        student_id=student.id,
        student_display_name=student.display_name,
        week_start=start_date,
        week_end=start_date + timedelta(days=6),
        is_complete=now >= end,
        generated_at=now,
        min_samples=min_samples,
        sessions_count=sessions_count,
        attempts_count=len(records),
        active_days=len(
            {attempt.submitted_at.astimezone(offset).date() for attempt, *_ in records}
        ),
        independent=independent,
        assisted=stat(
            (r for r in rows if not r.independent), progress_service.is_correct, min_samples
        ),
        hint_dependency=stat(first, lambda r: not r.independent, min_samples),
        retest_success=stat(
            (r for r in first if r.origin == "review"),
            progress_service.unaided_success,
            min_samples,
        ),
        written_attempts=sum(1 for _, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES),
        independent_trend=trend_of(previous_independent.rate, independent.rate),
        previous_week=PreviousWeekOut(
            week_start=start_date - timedelta(days=7),
            attempts_count=len(previous_records),
            independent=previous_independent,
        ),
        by_subject=progress_service.subject_buckets(rows, min_samples),
        disclaimer=DISCLAIMER,
    )
