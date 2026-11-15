"""间隔复测（docs/06 §7）。

用确定性的间隔：默认 T+1、T+3、T+7 天，可配置，不保证是最优的。每通过一次进入下一档，
全部通过后标记 mastered；任何一次没通过都回到第一档。复测结果只取服务端对作答的判定
（实测），不接受客户端自报，也不用任何估算代替。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import conflict, not_found
from tutor_api.models import Attempt, Question, ReviewItem, StudySession
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
    item = get_owned_item(db, student_id, review_id)
    attempt = db.get(Attempt, attempt_id)
    session = db.get(StudySession, attempt.session_id) if attempt is not None else None
    if attempt is None or session is None or session.student_id != student_id:
        raise not_found()
    if session.review_item_id != item.id:
        raise conflict("attempt_not_for_this_review", "这份作答不是用这个复测项开启的会话里产生的")

    # 复测的结果看这次复测会话里的第一份提交：之后的重试已经看过反馈，不算
    first = db.scalar(
        select(Attempt).where(Attempt.session_id == session.id, Attempt.attempt_no == 1)
    )
    if first is None or first.status != "submitted" or first.evaluation_state != "verified":
        raise conflict("attempt_not_verified", "这次复测的作答还没有确定的判定，暂时不能完成复测")
    if item.last_attempt_id == first.id:
        raise conflict("review_already_completed", "这次复测已经记录过了")

    passed = bool(first.is_correct) and bool(first.independent)
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
