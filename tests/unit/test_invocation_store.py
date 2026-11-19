from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ai_gateway.audit import AuditRecord
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_store import InvocationStore, metadata


def test_persistence_session_exclusion_and_fencing(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "invocations.db"))
    metadata.create_all(engine)
    factory = sessionmaker(engine)
    rules = InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    store = InvocationStore(factory, rules)
    value = dict(
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
    store.prepare(value)
    assert store.prepare(value) == value
    store = InvocationStore(factory, rules)
    assert store.read("a" * 32, "b" * 64) == value
    assert store.read("a" * 32, "f" * 64) is None
    with pytest.raises(ValueError):
        store.prepare(dict(value, invocation_id="e" * 32))

    def claim(_):
        try:
            store.claim("a" * 32, "b" * 64, expected_fence=1)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(8))) == 1
    assert store.read("a" * 32, "b" * 64)["fence"] == 2
    assert store.prepare(value)["fence"] == 2
    with pytest.raises(ValueError):
        store.prepare(dict(value, fingerprint="f" * 64))
    with pytest.raises(ValueError):
        store.prepare(dict(value, budget_key="stu_" + "f" * 32))
    with pytest.raises(ValueError):
        store.prepare(dict(value, actor_digest="f" * 64))
    store.cancel("a" * 32, "b" * 64, expected_fence=2)
    store.prepare(dict(value, invocation_id="e" * 32))
    engine.dispose()


def test_dispatch_budget_and_marker_commit_together(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "dispatch.db"))
    metadata.create_all(engine)
    ModelBudgetUsage.__table__.create(engine)
    ModelCallAudit.__table__.create(engine)
    factory = sessionmaker(engine)
    store = InvocationStore(
        factory, InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    )
    value = dict(
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
    store.prepare(value)
    options = dict(
        expected_fence=1,
        attempt_id="e" * 32,
        estimated_cost_micros=3,
        request_cost_cap=3,
        student_limit=1,
        platform_limit=1,
    )
    with pytest.raises(ValueError):
        store.dispatch(
            value["invocation_id"], value["actor_digest"], **dict(options, platform_limit=0)
        )
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "prepared"
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []

    def reject_commit(db):
        raise RuntimeError("commit unavailable")

    event.listen(factory.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError, match="commit unavailable"):
            store.dispatch(value["invocation_id"], value["actor_digest"], **options)
    finally:
        event.remove(factory.class_, "before_commit", reject_commit)
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "prepared"
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
    store.now = lambda: datetime(2027, 1, 2, tzinfo=UTC)
    result = store.dispatch(value["invocation_id"], value["actor_digest"], **options)
    assert result["quota_day"] == "2027-01-02"
    assert result["state"] == "dispatch_unknown"
    recovered = InvocationStore(factory, store.transitions)
    assert (
        recovered.mark_unknown(value["invocation_id"], value["actor_digest"], expected_fence=1)[
            "state"
        ]
        == "outcome_unknown"
    )
    assert (
        recovered.mark_unknown(value["invocation_id"], value["actor_digest"], expected_fence=1)[
            "state"
        ]
        == "outcome_unknown"
    )
    for operation in (recovered.claim, recovered.cancel):
        with pytest.raises(ValueError):
            operation(value["invocation_id"], value["actor_digest"], expected_fence=1)
    with pytest.raises(ValueError):
        store.dispatch(value["invocation_id"], value["actor_digest"], **options)
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert next(row for row in rows if row.scope == "student").scope_key == value["budget_key"]
        assert all(row.request_count == 1 and row.estimated_cost_micros == 3 for row in rows)
    audit = AuditRecord(
        request_id="request",
        trace_id="trace",
        student_pseudonym=value["budget_key"],
        task_type="tutor_explain",
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
    from dataclasses import replace

    for field, invalid in [
        ("estimated_cost_micros", -1),
        ("estimated_cost_micros", True),
        ("estimated_cost_micros", 1.5),
        ("input_tokens", -1),
        ("provider_calls", True),
        ("status", "invented"),
    ]:
        with pytest.raises(ValueError):
            store.settle_metadata(
                value["invocation_id"],
                value["actor_digest"],
                expected_fence=1,
                attempt_id=options["attempt_id"],
                audit=replace(audit, **{field: invalid}),
            )
    event.listen(factory.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError):
            store.settle_metadata(
                value["invocation_id"],
                value["actor_digest"],
                expected_fence=1,
                attempt_id=options["attempt_id"],
                audit=audit,
            )
    finally:
        event.remove(factory.class_, "before_commit", reject_commit)
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "outcome_unknown"
    with factory() as db:
        assert list(db.scalars(select(ModelCallAudit))) == []
        assert all(row.estimated_cost_micros == 3 for row in db.scalars(select(ModelBudgetUsage)))
    result = store.settle_metadata(
        value["invocation_id"],
        value["actor_digest"],
        expected_fence=1,
        attempt_id=options["attempt_id"],
        audit=audit,
    )
    assert result["state"] == "settled_metadata"
    assert (
        store.settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id=options["attempt_id"],
            audit=audit,
        )
        == result
    )
    from dataclasses import replace

    with pytest.raises(ValueError):
        store.settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id=options["attempt_id"],
            audit=replace(audit, estimated_cost_micros=9),
        )
    with factory() as db:
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        assert all(row.estimated_cost_micros == 5 for row in db.scalars(select(ModelBudgetUsage)))
    with factory() as db:
        db.begin()
        with pytest.raises(ValueError):
            store.applied_in_transaction(
                db,
                value["invocation_id"],
                value["actor_digest"],
                expected_fence=1,
                context_digest="f" * 64,
            )
        db.rollback()
    other_engine = create_engine("sqlite:///" + str(tmp_path / "other-database.db"))
    with sessionmaker(other_engine)() as wrong_db:
        wrong_db.begin()
        with pytest.raises(ValueError, match="database does not match"):
            store.applied_in_transaction(
                wrong_db,
                value["invocation_id"],
                value["actor_digest"],
                expected_fence=1,
                context_digest=value["context_digest"],
            )
    other_engine.dispose()
    with factory() as db:
        db.begin()
        store.applied_in_transaction(
            db,
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            context_digest=value["context_digest"],
        )
        db.rollback()
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "settled_metadata"
    with factory.begin() as db:
        store.applied_in_transaction(
            db,
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            context_digest=value["context_digest"],
        )
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "applied"
    store.prepare(dict(value, invocation_id="f" * 32))
    engine.dispose()
