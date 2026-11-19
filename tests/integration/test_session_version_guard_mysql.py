"""Real MySQL RR snapshot and publish/create ordering for version protection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, current_thread

import pytest
from sqlalchemy import event, select, text
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.db import new_id
from tutor_api.errors import ApiError
from tutor_api.models import Question, QuestionVersion
from tutor_api.schemas import SessionCreateIn
from tutor_api.services import session_service


@pytest.mark.parametrize("expected", [1, 2])
def test_rr_old_snapshot_waits_for_publish_and_pins_checked_version(tutor_case, expected):  # noqa: F811
    case = tutor_case
    factory = case["factory"]
    snapshot, proceed, waiting = Event(), Event(), Event()
    now = datetime.now(UTC)

    def creator():
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            assert db.get(Question, case["question"]).version == 1
            snapshot.set()
            assert proceed.wait(10)
            try:
                row = session_service.create_session(
                    db,
                    case["tokens"]["student"],
                    SessionCreateIn(
                        question_id=case["question"],
                        origin="practice",
                        expected_question_version=expected,
                    ),
                    now=now,
                )
                serialized = session_service.serialize_session(db, row)
                db.commit()
                return serialized.question_version
            except ApiError as error:
                db.rollback()
                return error.code

    def observe(conn, cursor, sql, parameters, ctx, many):
        if (
            current_thread().name.startswith("session-version")
            and "questions" in sql
            and ("LOCK IN SHARE MODE" in sql.upper() or "FOR SHARE" in sql.upper())
        ):
            waiting.set()

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            factory() as publisher,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-version") as pool,
        ):
            question = publisher.scalar(
                select(Question).where(Question.id == case["question"]).with_for_update()
            )
            future = pool.submit(creator)
            assert snapshot.wait(10)
            old = publisher.scalar(
                select(QuestionVersion).where(
                    QuestionVersion.question_id == question.id, QuestionVersion.version == 1
                )
            )
            values = {
                column.name: getattr(old, column.name)
                for column in QuestionVersion.__table__.columns
            }
            values.update(id=new_id(), version=2)
            publisher.add(QuestionVersion(**values))
            question.version = 2
            publisher.flush()
            proceed.set()
            assert waiting.wait(10)
            assert not future.done()
            publisher.commit()
            assert future.result(timeout=15) == (
                "question_version_conflict" if expected == 1 else 2
            )
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_durable_legacy_session_receipt_keeps_original_canonical_body(tutor_case):  # noqa: F811
    import hashlib
    import json

    from tutor_api.idempotency import key_digest
    from tutor_api.models import IdempotencyReceipt

    case = tutor_case
    key = "historical-session-command-key"
    body = {"question_id": case["question"], "origin": "practice"}
    first = case["student"].data("POST", "/sessions", expect=201, json=body, key=key)
    old_canonical = json.dumps(
        {
            "m": "POST",
            "p": "/api/v1/sessions",
            "b": {**body, "review_item_id": None, "parent_session_id": None},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(old_canonical.encode("utf-8")).hexdigest()
    with case["factory"]() as db:
        receipt = db.scalar(
            select(IdempotencyReceipt).where(
                IdempotencyReceipt.key_digest == key_digest(case["tokens"]["student"], key)
            )
        )
        assert receipt.fingerprint == fingerprint
        receipt.fingerprint = fingerprint
        db.commit()
    assert case["student"].data("POST", "/sessions", expect=201, json=body, key=key) == first
