"""间隔复测（docs/06 §7）。

用确定性的间隔：默认 T+1、T+3、T+7 天，可配置，不保证是最优的。每通过一次进入下一档，
全部通过后标记 mastered；任何一次没通过都回到第一档。复测结果只取服务端对作答的判定
（实测），不接受客户端自报，也不用任何估算代替。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import conflict, not_found
from tutor_api.models import Attempt, Question, ReviewCompletionRecord, ReviewItem, StudySession
from tutor_api.schemas import ReviewCompletion, ReviewItemOut, ReviewPage
from tutor_api.services import question_service
from tutor_api.settings import Settings


def serialize(db: Session, item: ReviewItem, *, now: datetime, settings: Settings) -> ReviewItemOut:
    question = db.get(Question, item.question_id)
    assert question is not None
    version = question_service.get_version(db, question.id, question.version)
    return ReviewItemOut(
        id=item.id,
        question_id=item.question_id,
        question_title=version.content_json.get("title") or "",
        subject=question.subject,
        status=item.status,
        stage=item.stage,
        total_stages=len(settings.review_intervals),
        due_at=item.due_at,
        is_due=item.status == "scheduled" and item.due_at <= now,
        last_result=item.last_result,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def find_item(db: Session, student_id: str, question_id: str) -> ReviewItem | None:
    return db.scalar(
        select(ReviewItem).where(
            ReviewItem.student_id == student_id, ReviewItem.question_id == question_id
        )
    )


def after_submission(
    db: Session,
    settings: Settings,
    *,
    student_id: str,
    question_id: str,
    session_id: str,
    correct: bool,
    now: datetime,
) -> ReviewItem:
    """答错，或在辅助下才答对：把这道题放进复测队列。已在队列里的题，再次答错会回到第一档。"""
    first_due = now + settings.review_intervals[0]
    item = find_item(db, student_id, question_id)
    if item is None:
        item = ReviewItem(
            id=new_id(),
            student_id=student_id,
            question_id=question_id,
            status="scheduled",
            stage=0,
            due_at=first_due,
            origin_session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    elif not correct:
        item.due_at = min(item.due_at, first_due) if item.status == "scheduled" else first_due
        item.status = "scheduled"
        item.stage = 0
        item.updated_at = now
    db.flush()
    return item


def get_owned_item(db: Session, student_id: str, review_id: str) -> ReviewItem:
    item = db.get(ReviewItem, review_id)
    if item is None or item.student_id != student_id:
        raise not_found()
    return item


def list_reviews(
    db: Session,
    student_id: str,
    *,
    scope: str,
    cursor: str | None,
    limit: int,
    now: datetime,
    settings: Settings,
) -> ReviewPage:
    offset = question_service.decode_cursor(cursor)
    # 题目被下线（或改成了待审的新版本）时，复测项还留着、时间也不变，但学生开不了会话，
    # 所以不列给他；题目重新上线后会自然回到列表里
    query = (
        select(ReviewItem)
        .join(Question, Question.id == ReviewItem.question_id)
        .where(
            ReviewItem.student_id == student_id,
            ReviewItem.status == "scheduled",
            Question.status == "published",
        )
    )
    if scope == "due":
        query = query.where(ReviewItem.due_at <= now)
    rows = list(
        db.scalars(query.order_by(ReviewItem.due_at, ReviewItem.id).offset(offset).limit(limit + 1))
    )
    page = rows[:limit]
    return ReviewPage(
        items=[serialize(db, item, now=now, settings=settings) for item in page],
        next_cursor=question_service.encode_cursor(offset + limit) if len(rows) > limit else None,
    )


def complete(
    db: Session,
    settings: Settings,
    *,
    student_id: str,
    review_id: str,
    attempt_id: str,
    now: datetime,
) -> ReviewCompletion:
    # Match submit's lock order: owned sessions, their attempts, then review.
    # Never look up an arbitrary supplied attempt ID in a locking query: even a
    # rejected foreign ID can take a primary-key lock in InnoDB.
    get_owned_item(db, student_id, review_id)
    sessions_query = select(StudySession).where(
        StudySession.student_id == student_id, StudySession.review_item_id == review_id
    )
    if db.get_bind().dialect.name == "sqlite":
        db.execute(
            update(StudySession)
            .where(StudySession.student_id == student_id, StudySession.review_item_id == review_id)
            .values(updated_at=StudySession.updated_at)
        )
    sessions = list(
        db.scalars(
            sessions_query.with_hint(
                StudySession, "FORCE INDEX (ix_sessions_review_owner)", "mysql"
            )
            .order_by(StudySession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    attempts = []
    for session in sessions:
        attempts.extend(
            db.scalars(
                select(Attempt)
                .where(Attempt.session_id == session.id)
                .with_hint(Attempt, "FORCE INDEX (uq_attempt_no)", "mysql")
                .order_by(Attempt.attempt_no)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
    attempt = next((row for row in attempts if row.id == attempt_id), None)
    if attempt is None:
        # Nonlocking reads preserve the existing wrong-review error without
        # acquiring a lock outside the owned review group.
        supplied = db.get(Attempt, attempt_id)
        supplied_session = db.get(StudySession, supplied.session_id) if supplied else None
        if supplied_session is None or supplied_session.student_id != student_id:
            raise not_found()
        raise conflict("attempt_not_for_this_review", "这份作答不是用这个复测项开启的会话里产生的")
    first = next(
        (
            row
            for row in attempts
            if row.session_id == attempt.session_id and row.submission_no == 1
        ),
        None,
    )
    item = db.scalar(
        select(ReviewItem)
        .where(ReviewItem.id == review_id, ReviewItem.student_id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise not_found()
    source_session = next(row for row in sessions if row.id == attempt.session_id)
    if source_session.question_id != item.question_id or source_session.origin != "review":
        raise conflict("attempt_not_for_this_review", "这份作答不是用这个复测项开启的会话里产生的")
    if first is None or first.status != "submitted" or first.evaluation_state != "verified":
        raise conflict("attempt_not_verified", "这次复测的作答还没有确定的判定，暂时不能完成复测")
    passed = bool(first.is_correct) and bool(first.independent)
    values = dict(
        review_id=item.id,
        first_attempt_id=first.id,
        student_id=student_id,
        question_id=item.question_id,
        state="completed",
        result="passed" if passed else "failed",
        completed_at=now,
    )
    # Reserve atomically before reading: SELECT FOR UPDATE on a missing history
    # key takes gap locks under MySQL RR and can deadlock unrelated reviews.
    if db.get_bind().dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import insert

        statement = insert(ReviewCompletionRecord).values(**values).prefix_with("IGNORE")
    else:
        from sqlalchemy.dialects.sqlite import insert

        statement = (
            insert(ReviewCompletionRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["review_id", "first_attempt_id"])
        )
    inserted = db.execute(statement).rowcount
    if not inserted:
        history = db.scalar(
            select(ReviewCompletionRecord)
            .where(
                ReviewCompletionRecord.review_id == item.id,
                ReviewCompletionRecord.first_attempt_id == first.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            history is None
            or history.student_id != student_id
            or history.question_id != item.question_id
        ):
            raise conflict(
                "review_completion_history_unknown", "复测历史关联不一致，请保留作答并联系支持"
            )
        if history.state != "completed" or history.result != values["result"]:
            raise conflict(
                "review_completion_history_unknown", "这份旧作答的复测完成历史无法确认，请保留作答"
            )
        raise conflict("review_already_completed", "这次复测已经记录过了")
    if item.last_attempt_id == first.id:
        raise conflict("review_already_completed", "这次复测已经记录过了")
    # Multiple sessions can be opened in the same due window. Completing one
    # advances the schedule; an already-open second session cannot skip it.
    if item.status != "scheduled" or item.due_at > now:
        raise conflict("review_not_due", "这项复测尚未到期，暂时不能完成复测")

    intervals = settings.review_intervals
    if passed:
        item.stage += 1
        if item.stage >= len(intervals):
            item.status = "mastered"
        else:
            item.due_at = now + intervals[item.stage]
    else:
        item.stage = 0
        item.status = "scheduled"
        item.due_at = now + intervals[0]
    item.last_result = "passed" if passed else "failed"
    item.last_attempt_id = first.id
    item.updated_at = now
    db.flush()
    return ReviewCompletion(
        review_item=serialize(db, item, now=now, settings=settings),
        result=item.last_result,
        next_due_at=item.due_at if item.status == "scheduled" else None,
    )
