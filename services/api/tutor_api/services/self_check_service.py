"""解答题提交后的对照自查（PRD P0 第 3、4 条）。

解答题不自动评分（Q-06：低置信度弃判，不冒充官方阅卷）。提交之后，学生对照这道题的要点清单，
给每个要点标"做到了 / 做到一部分 / 没做到"。这是学生自己的记录：不折算成分数，不进任何正确率，
也不据此安排复测。

- 要点（rubric.points）只在作答提交之后才给，独立作答阶段不泄题；
- 要点取自会话开始时固定的那个题目版本：题目之后改过，不影响这份作答的自查；
- 每个要点必须恰好评一次，整体替换，可以改过再存。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import conflict, unprocessable
from tutor_api.models import Attempt, AttemptSelfCheck, Question, StudySession
from tutor_api.schemas import (
    SelfCheckMark,
    SelfCheckOut,
    SelfCheckPoint,
    SelfCheckSaveIn,
    SelfCheckSummary,
)
from tutor_api.services import question_service, session_service

DISCLAIMER = "自查是你自己对照要点做的记录，不是官方阅卷分数，也不会计入正确率。"


def _points_of(db: Session, attempt: Attempt, session: StudySession) -> list[SelfCheckPoint]:
    """这份作答可以自查的要点。不是解答题、或还没提交，都不给。"""
    question = db.get(Question, session.question_id)
    assert question is not None
    if question.answer_mode != "written":
        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")
    if attempt.status != "submitted":
        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")
    rubric = question_service.get_rubric(db, question.id, session.question_version)
    return [
        SelfCheckPoint(key=point["key"], part=point.get("part"), text=point["text"])
        for point in rubric.get("points") or []
    ]


def _row(db: Session, attempt_id: str) -> AttemptSelfCheck | None:
    return db.scalar(select(AttemptSelfCheck).where(AttemptSelfCheck.attempt_id == attempt_id))


def _serialize(
    attempt: Attempt, points: list[SelfCheckPoint], row: AttemptSelfCheck | None
) -> SelfCheckOut:
    marks = [SelfCheckMark(**mark) for mark in (row.marks_json if row else [])]
    counts = Counter(mark.level for mark in marks)
    return SelfCheckOut(
        attempt_id=attempt.id,
        points=points,
        marks=marks,
        summary=SelfCheckSummary(
            done=counts["done"],
            partial=counts["partial"],
            missed=counts["missed"],
            total=len(points),
        ),
        saved_at=row.updated_at if row else None,
        disclaimer=DISCLAIMER,
    )


def get_self_check(db: Session, student_id: str, attempt_id: str) -> SelfCheckOut:
    attempt, session = session_service.get_owned_attempt(db, student_id, attempt_id)
    points = _points_of(db, attempt, session)
    return _serialize(attempt, points, _row(db, attempt.id))


def save_self_check(
    db: Session, student_id: str, attempt_id: str, body: SelfCheckSaveIn, *, now: datetime
) -> SelfCheckOut:
    attempt, session = session_service.get_owned_attempt(db, student_id, attempt_id)
    points = _points_of(db, attempt, session)

    keys = [point.key for point in points]
    given = [mark.point_key for mark in body.marks]
    if len(set(given)) != len(given):
        raise unprocessable("marks", "同一个要点只能评一次")
    if not set(given) <= set(keys):
        raise unprocessable("marks", "包含不存在的要点")
    if set(keys) - set(given):
        raise unprocessable("marks", "每个要点都要评一次，还有要点没有评")

    level_of = {mark.point_key: mark.level for mark in body.marks}
    # 按要点清单的顺序存，读出来的顺序就不依赖客户端发送的顺序
    marks = [{"point_key": key, "level": level_of[key]} for key in keys]
    row = _row(db, attempt.id)
    if row is None:
        row = AttemptSelfCheck(
            id=new_id(), attempt_id=attempt.id, marks_json=marks, created_at=now, updated_at=now
        )
        db.add(row)
    else:
        row.marks_json = marks
        row.updated_at = now
    db.flush()
    return _serialize(attempt, points, row)
