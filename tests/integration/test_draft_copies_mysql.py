# ruff: noqa: F811 -- imported fixtures are intentionally used as test parameters
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_managed_tutor_transactions import tutor_case  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.errors import conflict
from tutor_api.idempotency import key_digest
from tutor_api.models import Attempt, IdempotencyReceipt
from tutor_api.schemas import DraftCopyCreateIn, SubmitIn
from tutor_api.services import session_service


def original(case):
    return case["student"].data(
        "POST", "/attempts", expect=201, json={"session_id": case["session"]["id"]}
    )


def payload(case):
    return {
        "source_revision": 0,
        "answer": {"selected_options": case["payload"]["question"]["answer"]["value"]},
        "strokes": None,
    }


@pytest.mark.parametrize("same_key", [True, False])
def test_managed_concurrent_copies_replay_or_allocate_distinct_drafts(tutor_case, same_key):
    case = tutor_case
    source = original(case)
    start = Barrier(2)

    def invoke(index):
        start.wait(timeout=5)
        return case["student"].data(
            "POST",
            f"/attempts/{source['id']}/copies",
            expect=201,
            json=payload(case),
            key="parallel-copy-same" if same_key else f"parallel-copy-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, range(2)))
    identifiers = {row["attempt"]["id"] for row in results}
    assert len(identifiers) == (1 if same_key else 2)
    with case["factory"]() as db:
        rows = list(db.scalars(select(Attempt).where(Attempt.session_id == case["session"]["id"])))
        assert len(rows) == (2 if same_key else 3)
        assert {row.attempt_no for row in rows} == set(range(1, len(rows) + 1))
        assert all(row.status == "draft" and row.submission_no is None for row in rows)
        assert all(
            row.copied_from_attempt_id == source["id"] for row in rows if row.id != source["id"]
        )


@pytest.mark.parametrize("submit_first", [False, True])
def test_copy_and_submit_refresh_after_owned_session_lock(tutor_case, submit_first):
    case = tutor_case
    source = original(case)
    sid, uid = case["session"]["id"], case["tokens"]["student"]
    waiting = Event()
    with case["factory"]() as holder:
        session_service.lock_owned_session(holder, uid, sid)
        # The fixture's raw SQL factory and the API factory use distinct pools.
        engine = case["app"].state.session_factory.kw["bind"]

        def observe(_conn, _cursor, sql, _parameters, _context, _many):
            if "FROM study_sessions" in sql and "FOR UPDATE" in sql.upper():
                waiting.set()

        def pending_request():
            if submit_first:
                return case["student"].error(
                    "POST", f"/attempts/{source['id']}/copies", json=payload(case), expect=409
                )
            return case["student"].data(
                "POST",
                f"/attempts/{source['id']}/submit",
                json={"answer": payload(case)["answer"]},
            )

        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(pending_request)
                try:
                    assert waiting.wait(5)
                    event.remove(engine, "before_cursor_execute", observe)
                    if submit_first:
                        session_service.submit_attempt(
                            holder,
                            case["app"].state.settings,
                            uid,
                            source["id"],
                            SubmitIn(answer=payload(case)["answer"]),
                            key_digest=key_digest(uid, "holder-submit"),
                            request_id=str(uuid4()),
                            now=case["app"].state.clock(),
                        )
                    else:
                        session_service.create_draft_copy(
                            holder,
                            uid,
                            source["id"],
                            DraftCopyCreateIn(**payload(case)),
                            now=case["app"].state.clock(),
                        )
                    holder.commit()
                finally:
                    holder.rollback()
                result = pending.result(timeout=10)
        finally:
            if event.contains(engine, "before_cursor_execute", observe):
                event.remove(engine, "before_cursor_execute", observe)
    if submit_first:
        assert result["code"] == "attempt_already_submitted"
    else:
        assert result["attempt"]["submission_no"] == 1
        assert result["evaluation"]["independent"] is True
    with case["factory"]() as db:
        rows = list(db.scalars(select(Attempt).where(Attempt.session_id == sid)))
        assert len(rows) == (1 if submit_first else 2)
        assert sum(row.status == "submitted" for row in rows) == 1


def test_copy_and_durable_receipt_roll_back_together(tutor_case, monkeypatch):
    case = tutor_case
    source = original(case)
    uid, key = case["tokens"]["student"], "durable-copy-retry"
    store = case["app"].state.receipt_store
    finish = store.finish

    def fail(*args, **kwargs):
        finish(*args, **kwargs)
        raise conflict("copy_receipt_failure", "验证副本与回执同事务回滚")

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "finish", fail)
        case["student"].error(
            "POST", f"/attempts/{source['id']}/copies", json=payload(case), key=key, expect=409
        )
    with case["factory"]() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1
        assert (
            db.scalar(
                select(IdempotencyReceipt).where(
                    IdempotencyReceipt.actor_id == uid,
                    IdempotencyReceipt.key_digest == key_digest(uid, key),
                )
            )
            is None
        )
    saved = case["student"].data(
        "POST", f"/attempts/{source['id']}/copies", json=payload(case), key=key, expect=201
    )
    assert saved["attempt"]["copied_from_attempt_id"] == source["id"]
