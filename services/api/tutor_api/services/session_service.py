"""学习会话、作答、草稿与提交。

几条贯穿始终的规则：
- 每次读写都按"属于当前学生"过滤，不属于的一律当作不存在（404）；
- 会话保存题目版本和当时的地区、考试年份、教材版本快照，之后改资料不会回写；
- 只有会话里的第一份提交、且此前没有用过提示、图解、换种讲法或解析，才算独立作答；
- 判不出来的提交标成 uncertain，不算对也不算错，也不据此安排复测。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import conflict, not_found, unprocessable
from tutor_api.models import Attempt, HandwritingDraft, Question, StudentProfile, StudySession
from tutor_api.schemas import (
    AttemptOut,
    DraftOut,
    DraftSyncIn,
    Evaluation,
    FeedbackItem,
    SessionCreateIn,
    StudySessionOut,
    SubmitIn,
    SubmitResult,
)
from tutor_api.services import events, grading, profile_service, question_service, review_scheduler
from tutor_api.settings import Settings
from tutor_api.timefmt import iso

DISCLAIMER = "这是练习反馈，不是官方阅卷分数。"


# ---------------------------------------------------------------- 读取与归属


def get_owned_session(db: Session, student_id: str, session_id: str) -> StudySession:
    session = db.get(StudySession, session_id)
    if session is None or session.student_id != student_id:
        raise not_found()
    return session


def get_owned_attempt(
    db: Session, student_id: str, attempt_id: str
) -> tuple[Attempt, StudySession]:
    attempt = db.get(Attempt, attempt_id)
    session = db.get(StudySession, attempt.session_id) if attempt is not None else None
    if attempt is None or session is None or session.student_id != student_id:
        raise not_found()
    return attempt, session


def get_draft(db: Session, attempt_id: str) -> HandwritingDraft:
    draft = db.scalar(select(HandwritingDraft).where(HandwritingDraft.attempt_id == attempt_id))
    if draft is None:
        raise not_found()
    return draft


def submitted_count(db: Session, session_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(Attempt.session_id == session_id, Attempt.status == "submitted")
        )
        or 0
    )


def open_attempt(db: Session, session_id: str) -> Attempt | None:
    return db.scalar(
        select(Attempt).where(Attempt.session_id == session_id, Attempt.status == "draft")
    )


# ---------------------------------------------------------------- 序列化


def serialize_session(db: Session, session: StudySession) -> StudySessionOut:
    version = question_service.get_version(db, session.question_id, session.question_version)
    active = open_attempt(db, session.id)
    return StudySessionOut(
        id=session.id,
        question_id=session.question_id,
        question_version=session.question_version,
        origin=session.origin,
        state=session.state,
        review_item_id=session.review_item_id,
        parent_session_id=session.parent_session_id,
        region_code_snapshot=session.region_code_snapshot,
        exam_year_snapshot=session.exam_year_snapshot,
        curriculum_version_snapshot=session.curriculum_version_snapshot,
        assisted=session.assisted,
        used_solution=session.used_solution,
        independent_ended=session.independent_ended,
        hint_level_revealed=session.hint_level_revealed,
        hint_levels_total=len((version.teaching_json or {}).get("hints") or []),
        confused_streak=session.confused_streak,
        needs_human_help=session.needs_human_help,
        active_attempt_id=active.id if active else None,
        submitted_attempts=submitted_count(db, session.id),
        last_event_seq=events.last_seq(db, session.id),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def serialize_attempt(db: Session, attempt: Attempt) -> AttemptOut:
    draft = get_draft(db, attempt.id)
    return AttemptOut(
        id=attempt.id,
        session_id=attempt.session_id,
        attempt_no=attempt.attempt_no,
        status=attempt.status,
        answer=attempt.answer_json,
        draft_revision=draft.revision,
        assisted=attempt.assisted,
        used_solution=attempt.used_solution,
        independent=attempt.independent,
        evaluation=Evaluation(**attempt.evaluation_json) if attempt.evaluation_json else None,
        submitted_at=attempt.submitted_at,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
    )


def serialize_draft(attempt: Attempt, draft: HandwritingDraft) -> DraftOut:
    return DraftOut(
        attempt_id=attempt.id,
        revision=draft.revision,
        answer=attempt.answer_json,
        strokes=draft.strokes_json,
        updated_at=draft.updated_at,
    )


# ---------------------------------------------------------------- 会话


def create_session(
    db: Session, student_id: str, body: SessionCreateIn, *, now: datetime
) -> StudySession:
    question = question_service.get_published_question(db, body.question_id.lower())

    if body.origin == "review":
        if body.review_item_id is None:
            raise unprocessable("review_item_id", "复测会话必须指定复测项")
        item = review_scheduler.get_owned_item(db, student_id, body.review_item_id.lower())
        if item.question_id != question.id:
            raise unprocessable("review_item_id", "复测项与题目不一致")
        if item.status != "scheduled" or item.due_at > now:
            raise conflict("review_not_due", "这道题还没有到复测时间", {"due_at": iso(item.due_at)})
    elif body.review_item_id is not None:
        raise unprocessable("review_item_id", "只有复测会话才能指定复测项")

    parent_id = None
    if body.parent_session_id is not None:
        parent_id = get_owned_session(db, student_id, body.parent_session_id.lower()).id

    profile = db.get(StudentProfile, student_id)
    region_code = profile.region_code if profile else None
    exam_year = profile.exam_year if profile else None
    session = StudySession(
        id=new_id(),
        student_id=student_id,
        question_id=question.id,
        question_version=question.version,
        state="READY",
        origin=body.origin,
        review_item_id=body.review_item_id.lower() if body.review_item_id else None,
        parent_session_id=parent_id,
        region_code_snapshot=region_code,
        exam_year_snapshot=exam_year,
        exam_scheme_code_snapshot=profile_service.resolve_scheme_code(db, region_code, exam_year),
        curriculum_version_snapshot=profile.curriculum_version if profile else None,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.flush()
    return session


# ---------------------------------------------------------------- 作答与草稿


def create_attempt(db: Session, student_id: str, session_id: str, *, now: datetime) -> Attempt:
    session = get_owned_session(db, student_id, session_id.lower())
    if session.state == "DONE":
        raise conflict("invalid_state", "这次学习已经结束，请重新开始一次会话")
    existing = open_attempt(db, session.id)
    if existing is not None:
        raise conflict(
            "attempt_in_progress", "这次会话里还有一份没有提交的作答", {"attempt_id": existing.id}
        )

    attempt_no = (
        db.scalar(select(func.max(Attempt.attempt_no)).where(Attempt.session_id == session.id)) or 0
    ) + 1
    attempt = Attempt(
        id=new_id(),
        session_id=session.id,
        attempt_no=attempt_no,
        status="draft",
        # 同一会话里的重试已经看过上一次的反馈，不再算独立作答
        assisted=session.assisted or attempt_no > 1,
        used_solution=session.used_solution,
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)
    db.flush()
    db.add(HandwritingDraft(id=new_id(), attempt_id=attempt.id, revision=0, updated_at=now))
    if session.state == "READY":
        session.state = "INDEPENDENT_ATTEMPT"
    session.updated_at = now
    db.flush()
    return attempt


def sync_draft(
    db: Session, student_id: str, attempt_id: str, body: DraftSyncIn, *, now: datetime
) -> DraftOut:
    attempt, _ = get_owned_attempt(db, student_id, attempt_id)
    if attempt.status != "draft":
        raise conflict("attempt_already_submitted", "这份作答已经提交，草稿不能再修改")
    draft = get_draft(db, attempt.id)
    if body.base_revision != draft.revision:
        # 不覆盖任何一方：把服务端当前版本带回去，由客户端让学生选择
        raise conflict(
            "draft_revision_conflict",
            "草稿在别处已有更新，没有覆盖",
            {
                "server_revision": draft.revision,
                "server_draft": serialize_draft(attempt, draft).model_dump(mode="json"),
            },
        )

    attempt.answer_json = body.answer.model_dump(exclude_none=True) if body.answer else None
    attempt.updated_at = now
    draft.strokes_json = body.strokes.model_dump() if body.strokes else None
    draft.revision += 1
    draft.updated_at = now
    db.flush()
    return serialize_draft(attempt, draft)


# ---------------------------------------------------------------- 提交


def _diagnosis_suggestions(
    result: grading.GradeResult, session: StudySession, hint_total: int, has_standard: bool
) -> list[dict[str, Any]]:
    if result.is_correct:
        suggestions = [events.suggestion("request_standard", "看看解法")] if has_standard else []
        return [*suggestions, events.suggestion("finish", "完成这道题")]
    suggestions = []
    if session.hint_level_revealed < hint_total:
        suggestions.append(events.suggestion("request_hint", "给点提示"))
    suggestions.append(events.suggestion("retry_attempt", "再试一次"))
    if has_standard:
        suggestions.append(events.suggestion("request_standard", "看常规解法"))
    return suggestions


def submit_attempt(
    db: Session,
    settings: Settings,
    student_id: str,
    attempt_id: str,
    body: SubmitIn,
    *,
    key_digest: str,
    request_id: str,
    now: datetime,
) -> SubmitResult:
    attempt, session = get_owned_attempt(db, student_id, attempt_id)
    if attempt.status != "draft":
        raise conflict("attempt_already_submitted", "这份作答已经提交过了")

    question = db.get(Question, session.question_id)
    assert question is not None
    version = question_service.get_version(db, question.id, session.question_version)
    teaching = version.teaching_json or {}
    answer = body.answer.model_dump(exclude_none=True)
    try:
        result = grading.grade(
            answer_mode=question.answer_mode,
            content=version.content_json,
            answer_key=version.answer_json,
            rubric=question_service.get_rubric(db, question.id, version.version),
            teaching=teaching,
            answer=answer,
        )
    except grading.AnswerShapeError as error:
        raise unprocessable(error.field, error.message) from error

    independent = (
        attempt.attempt_no == 1
        and not session.assisted
        and not session.used_solution
        and not session.independent_ended
    )
    evaluation = Evaluation(
        state=result.state,
        outcome=result.outcome,
        is_correct=result.is_correct,
        independent=independent,
        assisted=not independent,
        used_solution=session.used_solution,
        review_required=result.review_required,
        feedback=[
            FeedbackItem(target=f.target, code=f.code, message=f.message) for f in result.feedback
        ],
        message=result.message,
        disclaimer=DISCLAIMER,
    )

    attempt.status = "submitted"
    attempt.answer_json = answer
    attempt.independent = independent
    attempt.assisted = not independent
    attempt.used_solution = session.used_solution
    attempt.evaluation_state = result.state
    attempt.outcome = result.outcome
    attempt.is_correct = result.is_correct
    attempt.evaluation_json = evaluation.model_dump(mode="json")
    attempt.request_id = key_digest
    attempt.elapsed_ms = body.elapsed_ms
    attempt.submitted_at = now
    attempt.updated_at = now
    session.state = "SUBMITTED"
    if result.is_correct:
        session.confused_streak = 0
    db.flush()

    if result.state == "verified":
        knowledge = question_service.knowledge_refs(db, [question.id])[question.id]
        standard = question_service.get_solution(db, question.id, version.version, "standard")
        payload = {
            "outcome": result.outcome,
            "summary": result.message,
            "feedback": [f.model_dump() for f in evaluation.feedback],
            "knowledge": [ref.model_dump() for ref in knowledge],
            "suggestions": _diagnosis_suggestions(
                result,
                session,
                len(teaching.get("hints") or []),
                standard is not None and standard.reviewed,
            ),
        }
        event = events.append_event(
            db,
            session,
            event_type="diagnosis",
            payload=payload,
            state_after="DIAGNOSED",
            source="rule_engine",
            request_id=request_id,
            now=now,
        )
    else:
        # 判不出来：明确告诉学生"待确认"，不给任何确定结论（US-05）
        event = events.append_event(
            db,
            session,
            event_type="uncertainty",
            payload={
                "reason_code": result.uncertainty_reason or "verification_failed",
                "text": result.message,
                "review_required": True,
            },
            state_after="DIAGNOSED",
            source="rule_engine",
            request_id=request_id,
            now=now,
        )

    review_item = None
    needs_review = result.state == "verified" and (not result.is_correct or not independent)
    if needs_review and session.origin != "review":
        review_item = review_scheduler.after_submission(
            db,
            settings,
            student_id=student_id,
            question_id=question.id,
            session_id=session.id,
            correct=bool(result.is_correct),
            now=now,
        )

    return SubmitResult(
        attempt=serialize_attempt(db, attempt),
        evaluation=evaluation,
        session=serialize_session(db, session),
        events=[event],
        review_item=(
            review_scheduler.serialize(db, review_item, now=now, settings=settings)
            if review_item
            else None
        ),
    )
