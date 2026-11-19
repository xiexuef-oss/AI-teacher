"""Real create/copy/review service lock cycle and withdrawal current-read guard."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, current_thread

from sqlalchemy import event, select, text
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.db import new_id
from tutor_api.errors import ApiError
from tutor_api.models import ReviewItem, StudySession
from tutor_api.schemas import DraftCopyCreateIn, SessionCreateIn
from tutor_api.services import review_scheduler, session_service


def test_real_services_create_copy_review_do_not_form_three_way_deadlock(tutor_case, monkeypatch):  # noqa: F811
    case = tutor_case
    factory = case["factory"]
    engine = factory.kw["bind"]
    student = case["tokens"]["student"]
    now = datetime.now(UTC).replace(microsecond=0)
    review_id = new_id()
    source_session = "80000000-0000-4000-8000-000000000001"
    created_session = "40000000-0000-4000-8000-000000000001"
    with factory() as db:
        db.add(
            ReviewItem(
                id=review_id,
                student_id=student,
                question_id=case["question"],
                status="scheduled",
                stage=0,
                due_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        template = db.get(StudySession, case["session"]["id"])
        values = {c.name: getattr(template, c.name) for c in StudySession.__table__.columns}
        values.update(id=source_session, origin="review", review_item_id=review_id)
        db.add(StudySession(**values))
        db.flush()
        attempt = session_service.create_attempt(db, student, source_session, now=now)
        source_id = attempt.id
        db.commit()
    copy_ready, create_ready, release_copy, release_create = Event(), Event(), Event(), Event()
    connections = {}
    original_id = session_service.new_id
    monkeypatch.setattr(
        session_service,
        "new_id",
        lambda: (
            created_session if current_thread().name.startswith("cycle-create") else original_id()
        ),
    )

    def observe(conn, cursor, sql, parameters, ctx, many):
        name = current_thread().name
        upper = sql.upper()
        if (
            name.startswith("cycle-copy")
            and "FROM questions" in sql
            and ("FOR UPDATE" in upper or "LOCK IN SHARE MODE" in upper or "FOR SHARE" in upper)
        ):
            copy_ready.set()
            assert release_copy.wait(15)
        if name.startswith("cycle-create") and upper.startswith("INSERT INTO STUDY_SESSIONS"):
            create_ready.set()
            assert release_create.wait(15)

    def worker(kind):
        with factory() as db:
            connections[kind] = db.execute(text("SELECT CONNECTION_ID()")).scalar()
            try:
                if kind == "copy":
                    result = session_service.create_draft_copy(
                        db,
                        student,
                        source_id,
                        DraftCopyCreateIn(
                            source_revision=0, answer={"selected_options": []}, strokes=None
                        ),
                        now=now,
                    )
                    value = result.attempt.copied_from_attempt_id
                elif kind == "create":
                    result = session_service.create_session(
                        db,
                        student,
                        SessionCreateIn(
                            question_id=case["question"],
                            origin="review",
                            review_item_id=review_id,
                            expected_question_version=1,
                        ),
                        now=now,
                    )
                    value = result.id
                else:
                    review_scheduler.complete(
                        db,
                        case["app"].state.settings,
                        student_id=student,
                        review_id=review_id,
                        attempt_id=source_id,
                        now=now,
                    )
                    value = "unexpected_completion"
                db.commit()
                return value
            except ApiError as error:
                db.rollback()
                return error.code

    def waiting_on(requester, blocker):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if requester in connections and blocker in connections:
                with engine.connect() as conn:
                    count = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.threads r ON r.THREAD_ID=w.REQUESTING_THREAD_ID JOIN performance_schema.threads b ON b.THREAD_ID=w.BLOCKING_THREAD_ID WHERE r.PROCESSLIST_ID=:r AND b.PROCESSLIST_ID=:b"
                        ),
                        {"r": connections[requester], "b": connections[blocker]},
                    ).scalar()
                if count:
                    return True
            time.sleep(0.05)
        return False

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="cycle-copy") as cp,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="cycle-create") as cr,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="cycle-review") as rv,
        ):
            try:
                copy = cp.submit(worker, "copy")
                assert copy_ready.wait(8)
                create = cr.submit(worker, "create")
                assert create_ready.wait(8)
                review = rv.submit(worker, "review")
                assert waiting_on("review", "copy")
                release_create.set()
                assert waiting_on("create", "review")
                release_copy.set()
                assert copy.result(timeout=12) == source_id
                assert review.result(timeout=12) == "attempt_not_verified"
                assert create.result(timeout=12) == created_session
            finally:
                release_copy.set()
                release_create.set()
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_copy_waits_for_withdrawal_and_rechecks_current_published_status(tutor_case):  # noqa: F811
    from tutor_api.models import Question

    case = tutor_case
    factory = case["factory"]
    engine = factory.kw["bind"]
    source = case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )
    reading, proceed, waiting = Event(), Event(), Event()

    def copier():
        with factory() as db:
            assert db.get(Question, case["question"]).status == "published"
            reading.set()
            assert proceed.wait(8)
            try:
                session_service.create_draft_copy(
                    db,
                    case["tokens"]["student"],
                    source["id"],
                    DraftCopyCreateIn(source_revision=0, answer=None, strokes=None),
                    now=datetime.now(UTC),
                )
                db.commit()
                return "unexpected_success"
            except ApiError as error:
                db.rollback()
                return error.code

    def observe(conn, cursor, sql, params, ctx, many):
        if (
            current_thread().name.startswith("withdraw-copy")
            and "FROM questions" in sql
            and ("FOR SHARE" in sql.upper() or "LOCK IN SHARE MODE" in sql.upper())
        ):
            waiting.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            factory() as publisher,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="withdraw-copy") as pool,
        ):
            try:
                question = publisher.scalar(
                    select(Question).where(Question.id == case["question"]).with_for_update()
                )
                future = pool.submit(copier)
                assert reading.wait(8)
                question.status = "draft"
                publisher.flush()
                proceed.set()
                assert waiting.wait(8)
                assert not future.done()
                publisher.commit()
                assert future.result(timeout=10) == "not_found"
            finally:
                publisher.rollback()
                proceed.set()
    finally:
        event.remove(engine, "before_cursor_execute", observe)
