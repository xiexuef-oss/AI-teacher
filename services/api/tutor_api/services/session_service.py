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

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import conflict, not_found, unprocessable
from tutor_api.models import (
    Attempt,
    HandwritingDraft,
    Question,
    QuestionVersion,
    StudentProfile,
    StudySession,
)
from tutor_api.schemas import (
    AttemptOut,
    DraftCopyCreateIn,
    DraftCopyOut,
    DraftOut,
    DraftSyncIn,
    Evaluation,
    FeedbackItem,
    QuestionDraftPageOut,
    QuestionDraftRefOut,
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


def _locked(db, session_id):
    transaction = db.get_transaction()
    return (
        transaction is not None
        and db.info.get("session_write_locks", {}).get(session_id) is transaction
    )


def lock_owned_session(db, student_id, session_id):
    statement = select(StudySession).where(
        StudySession.id == session_id, StudySession.student_id == student_id
    )
    if db.get_bind().dialect.name == "sqlite":
        guarded = db.execute(
            update(StudySession)
            .where(StudySession.id == session_id, StudySession.student_id == student_id)
            .values(updated_at=StudySession.updated_at)
        )
        if guarded.rowcount != 1:
            raise not_found()
    session = db.scalar(statement.with_for_update().execution_options(populate_existing=True))
    if session is None:
        raise not_found()
    db.info.setdefault("session_write_locks", {})[session.id] = db.get_transaction()
    return session


def get_owned_session(db: Session, student_id: str, session_id: str) -> StudySession:
    session = db.get(StudySession, session_id)
    if session is None or session.student_id != student_id:
        raise not_found()
    return session


def get_owned_attempt(
    db: Session, student_id: str, attempt_id: str, *, write=False
) -> tuple[Attempt, StudySession]:
    if write:
        identifier = db.scalar(
            select(Attempt.session_id)
            .join(StudySession, StudySession.id == Attempt.session_id)
            .where(Attempt.id == attempt_id, StudySession.student_id == student_id)
        )
        if identifier is None:
            raise not_found()
        session = lock_owned_session(db, student_id, identifier)
        attempt = db.scalar(
            select(Attempt)
            .where(Attempt.id == attempt_id, Attempt.session_id == session.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        attempt = db.get(Attempt, attempt_id)
        session = db.get(StudySession, attempt.session_id) if attempt is not None else None
    if attempt is None or session is None or session.student_id != student_id:
        raise not_found()
    return attempt, session


def get_draft(db: Session, attempt_id: str) -> HandwritingDraft:
    statement = select(HandwritingDraft).where(HandwritingDraft.attempt_id == attempt_id)
    if any(
        transaction is db.get_transaction()
        for transaction in db.info.get("session_write_locks", {}).values()
    ):
        statement = statement.with_for_update().execution_options(populate_existing=True)
    draft = db.scalar(statement)
    if draft is None:
        raise not_found()
    return draft


def _has_ink(draft: HandwritingDraft) -> bool:
    """草稿里至少有一笔。只有空白页不算。"""
    pages = (draft.strokes_json or {}).get("pages") or []
    return any(page.get("strokes") for page in pages)


def _submitted_rows(db: Session, session_id: str) -> list[tuple[str, int | None]]:
    statement = select(Attempt.id, Attempt.submission_no).where(
        Attempt.session_id == session_id, Attempt.status == "submitted"
    )
    if _locked(db, session_id):
        statement = statement.with_for_update()
    return [(identifier, number) for identifier, number in db.execute(statement)]


def submitted_count(db: Session, session_id: str) -> int:
    return len(_submitted_rows(db, session_id))


def open_attempt(db: Session, session_id: str) -> Attempt | None:
    statement = (
        select(Attempt)
        .where(Attempt.session_id == session_id, Attempt.status == "draft")
        .order_by(Attempt.attempt_no, Attempt.id)
        .limit(1)
    )
    if _locked(db, session_id):
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


# ---------------------------------------------------------------- 序列化


def serialize_session(db: Session, session: StudySession) -> StudySessionOut:
    created = db.info.get("created_session_versions", {}).get(session.id)
    version = (
        created[1]
        if created is not None and created[0] is db.get_transaction()
        else question_service.get_version(db, session.question_id, session.question_version)
    )
    active = open_attempt(db, session.id)
    submitted = _submitted_rows(db, session.id)
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
        first_submitted_attempt_id=next(
            (identifier for identifier, number in submitted if number == 1), None
        ),
        submitted_attempts=len(submitted),
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
        submission_no=attempt.submission_no,
        copied_from_attempt_id=attempt.copied_from_attempt_id,
        copied_from_revision=attempt.copied_from_revision,
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
    question_id = body.question_id.lower()
    if db.get_bind().dialect.name == "sqlite":
        db.execute(
            update(Question).where(Question.id == question_id).values(version=Question.version)
        )
    question = db.scalar(
        select(Question)
        .where(Question.id == question_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if question is None or question.status != "published":
        raise not_found()
    if (
        body.expected_question_version is not None
        and body.expected_question_version != question.version
    ):
        raise conflict(
            "question_version_conflict",
            "题目版本已更新，请保留原稿并确认要使用的题面",
            {
                "expected_question_version": body.expected_question_version,
                "current_question_version": question.version,
            },
        )

    # A locking/current read can observe a freshly published version which the
    # transaction's earlier RR snapshot cannot yet see. Keep that immutable row
    # for this transaction's create response rather than re-reading its snapshot.
    version = db.scalar(
        select(QuestionVersion)
        .where(
            QuestionVersion.question_id == question.id,
            QuestionVersion.version == question.version,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise not_found()

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
    db.info.setdefault("created_session_versions", {})[session.id] = (
        db.get_transaction(),
        version,
    )
    return session


# ---------------------------------------------------------------- 作答与草稿


def create_attempt(db: Session, student_id: str, session_id: str, *, now: datetime) -> Attempt:
    session = lock_owned_session(db, student_id, session_id.lower())
    if session.state == "DONE":
        raise conflict("invalid_state", "这次学习已经结束，请重新开始一次会话")
    existing = open_attempt(db, session.id)
    if existing is not None:
        raise conflict(
            "attempt_in_progress", "这次会话里还有一份没有提交的作答", {"attempt_id": existing.id}
        )

    return _append_attempt(db, session, now=now)


def _append_attempt(
    db: Session,
    session: StudySession,
    *,
    now: datetime,
    source: Attempt | None = None,
    source_revision: int | None = None,
    answer: dict | None = None,
    strokes: dict | None = None,
) -> Attempt:

    last_number = db.scalar(
        select(Attempt.attempt_no)
        .where(Attempt.session_id == session.id)
        .order_by(Attempt.attempt_no.desc())
        .limit(1)
        .with_for_update()
    )
    attempt_no = (last_number or 0) + 1
    attempt = Attempt(
        id=new_id(),
        session_id=session.id,
        attempt_no=attempt_no,
        status="draft",
        copied_from_attempt_id=source.id if source is not None else None,
        copied_from_revision=source_revision,
        answer_json=answer,
        # 同一会话里的重试已经看过上一次的反馈，不再算独立作答
        assisted=session.assisted or submitted_count(db, session.id) > 0,
        used_solution=session.used_solution,
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)
    db.flush()
    db.add(
        HandwritingDraft(
            id=new_id(),
            attempt_id=attempt.id,
            revision=1 if source is not None else 0,
            strokes_json=strokes,
            updated_at=now,
        )
    )
    if session.state == "READY":
        session.state = "INDEPENDENT_ATTEMPT"
    session.updated_at = now
    db.flush()
    return attempt


def create_draft_copy(
    db: Session, student_id: str, attempt_id: str, body: DraftCopyCreateIn, *, now: datetime
) -> DraftCopyOut:
    source, session = get_owned_attempt(db, student_id, attempt_id, write=True)
    if source.status != "draft":
        raise conflict("attempt_already_submitted", "源作答已经提交，不能再创建草稿副本")
    if session.state == "DONE":
        raise conflict("invalid_state", "这次学习已经结束，草稿仍保留")
    draft = get_draft(db, source.id)
    if draft.revision != body.source_revision:
        raise conflict(
            "draft_revision_conflict",
            "云端草稿又有更新，没有覆盖任何一方",
            {
                "server_revision": draft.revision,
                "server_draft": serialize_draft(source, draft).model_dump(mode="json"),
            },
        )
    # Use a current locking read after the owned-session lock, including MySQL RR.
    published = db.scalar(
        select(Question)
        .where(Question.id == session.question_id, Question.status == "published")
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if published is None:
        raise not_found()
    new = _append_attempt(
        db,
        session,
        now=now,
        source=source,
        source_revision=draft.revision,
        answer=body.answer.model_dump(exclude_none=True) if body.answer is not None else None,
        strokes=body.strokes.model_dump() if body.strokes is not None else None,
    )
    return DraftCopyOut(
        session=serialize_session(db, session),
        attempt=serialize_attempt(db, new),
        draft=serialize_draft(new, get_draft(db, new.id)),
    )


def list_question_drafts(db, student_id, question_id, *, cursor, limit):
    question_service.get_published_question(db, question_id)
    offset = question_service.decode_cursor(cursor)
    statement = (
        select(
            StudySession.id.label("session_id"),
            Attempt.id.label("attempt_id"),
            StudySession.question_version,
            Attempt.attempt_no,
            HandwritingDraft.revision.label("draft_revision"),
            Attempt.copied_from_attempt_id,
            Attempt.copied_from_revision,
            StudySession.origin,
            StudySession.review_item_id,
            StudySession.state.label("session_state"),
            Attempt.updated_at,
        )
        .select_from(Attempt)
        .join(StudySession, StudySession.id == Attempt.session_id)
        .join(HandwritingDraft, HandwritingDraft.attempt_id == Attempt.id)
        .where(
            StudySession.student_id == student_id,
            StudySession.question_id == question_id,
            Attempt.status == "draft",
        )
        .order_by(StudySession.created_at.desc(), StudySession.id, Attempt.attempt_no, Attempt.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(db.execute(statement).mappings())
    return QuestionDraftPageOut(
        items=[QuestionDraftRefOut(**row) for row in rows[:limit]],
        next_cursor=question_service.encode_cursor(offset + limit) if len(rows) > limit else None,
    )


def sync_draft(
    db: Session, student_id: str, attempt_id: str, body: DraftSyncIn, *, now: datetime
) -> DraftOut:
    attempt, _ = get_owned_attempt(db, student_id, attempt_id, write=True)
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
    attempt, session = get_owned_attempt(db, student_id, attempt_id, write=True)
    if attempt.status != "draft":
        raise conflict("attempt_already_submitted", "这份作答已经提交过了")

    draft = get_draft(db, attempt.id)
    if body.expected_draft_revision is not None and body.expected_draft_revision != draft.revision:
        raise conflict(
            "submission_draft_revision_conflict",
            "草稿已在别处更新，请保留双方内容并确认提交快照",
            {
                "expected_draft_revision": body.expected_draft_revision,
                "server_revision": draft.revision,
                "server_draft": serialize_draft(attempt, draft).model_dump(mode="json"),
            },
        )

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
            # 解答题可以只手写、不打字：笔迹随草稿同步，这里看草稿里有没有笔迹
            has_ink=_has_ink(draft),
        )
    except grading.AnswerShapeError as error:
        raise unprocessable(error.field, error.message) from error

    submission_no = submitted_count(db, session.id) + 1
    independent = (
        submission_no == 1
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
    attempt.submission_no = submission_no
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
