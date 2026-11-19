from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_gateway.audit import AuditRecord
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_store import InvocationBudgetExceeded, InvocationStore, metadata


def document_record():
    return dict(
        schema_version=2,
        invocation_id="a" * 32,
        actor_digest="b" * 64,
        budget_key="stu_" + "b" * 32,
        context_kind="document_ocr",
        resource_digest="c" * 64,
        file_digest="d" * 64,
        page=1,
        context_generation=0,
        fingerprint="e" * 64,
        context_digest="f" * 64,
        quota_day="2026-11-17",
        fence=1,
        state="prepared",
        attempts=[],
    )


@pytest.fixture
def document_store(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "document.db"))
    metadata.create_all(engine)
    ModelBudgetUsage.__table__.create(engine)
    ModelCallAudit.__table__.create(engine)
    factory = sessionmaker(engine)
    rules = InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    store = InvocationStore(factory, rules, now=lambda: datetime(2026, 11, 17, tzinfo=UTC))
    yield store, factory
    engine.dispose()


def test_document_resource_exclusion_replay_and_identity(document_store):
    store, _ = document_store
    value = document_record()
    assert store.prepare(value) == value
    assert store.prepare(value) == value
    assert store.read(value["invocation_id"], "e" * 64) is None
    for changed in ({"page": 2}, {"file_digest": "f" * 64}, {"resource_digest": "e" * 64}):
        with pytest.raises(ValueError, match="identity"):
            store.prepare(dict(value, **changed))
    with pytest.raises(ValueError):
        store.prepare(dict(value, invocation_id="e" * 32))
    claimed = store.claim(value["invocation_id"], value["actor_digest"], expected_fence=1)
    assert claimed["fence"] == 2
    store.cancel(value["invocation_id"], value["actor_digest"], expected_fence=2)
    assert store.prepare(dict(value, invocation_id="e" * 32))["state"] == "prepared"


def test_document_dispatch_settlement_and_application_are_shared(document_store):
    store, factory = document_store
    value = document_record()
    store.prepare(value)
    options = dict(
        expected_fence=1,
        attempt_id="e" * 32,
        estimated_cost_micros=3,
        request_cost_cap=3,
        student_limit=1,
        platform_limit=0,
    )
    with pytest.raises(InvocationBudgetExceeded):
        store.dispatch(value["invocation_id"], value["actor_digest"], **options)
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "prepared"
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
    sent = store.dispatch(
        value["invocation_id"], value["actor_digest"], **dict(options, platform_limit=1)
    )
    assert sent["state"] == "dispatch_unknown"
    audit = AuditRecord(
        request_id="self-authored",
        trace_id="f" * 32,
        student_pseudonym=value["budget_key"],
        task_type="ocr_extract",
        provider="fake",
        model_id="fake",
        status="ok",
        error_code=None,
        provider_calls=1,
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        image_units=1,
        estimated_cost_micros=4,
        schema_valid=True,
        review_required=True,
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    for _ in range(2):
        store.settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id="e" * 32,
            audit=audit,
        )
    with factory.begin() as db:
        store.applied_in_transaction(
            db,
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            context_digest=value["context_digest"],
        )
    assert (
        store.settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id="e" * 32,
            audit=audit,
        )["state"]
        == "applied"
    )
    with factory() as db:
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        assert [b.estimated_cost_micros for b in db.scalars(select(ModelBudgetUsage))] == [4, 4]
    assert store.read(value["invocation_id"], value["actor_digest"])["state"] == "applied"
