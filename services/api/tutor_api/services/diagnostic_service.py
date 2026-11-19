"""Three-question practice plans, not ability estimates or official grades."""

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from tutor_api.db import new_id
from tutor_api.diagnostic_models import DiagnosticItem, DiagnosticRun, DiagnosticState
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.models import Attempt, Question, StudentProfile, User
from tutor_api.schemas import SessionCreateIn
from tutor_api.services import grading, question_service, session_service


def owned_run(db, student_id, run_id, *, current=False):
    query = select(DiagnosticRun).where(
        DiagnosticRun.id == run_id, DiagnosticRun.student_id == student_id
    )
    if current:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    run = db.scalar(query)
    if run is None:
        raise not_found()
    return run


def serialize_run(db, run, *, current=False):
    item_query = (
        select(DiagnosticItem)
        .where(DiagnosticItem.run_id == run.id)
        .order_by(DiagnosticItem.position)
    )
    if current:
        item_query = item_query.with_for_update(read=True).execution_options(populate_existing=True)
    items = list(db.scalars(item_query))
    query = select(Attempt).where(
        Attempt.session_id.in_([item.session_id for item in items if item.session_id]),
        Attempt.submission_no == 1,
        Attempt.status == "submitted",
    )
    if current:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    attempts = {attempt.session_id: attempt for attempt in db.scalars(query)}
    summary = dict.fromkeys(
        ("submitted", "independent_correct", "independent_incorrect", "assisted", "unconfirmed"), 0
    )
    result = []
    for item in items:
        attempt = attempts.get(item.session_id)
        submission = None
        if attempt is not None:
            confirmed = attempt.evaluation_state == "verified" and attempt.is_correct is not None
            summary["submitted"] += 1
            if not confirmed:
                summary["unconfirmed"] += 1
            elif not attempt.independent:
                summary["assisted"] += 1
            else:
                summary[
                    "independent_correct" if attempt.is_correct else "independent_incorrect"
                ] += 1
            submission = {
                "attempt_id": attempt.id,
                "independent": bool(attempt.independent),
                "evaluation_state": attempt.evaluation_state,
                "is_correct": attempt.is_correct if confirmed else None,
            }
        result.append(
            {
                "position": item.position,
                "question": item.summary_json,
                "question_version": item.question_version,
                "session_id": item.session_id,
                "submission": submission,
            }
        )
    status = (
        "abandoned"
        if run.abandoned_at is not None
        else "completed"
        if summary["submitted"] == 3
        else "active"
    )
    return {
        "id": run.id,
        "subject": run.subject,
        "scope": run.scope_json,
        "status": status,
        "items": result,
        "summary": summary,
        "created_at": run.created_at.isoformat(),
        "abandoned_at": run.abandoned_at.isoformat() if run.abandoned_at else None,
    }


def workspace(db, student_id):
    state = db.get(DiagnosticState, student_id)
    return {
        "revision": state.revision if state else 0,
        "run": serialize_run(db, owned_run(db, student_id, state.current_run_id))
        if state and state.current_run_id
        else None,
    }


def history(db, student_id, *, cursor=None, limit=20):
    query = select(DiagnosticRun).where(DiagnosticRun.student_id == student_id)
    if cursor is not None:
        anchor = db.scalar(query.where(DiagnosticRun.id == cursor))
        if anchor is None:
            raise ApiError(400, "invalid_cursor", "历史游标无效，请从第一页重新读取")
        query = query.where(
            or_(
                DiagnosticRun.created_at < anchor.created_at,
                and_(DiagnosticRun.created_at == anchor.created_at, DiagnosticRun.id < anchor.id),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(DiagnosticRun.created_at.desc(), DiagnosticRun.id.desc()).limit(
                limit + 1
            )
        )
    )
    return {
        "items": [serialize_run(db, run) for run in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


def _lock_state(db, student_id, expected_revision):
    # Profile writes lock the owner first too. Shared ownership precedes plan,
    # profile and question locks, including the FK checks of a new solve session.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(User).where(User.id == student_id).values(updated_at=User.updated_at))
    db.scalar(select(User).where(User.id == student_id).with_for_update(read=True))
    insert = mysql_insert if db.get_bind().dialect.name == "mysql" else sqlite_insert
    statement = insert(DiagnosticState).values(student_id=student_id, revision=0)
    statement = (
        statement.on_duplicate_key_update(student_id=DiagnosticState.student_id)
        if db.get_bind().dialect.name == "mysql"
        else statement.on_conflict_do_nothing(index_elements=["student_id"])
    )
    db.execute(statement)
    state = db.scalar(
        select(DiagnosticState)
        .where(DiagnosticState.student_id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state.revision != expected_revision:
        raise conflict(
            "diagnostic_revision_conflict",
            "摸底进度已更新，请刷新后确认",
            {"current_revision": state.revision},
        )
    return state


def _profile(db, student_id):
    profile = db.scalar(
        select(StudentProfile)
        .where(StudentProfile.user_id == student_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if profile is None:
        raise unprocessable("profile", "请先完成学习资料")
    return profile


def create(db, student_id, body, now):
    state = _lock_state(db, student_id, body.expected_revision)
    if state.current_run_id:
        previous = serialize_run(
            db, owned_run(db, student_id, state.current_run_id, current=True), current=True
        )
        if previous["status"] == "active":
            raise conflict("diagnostic_active", "请继续当前摸底，或明确结束后另开")
    profile = _profile(db, student_id)
    if profile.revision != body.expected_profile_revision:
        raise conflict("diagnostic_profile_conflict", "学习资料已更新，请刷新后重新确认")
    if profile.region_code is None or body.subject not in (profile.subjects_json or []):
        raise unprocessable("subject", "请先选择地区和本轮学科")
    scope = question_service.student_scope(db, student_id)
    candidates = [
        question
        for question, _ in question_service.deliverable_questions(db, scope, subject=body.subject)
        if question.answer_mode not in grading.SUBJECTIVE_MODES
        and question.variant_of_id is None
        and (profile.grade is None or question.grade in (None, profile.grade))
    ]
    if len(candidates) < 3:
        raise unprocessable("subject", "当前资料下可用客观题不足三道，请稍后再试或选择其他学科")
    selected = candidates[:3]
    versions = {question.id: question.version for question in selected}
    locked = list(
        db.scalars(
            select(Question)
            .where(Question.id.in_(versions))
            .order_by(Question.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if any(
        question.status != "published" or question.version != versions[question.id]
        for question in locked
    ):
        raise conflict("question_version_conflict", "选题期间题库已更新，请刷新后重试")
    summaries = question_service.summarize(db, selected, scope)
    run = DiagnosticRun(
        id=new_id(),
        student_id=student_id,
        subject=body.subject,
        scope_json={
            "profile_revision": profile.revision,
            "region_code": profile.region_code,
            "grade": profile.grade,
            "exam_year": profile.exam_year,
            "curriculum_version": profile.curriculum_version,
        },
        created_at=now,
    )
    db.add(run)
    db.flush()
    for position, question in enumerate(selected, 1):
        db.add(
            DiagnosticItem(
                run_id=run.id,
                position=position,
                question_id=question.id,
                question_version=question.version,
                summary_json=summaries[question.id].model_dump(mode="json"),
            )
        )
    state.current_run_id = run.id
    state.revision += 1
    db.flush()
    return workspace(db, student_id)


def _current_run(db, student_id, run_id, body):
    owned_run(db, student_id, run_id)  # Ownership before revision details.
    state = _lock_state(db, student_id, body.expected_revision)
    run = owned_run(db, student_id, run_id, current=True)
    if state.current_run_id != run.id or run.abandoned_at is not None:
        raise conflict("diagnostic_inactive", "这轮摸底已结束，请刷新当前进度")
    return run, state


def open_session(db, student_id, run_id, position, body, now):
    run, state = _current_run(db, student_id, run_id, body)
    item = db.scalar(
        select(DiagnosticItem)
        .where(DiagnosticItem.run_id == run.id, DiagnosticItem.position == position)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item.session_id:
        return session_service.serialize_session(
            db, session_service.get_owned_session(db, student_id, item.session_id)
        )
    profile = _profile(db, student_id)
    if profile.revision != run.scope_json["profile_revision"]:
        raise conflict(
            "diagnostic_profile_conflict", "学习资料已更新，请保留当前记录并明确结束后另开"
        )
    session = session_service.create_session(
        db,
        student_id,
        SessionCreateIn(
            question_id=item.question_id,
            origin="practice",
            expected_question_version=item.question_version,
        ),
        now=now,
    )
    item.session_id = session.id
    state.revision += 1
    db.flush()
    return session_service.serialize_session(db, session)


def abandon(db, student_id, run_id, body, now):
    run, state = _current_run(db, student_id, run_id, body)
    run.abandoned_at = now
    state.revision += 1
    db.flush()
    return workspace(db, student_id)
