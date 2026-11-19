"""Real RR stale-view submission must read current locked draft before grading."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, current_thread

import pytest
from sqlalchemy import event, select, text
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.errors import ApiError
from tutor_api.idempotency import key_digest
from tutor_api.models import HandwritingDraft, IdempotencyReceipt
from tutor_api.schemas import DraftSyncIn, SubmitIn
from tutor_api.services import session_service

INK = {
    "version": 1,
    "pages": [
        {
            "width": 100,
            "height": 100,
            "strokes": [{"color": "#000000", "width": 2, "points": [1, 2, 0, 0.5, 3, 4, 1, 0.5]}],
        }
    ],
}


@pytest.mark.parametrize("expected", [0, 1])
def test_rr_submission_waits_for_synced_revision_not_old_identity(tutor_case, expected):  # noqa: F811
    case = tutor_case
    factory = case["factory"]
    engine = factory.kw["bind"]
    student = case["tokens"]["student"]
    now = datetime.now(UTC)
    attempt = case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )
    id = attempt["id"]
    snapshot, proceed, waiting = Event(), Event(), Event()
    option = case["payload"]["question"]["content"]["options"][0]["key"]

    def reader():
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            stale = db.scalar(select(HandwritingDraft).where(HandwritingDraft.attempt_id == id))
            assert stale.revision == 0 and stale.strokes_json is None
            snapshot.set()
            assert proceed.wait(8)
            try:
                result = session_service.submit_attempt(
                    db,
                    case["app"].state.settings,
                    student,
                    id,
                    SubmitIn(
                        answer={"selected_options": [option]}, expected_draft_revision=expected
                    ),
                    key_digest=key_digest(student, "rr-submit-key"),
                    request_id="rr-submit-request",
                    now=now,
                )
                db.commit()
                return result.attempt.status
            except ApiError as error:
                db.rollback()
                return error

    def observe(conn, cursor, sql, params, ctx, many):
        if (
            current_thread().name.startswith("submit-revision")
            and "study_sessions" in sql
            and "FOR UPDATE" in sql.upper()
        ):
            waiting.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            factory() as writer,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="submit-revision") as pool,
        ):
            try:
                current = session_service.sync_draft(
                    writer,
                    student,
                    id,
                    DraftSyncIn(
                        base_revision=0, answer={"selected_options": [option]}, strokes=INK
                    ),
                    now=now,
                )
                future = pool.submit(reader)
                assert snapshot.wait(8)
                proceed.set()
                assert waiting.wait(8)
                assert not future.done()
                writer.commit()
                result = future.result(timeout=12)
                if expected == 0:
                    assert result.code == "submission_draft_revision_conflict"
                    assert result.details["server_revision"] == 1
                    assert (
                        result.details["server_draft"]["strokes"]
                        == current.model_dump(mode="json")["strokes"]
                    )
                    assert case["student"].data("GET", f"/attempts/{id}")["status"] == "draft"
                else:
                    assert result == "submitted"
            finally:
                writer.rollback()
                proceed.set()
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_historical_sql_submit_canonical_body_still_replays(tutor_case):  # noqa: F811
    case = tutor_case
    attempt = case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )
    option = case["payload"]["question"]["content"]["options"][0]["key"]
    body = {"answer": {"selected_options": [option]}}
    path = f"/attempts/{attempt['id']}/submit"
    key = "historical-submit-key"
    first = case["student"].data("POST", path, json=body, key=key)
    old = SubmitIn(**body).model_dump(mode="json")
    old.pop("expected_draft_revision", None)
    canonical = json.dumps(
        {"m": "POST", "p": "/api/v1" + path, "b": old}, sort_keys=True, ensure_ascii=False
    )
    with case["factory"]() as db:
        receipt = db.scalar(
            select(IdempotencyReceipt).where(
                IdempotencyReceipt.key_digest == key_digest(case["tokens"]["student"], key)
            )
        )
        assert receipt.fingerprint == hashlib.sha256(canonical.encode()).hexdigest()
    assert case["student"].data("POST", path, json=body, key=key) == first
