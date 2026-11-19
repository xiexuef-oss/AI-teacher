"""DRAFT301B1 review completion under real MySQL repeatable-read contention."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, current_thread

import pytest
from sqlalchemy import event, func, select, text
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401, F811
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.db import new_id
from tutor_api.errors import ApiError
from tutor_api.models import Attempt, HandwritingDraft, ReviewItem, StudySession
from tutor_api.services import review_scheduler


@pytest.mark.parametrize(
    "already_completed,different_session", [(False, False), (True, False), (True, True)]
)
def test_review_lock_refreshes_snapshot_and_advances_once(  # noqa: F811
    tutor_case,  # noqa: F811
    already_completed,
    different_session,
):
    case = tutor_case
    factory = case["factory"]
    # Use database-representable precision so DATETIME(3) rounding cannot make
    # this boundary fixture spuriously appear to be due in the future.
    now = datetime.now(UTC).replace(microsecond=0)
    review_id, first_id, later_id = new_id(), new_id(), new_id()
    student_id = case["tokens"]["student"]
    with factory() as db:
        db.add(
            ReviewItem(
                id=review_id,
                student_id=student_id,
                question_id=case["question"],
                status="scheduled",
                stage=0,
                due_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        session = db.get(StudySession, case["session"]["id"])
        session.origin = "review"
        session.review_item_id = review_id
        later_session_id = session.id
        if different_session:
            values = {
                column.name: getattr(session, column.name)
                for column in StudySession.__table__.columns
            }
            values["id"] = new_id()
            later_session_id = values["id"]
            db.add(StudySession(**values))
        db.commit()

    waiting, snapshot, proceed = Event(), Event(), Event()

    def complete(db, attempt_id):
        return review_scheduler.complete(
            db,
            case["app"].state.settings,
            student_id=student_id,
            review_id=review_id,
            attempt_id=attempt_id,
            now=now,
        )

    def stale_reader():
        with factory() as second:
            assert (
                second.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            )
            assert second.scalar(select(func.count()).select_from(Attempt)) == 0
            assert second.get(ReviewItem, review_id).stage == 0
            snapshot.set()
            assert proceed.wait(5)
            try:
                result = complete(second, later_id)
                second.commit()
                return result.result
            except ApiError as exc:
                second.rollback()
                return exc.code

    def observe(conn, cursor, sql, parameters, ctx, many):
        if (
            current_thread().name.startswith("review-waiter")
            and "study_sessions" in sql
            and "FOR UPDATE" in sql.upper()
        ):
            waiting.set()

    with factory() as holder:
        engine = holder.get_bind()
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="review-waiter") as pool:
                pending = pool.submit(stale_reader)
                try:
                    assert snapshot.wait(3)
                    # Commit draft IDs after the reader's snapshot, before the
                    # holder takes the canonical session -> attempts -> review locks.
                    with factory() as writer:
                        for identifier, created in ((first_id, 1), (later_id, 2)):
                            writer.add(
                                Attempt(
                                    id=identifier,
                                    session_id=later_session_id
                                    if identifier == later_id
                                    else case["session"]["id"],
                                    attempt_no=1 if different_session else created,
                                    status="draft",
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                        writer.commit()
                    sessions = list(
                        holder.scalars(
                            select(StudySession)
                            .where(
                                StudySession.student_id == student_id,
                                StudySession.review_item_id == review_id,
                            )
                            .with_hint(
                                StudySession, "FORCE INDEX (ix_sessions_review_owner)", "mysql"
                            )
                            .order_by(StudySession.id)
                            .with_for_update()
                        )
                    )
                    for session in sessions:
                        list(
                            holder.scalars(
                                select(Attempt)
                                .where(Attempt.session_id == session.id)
                                .with_hint(Attempt, "FORCE INDEX (uq_attempt_no)", "mysql")
                                .order_by(Attempt.attempt_no)
                                .with_for_update()
                            )
                        )
                    holder.scalar(
                        select(ReviewItem).where(ReviewItem.id == review_id).with_for_update()
                    )
                    proceed.set()
                    assert waiting.wait(3) and not pending.done()
                    for identifier, submission in (
                        (first_id, 1),
                        (later_id, 1 if different_session else 2),
                    ):
                        attempt = holder.get(Attempt, identifier)
                        attempt.status = "submitted"
                        attempt.submission_no = submission
                        attempt.evaluation_state = "verified"
                        attempt.is_correct = attempt.independent = True
                        attempt.submitted_at = now
                    holder.flush()
                    if already_completed:
                        assert complete(holder, first_id).result == "passed"
                    holder.commit()
                finally:
                    holder.rollback()
                    proceed.set()
                expected = (
                    "review_not_due"
                    if different_session
                    else ("review_already_completed" if already_completed else "passed")
                )
                assert pending.result(timeout=5) == expected
        finally:
            event.remove(engine, "before_cursor_execute", observe)
    with factory() as db:
        item = db.get(ReviewItem, review_id)
        assert (item.stage, item.last_attempt_id) == (1, first_id)


@pytest.fixture
def completion_case(tutor_case):  # noqa: F811
    case = tutor_case
    now = datetime.now(UTC).replace(microsecond=0)
    review_id = new_id()
    ids = [new_id() for _ in range(3)]
    with case["factory"]() as db:
        db.add(
            ReviewItem(
                id=review_id,
                student_id=case["tokens"]["student"],
                question_id=case["question"],
                stage=0,
                status="scheduled",
                due_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        session = db.get(StudySession, case["session"]["id"])
        session.origin = "review"
        session.review_item_id = review_id
        for number, identifier in enumerate(ids, 1):
            submitted = number == 3
            db.add(
                Attempt(
                    id=identifier,
                    session_id=session.id,
                    attempt_no=number,
                    submission_no=1 if submitted else None,
                    status="submitted" if submitted else "draft",
                    evaluation_state="verified" if submitted else None,
                    is_correct=True if submitted else None,
                    independent=True if submitted else None,
                    submitted_at=now if submitted else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()
        for identifier in ids:
            db.add(HandwritingDraft(id=new_id(), attempt_id=identifier, revision=0, updated_at=now))
        db.commit()
    return case, now, review_id, ids


def test_submit_and_complete_pending_draft_share_lock_order(completion_case):
    from tutor_api.schemas import SubmitIn
    from tutor_api.services import session_service

    case, now, review_id, (a, b, c) = completion_case
    factory = case["factory"]
    waiting = Event()
    with factory() as submitter:
        engine = submitter.get_bind()
        session_service.lock_owned_session(
            submitter, case["tokens"]["student"], case["session"]["id"]
        )

        def observe(conn, cursor, sql, parameters, ctx, many):
            if (
                current_thread().name.startswith("complete-pending")
                and "study_sessions" in sql
                and "FOR UPDATE" in sql.upper()
            ):
                waiting.set()

        def complete():
            with factory() as db:
                result = review_scheduler.complete(
                    db,
                    case["app"].state.settings,
                    student_id=case["tokens"]["student"],
                    review_id=review_id,
                    attempt_id=b,
                    now=now,
                )
                db.commit()
                return result

        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="complete-pending") as pool:
                pending = pool.submit(complete)
                try:
                    assert waiting.wait(3) and not pending.done()
                    result = session_service.submit_attempt(
                        submitter,
                        case["app"].state.settings,
                        case["tokens"]["student"],
                        a,
                        SubmitIn(
                            answer={
                                "selected_options": case["payload"]["question"]["answer"]["value"]
                            }
                        ),
                        key_digest="e" * 64,
                        request_id="submit-complete-order",
                        now=now,
                    )
                    assert result.attempt.submission_no == 2
                    submitter.commit()
                finally:
                    submitter.rollback()
                assert pending.result(timeout=5).review_item.stage == 1
        finally:
            event.remove(engine, "before_cursor_execute", observe)
    with factory() as db:
        item = db.get(ReviewItem, review_id)
        assert (item.stage, item.last_attempt_id) == (1, c)


def test_external_supplied_attempt_is_never_locked(completion_case):
    case, now, review_id, _ = completion_case
    student = case["student"]
    session = student.data(
        "POST",
        "/sessions",
        expect=201,
        json={"question_id": case["question"], "origin": "practice"},
    )
    external = student.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
    with case["factory"]() as completing:
        with pytest.raises(ApiError) as error:
            review_scheduler.complete(
                completing,
                case["app"].state.settings,
                student_id=case["tokens"]["student"],
                review_id=review_id,
                attempt_id=external["id"],
                now=now,
            )
        assert error.value.code == "attempt_not_for_this_review"
        # Keep the rejected request transaction open: a NOWAIT probe must still
        # acquire the supplied out-of-scope attempt immediately.
        with case["factory"]() as probe:
            assert (
                probe.scalar(
                    select(Attempt).where(Attempt.id == external["id"]).with_for_update(nowait=True)
                )
                is not None
            )
        completing.rollback()
