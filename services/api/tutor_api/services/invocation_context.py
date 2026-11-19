"""Capture trusted model context under the existing owned-session write lock.

Only its digest may enter the invocation journal. The lock stays in the caller's
transaction so finalization can append events and a receipt before committing.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select

from tutor_api.errors import conflict, not_found
from tutor_api.models import QuestionVersion, Rubric, Solution, StudySession, User
from tutor_api.services import events, session_service


@dataclass(frozen=True)
class InvocationContext:
    digest: str
    question_version: int
    event_sequence: int


def capture_context(
    db, student_id: str, session_id: str, *, allow_done: bool = False
) -> InvocationContext:
    user = db.scalar(
        select(User)
        .where(User.id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.status != "active" or user.role != "student":
        raise not_found()
    session = session_service.lock_owned_session(db, student_id, session_id)
    if session.state == "DONE" and not allow_done:
        raise conflict("invalid_state", "这次学习已经结束")
    version = db.scalar(
        select(QuestionVersion)
        .where(
            QuestionVersion.question_id == session.question_id,
            QuestionVersion.version == session.question_version,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise conflict("invalid_state", "固定题目版本不可用")
    sequence = events.last_seq(db, session.id, current_read=True)
    view = session_service.serialize_session(db, session).model_dump(mode="json")
    view["last_event_seq"] = sequence
    value = dict(
        session=view,
        content=version.content_json,
        teaching=version.teaching_json,
        answer=version.answer_json,
    )
    solutions = db.scalars(
        select(Solution)
        .where(
            Solution.question_id == session.question_id,
            Solution.version == session.question_version,
        )
        .order_by(Solution.kind)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    value["solutions"] = [
        dict(
            kind=row.kind,
            content=row.content_json,
            conditions=row.conditions_json,
            reviewed=row.reviewed,
        )
        for row in solutions
    ]
    rubric = db.scalar(
        select(Rubric)
        .where(
            Rubric.question_id == session.question_id,
            Rubric.version == session.question_version,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    value["rubric"] = rubric.rubric_json if rubric else None
    digest = hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    return InvocationContext(digest, session.question_version, sequence)


def require_context(db, student_id: str, session_id: str, expected_digest: str) -> StudySession:
    current = capture_context(db, student_id, session_id)
    if current.digest != expected_digest:
        raise conflict("invalid_state", "学习上下文已变化，旧讲解不能应用")
    return db.get(StudySession, session_id)
