from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from migration_runner import apply_migrations
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker
from test_mysql_migrations import mysql_engine  # noqa: F401

from ai_gateway.audit import AuditRecord
from ai_gateway.invocation_state import InvocationTransitions
from support.cost_cases import record as cost_record
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_maintenance import report_invocations
from tutor_api.services.invocation_store import InvocationStore, intents


def test_mysql_operator_invocation_scan_is_bounded_and_read_only(mysql_engine):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    store = InvocationStore(
        sessionmaker(mysql_engine),
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
    )
    for key in ("a", "b", "c"):
        store.prepare(cost_record(key))
    with store.factory() as db:
        before = list(db.execute(select(intents)).mappings())
    page = report_invocations(store, limit=2)
    assert [item["invocation_id"] for item in page["items"]] == ["a" * 32, "b" * 32]
    assert page["next_cursor"] == "b" * 32
    tail = report_invocations(store, after=page["next_cursor"], limit=2)
    assert [item["invocation_id"] for item in tail["items"]] == ["c" * 32]
    assert tail["next_cursor"] is None
    with store.factory() as db:
        assert list(db.execute(select(intents)).mappings()) == before


@pytest.mark.parametrize("context_kind", ["tutoring", "document"])
def test_mysql_concurrent_prepare_replays_one_intent(mysql_engine, context_kind):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    store = InvocationStore(
        sessionmaker(mysql_engine),
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
    )
    record = dict(
        schema_version=1,
        invocation_id="a" * 32,
        actor_digest="b" * 64,
        budget_key="stu_" + "b" * 32,
        session_digest="c" * 64,
        question_version=1,
        context_generation=0,
        fingerprint="d" * 64,
        context_digest="a" * 64,
        quota_day="2026-11-16",
        fence=1,
        state="prepared",
        attempts=[],
    )
    if context_kind == "document":
        del record["session_digest"], record["question_version"]
        record.update(
            schema_version=2,
            context_kind="document_ocr",
            resource_digest="c" * 64,
            file_digest="e" * 64,
            page=1,
        )
    barrier = Barrier(8)

    def prepare(_):
        barrier.wait(timeout=10)
        return store.prepare(record)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(prepare, range(8))) == [record] * 8
    with store.factory() as db:
        assert db.scalar(select(func.count()).select_from(intents)) == 1
    assert (
        store.claim(record["invocation_id"], record["actor_digest"], expected_fence=1)["fence"] == 2
    )
    assert store.prepare(record)["fence"] == 2

    def reject_commit(db):
        raise RuntimeError("injected commit failure")

    event.listen(store.factory.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            store.dispatch(
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=2,
                attempt_id="f" * 32,
                estimated_cost_micros=3,
                request_cost_cap=3,
                student_limit=1,
                platform_limit=1,
            )
    finally:
        event.remove(store.factory.class_, "before_commit", reject_commit)
    assert store.read(record["invocation_id"], record["actor_digest"])["state"] == "prepared"
    with store.factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
    barrier = Barrier(8)

    def dispatch(index):
        barrier.wait(timeout=10)
        try:
            store.dispatch(
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=2,
                attempt_id=f"{index:032x}",
                estimated_cost_micros=3,
                request_cost_cap=3,
                student_limit=1,
                platform_limit=1,
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(dispatch, range(8))) == 1
    with store.factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert all(row.request_count == 1 and row.estimated_cost_micros == 3 for row in rows)
        assert next(row for row in rows if row.scope == "student").scope_key == record["budget_key"]
    assert store.prepare(record)["state"] == "dispatch_unknown"
    recovered = InvocationStore(store.factory, store.transitions)
    assert (
        recovered.mark_unknown(record["invocation_id"], record["actor_digest"], expected_fence=2)[
            "state"
        ]
        == "outcome_unknown"
    )
    assert recovered.prepare(record)["state"] == "outcome_unknown"
    attempt_id = recovered.read(record["invocation_id"], record["actor_digest"])["attempts"][0][
        "attempt_id"
    ]
    audit = AuditRecord(
        request_id="request",
        trace_id="trace",
        student_pseudonym=record["budget_key"],
        task_type="ocr_extract" if context_kind == "document" else "tutor_explain",
        provider="test",
        model_id="test-model",
        status="ok",
        error_code=None,
        provider_calls=1,
        latency_ms=1,
        input_tokens=None,
        output_tokens=None,
        image_units=None,
        estimated_cost_micros=5,
        schema_valid=True,
        review_required=False,
        created_at=datetime.now(UTC),
    )
    barrier = Barrier(8)

    def settle(_):
        barrier.wait(timeout=10)
        return recovered.settle_metadata(
            record["invocation_id"],
            record["actor_digest"],
            expected_fence=2,
            attempt_id=attempt_id,
            audit=audit,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        settled = list(pool.map(settle, range(8)))
    assert all(result["state"] == "settled_metadata" for result in settled)
    with pytest.raises(ValueError):
        recovered.cancel(record["invocation_id"], record["actor_digest"], expected_fence=2)
    with store.factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert all(row.request_count == 1 and row.estimated_cost_micros == 5 for row in rows)
        assert db.scalar(select(func.count()).select_from(ModelCallAudit)) == 1
