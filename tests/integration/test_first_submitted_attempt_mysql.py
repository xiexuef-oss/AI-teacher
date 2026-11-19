"""First-submission recovery reads current rows after the Session lock under RR."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, current_thread

from sqlalchemy import event, text
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.idempotency import key_digest
from tutor_api.models import Attempt
from tutor_api.schemas import SubmitIn
from tutor_api.services import session_service


def test_first_pointer_is_current_after_waiting_for_submission(tutor_case):  # noqa: F811
    case = tutor_case
    sid = case["session"]["id"]
    owner = case["tokens"]["student"]
    factory = case["factory"]
    engine = factory.kw["bind"]
    original = case["student"].data("POST", "/attempts", expect=201, json={"session_id": sid})
    option = case["payload"]["question"]["content"]["options"][0]["key"]
    answer = {"selected_options": [option]}
    copied = case["student"].data(
        "POST",
        f"/attempts/{original['id']}/copies",
        expect=201,
        json={"source_revision": 0, "answer": answer, "strokes": None},
    )["attempt"]
    snapshot, proceed, waiting = Event(), Event(), Event()

    def reader():
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            stale = db.get(Attempt, copied["id"])
            assert stale.submission_no is None
            before = session_service.serialize_session(
                db, session_service.get_owned_session(db, owner, sid)
            )
            assert before.first_submitted_attempt_id is None
            snapshot.set()
            assert proceed.wait(8)
            locked = session_service.lock_owned_session(db, owner, sid)
            current = session_service.serialize_session(db, locked)
            assert stale.submission_no is None, "stale ORM identity is deliberately retained"
            db.rollback()
            return current

    def observe(conn, cursor, sql, params, ctx, many):
        if (
            current_thread().name.startswith("first-pointer")
            and "study_sessions" in sql
            and "FOR UPDATE" in sql.upper()
        ):
            waiting.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            factory() as writer,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="first-pointer") as pool,
        ):
            future = pool.submit(reader)
            assert snapshot.wait(8)
            submitted = session_service.submit_attempt(
                writer,
                case["app"].state.settings,
                owner,
                copied["id"],
                SubmitIn(answer=answer),
                key_digest=key_digest(owner, "first-pointer-submit"),
                request_id="first-pointer-submit",
                now=datetime.now(UTC),
            )
            assert submitted.session.first_submitted_attempt_id == copied["id"]
            proceed.set()
            assert waiting.wait(8), "reader actually reaches the held Session lock"
            writer.commit()
            result = future.result(timeout=12)
            assert result.first_submitted_attempt_id == copied["id"]
            assert result.active_attempt_id == original["id"]
            assert result.submitted_attempts == 1
    finally:
        proceed.set()
        event.remove(engine, "before_cursor_execute", observe)
