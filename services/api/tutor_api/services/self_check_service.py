"""解答题、实验题、证明题提交后的对照自查（PRD P0 第 3、4 条）。

解答题、实验题和证明题不自动评分（Q-06：低置信度弃判，不冒充官方阅卷）。提交之后，学生对照这道题的要点清单，
给每个要点标"做到了 / 做到一部分 / 没做到"。这是学生自己的记录：不折算成分数，不进任何正确率，
也不据此安排复测。

- 要点（rubric.points）只在作答提交之后才给，独立作答阶段不泄题；
- 实验题数据表里留空格子的参考值（reference_cells）、证明题的参考证明（reference_steps）也只在提交之后给，
  让学生把自己填的数、自己写的证明和它们对照；
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
    AnswerCell,
    ProofReferenceStep,
    SelfCheckMark,
    SelfCheckOut,
    SelfCheckPoint,
    SelfCheckSaveIn,
    SelfCheckSummary,
)
from tutor_api.services import grading, question_service, session_service

DISCLAIMER = "自查是你自己对照要点做的记录，不是官方阅卷分数，也不会计入正确率。"


def _checklist_of(
    db: Session, attempt: Attempt, session: StudySession
) -> tuple[list[SelfCheckPoint], list[AnswerCell], list[ProofReferenceStep]]:
    """这份作答可以自查的要点、参考数据和参考证明。不是解答题、实验题、证明题，或还没提交，都不给。"""
    question = db.get(Question, session.question_id)
    assert question is not None
    if question.answer_mode not in grading.SUBJECTIVE_MODES:
        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")
    if attempt.status != "submitted":
        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")
    rubric = question_service.get_rubric(db, question.id, session.question_version)
    points = [
        SelfCheckPoint(key=point["key"], part=point.get("part"), text=point["text"])
        for point in rubric.get("points") or []
    ]
    return points, _reference_cells(db, question, session), _reference_steps(db, question, session)


def _reference_cells(db: Session, question: Question, session: StudySession) -> list[AnswerCell]:
    """实验题数据表里留空格子的参考值（取会话固定的题目版本）。其他题型没有。"""
    if question.answer_mode != "experiment":
        return []
    version = question_service.get_version(db, question.id, session.question_version)
    values = (version.answer_json or {}).get("value") or {}
    cells = []
    for table, row, col in grading.blank_cell_keys(version.content_json):
        reference = values.get(f"{table}.{row}.{col}")
        if isinstance(reference, str):
            cells.append(AnswerCell(table=table, row=row, col=col, value=reference))
    return cells


def _reference_steps(
    db: Session, question: Question, session: StudySession
) -> list[ProofReferenceStep]:
    """证明题的参考证明（取会话固定的题目版本）。其他题型没有。"""
    if question.answer_mode != "proof":
        return []
    version = question_service.get_version(db, question.id, session.question_version)
    steps = ((version.answer_json or {}).get("value") or {}).get("steps") or []
    return [
        ProofReferenceStep(stage=step["stage"], text=step["text"], reason=step["reason"])
        for step in steps
    ]


def _row(db: Session, attempt_id: str) -> AttemptSelfCheck | None:
    return db.scalar(select(AttemptSelfCheck).where(AttemptSelfCheck.attempt_id == attempt_id))


def _serialize(
    attempt: Attempt,
    points: list[SelfCheckPoint],
    reference_cells: list[AnswerCell],
    reference_steps: list[ProofReferenceStep],
    row: AttemptSelfCheck | None,
) -> SelfCheckOut:
    marks = [SelfCheckMark(**mark) for mark in (row.marks_json if row else [])]
    counts = Counter(mark.level for mark in marks)
    return SelfCheckOut(
        attempt_id=attempt.id,
        points=points,
        reference_cells=reference_cells,
        reference_steps=reference_steps,
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
    points, reference_cells, reference_steps = _checklist_of(db, attempt, session)
    return _serialize(attempt, points, reference_cells, reference_steps, _row(db, attempt.id))


def save_self_check(
    db: Session, student_id: str, attempt_id: str, body: SelfCheckSaveIn, *, now: datetime
) -> SelfCheckOut:
    attempt, session = session_service.get_owned_attempt(db, student_id, attempt_id)
    points, reference_cells, reference_steps = _checklist_of(db, attempt, session)

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
    return _serialize(attempt, points, reference_cells, reference_steps, row)
