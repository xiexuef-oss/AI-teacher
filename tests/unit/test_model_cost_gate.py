import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_gateway.invocation_state import InvocationTransitions
from support.cost_cases import audit, record
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_store import InvocationBudgetExceeded, InvocationStore, metadata


@pytest.fixture
def stores(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "cost.db"))
    metadata.create_all(engine)
    ModelBudgetUsage.__table__.create(engine)
    ModelCallAudit.__table__.create(engine)
    factory = sessionmaker(engine)
    rules = InvocationTransitions(Path("contracts/model_invocation.schema.json"))

    def make(policy="pause_platform"):
        return InvocationStore(
            factory,
            rules,
            now=lambda: datetime(2026, 11, 17, tzinfo=UTC),
            overrun_policy=policy,
        )

    yield make, factory
    engine.dispose()


def send(store, value, attempt="c"):
    store.prepare(value)
    return store.dispatch(
        value["invocation_id"],
        value["actor_digest"],
        expected_fence=1,
        attempt_id=attempt * 32,
        estimated_cost_micros=3,
        request_cost_cap=10,
        student_limit=100,
        platform_limit=100,
    )


@pytest.mark.parametrize("policy", ["record_only", "pause_platform"])
def test_overrun_is_durable_idempotent_and_shared_across_instances(stores, policy):
    make, factory = stores
    store = make(policy)
    value = record()
    send(store, value)
    for _ in range(2):
        store.settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id="c" * 32,
            audit=audit(),
        )
    report = make("record_only").cost_gate.report()
    assert report["paused"] == (policy == "pause_platform")
    assert len(report["incidents"]) == 1
    incident = report["incidents"][0]
    assert incident["reserved_cost_micros"] == 3
    assert incident["observed_estimated_cost_micros"] == 5
    assert "prompt" not in incident and "response" not in incident
    next_store = make("record_only")  # Config changes must not bypass a persisted pause.
    if policy == "pause_platform":
        next_store.now = lambda: datetime(2026, 11, 18, tzinfo=UTC)
        with pytest.raises(InvocationBudgetExceeded, match="paused"):
            send(next_store, record("f"), "d")
        assert next_store.read("f" * 32, "b" * 64)["state"] == "prepared"
    else:
        send(next_store, record("f"), "d")
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert all(row.request_count == (1 if policy == "pause_platform" else 2) for row in rows)
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1


def test_review_requires_current_incident_and_cannot_be_undone_by_audit_replay(stores):
    make, _ = stores
    store = make()
    value = record()
    send(store, value)
    settle_args = (value["invocation_id"], value["actor_digest"])
    settle_kwargs = dict(expected_fence=1, attempt_id="c" * 32, audit=audit())
    store.settle_metadata(*settle_args, **settle_kwargs)
    for incident_id, reason in [("d" * 32, "pricing_corrected"), ("c" * 32, "free text")]:
        with pytest.raises(ValueError):
            store.cost_gate.resume(incident_id, reason=reason)
    store.cost_gate.resume("c" * 32, reason="pricing_corrected")
    store.settle_metadata(*settle_args, **settle_kwargs)
    report = store.cost_gate.report()
    assert report["paused"] is False
    assert report["incidents"][0]["review_reason"] == "pricing_corrected"
    send(store, record("f"), "d")


@pytest.mark.parametrize("cost", [None, 0, 3])
def test_unknown_or_below_reserve_usage_never_refunds_or_creates_overrun(stores, cost):
    make, factory = stores
    store = make()
    send(store, record())
    store.settle_metadata(
        "a" * 32, "b" * 64, expected_fence=1, attempt_id="c" * 32, audit=audit(cost)
    )
    assert store.cost_gate.report()["incidents"] == []
    with factory() as db:
        assert all(row.estimated_cost_micros == 3 for row in db.scalars(select(ModelBudgetUsage)))


def test_late_overrun_replaces_review_target_even_if_new_instance_only_records(stores):
    make, _ = stores
    store = make()
    send(store, record())
    send(store, record("f"), "d")  # Already admitted before the first overrun was known.
    store.settle_metadata("a" * 32, "b" * 64, expected_fence=1, attempt_id="c" * 32, audit=audit())
    make("record_only").settle_metadata(
        "f" * 32, "b" * 64, expected_fence=1, attempt_id="d" * 32, audit=audit(6)
    )
    with pytest.raises(ValueError, match="changed"):
        store.cost_gate.resume("c" * 32, reason="pricing_corrected")
    assert store.cost_gate.report()["incident_id"] == "d" * 32
    assert store.cost_gate.report()["paused"] is True
    store.cost_gate.resume("d" * 32, reason="provider_usage_verified")


def test_cost_cli_is_read_only_by_default_and_requires_pinned_explicit_review(
    stores, monkeypatch, capsys
):
    import model_cost_report as cli

    make, factory = stores
    store = make()
    send(store, record())
    store.settle_metadata("a" * 32, "b" * 64, expected_fence=1, attempt_id="c" * 32, audit=audit())
    monkeypatch.setattr(
        cli, "Settings", lambda: SimpleNamespace(env="local", database_url="unused")
    )
    monkeypatch.setattr(cli, "make_engine", lambda *a, **k: factory.kw["bind"])
    before = store.cost_gate.report()
    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is True
    assert store.cost_gate.report() == before
    with pytest.raises(SystemExit) as error:
        cli.main(["--resume-attempt", "c" * 32, "--reason", "pricing_corrected"])
    assert error.value.code == 2
    capsys.readouterr()
    assert store.cost_gate.report() == before
    assert cli.main(["--resume-attempt", "c" * 32, "--reason", "pricing_corrected", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["resumed"] is True
    assert store.cost_gate.report()["paused"] is False


def test_settlement_failure_rolls_back_gate_incident_audit_and_delta(stores, monkeypatch):
    make, factory = stores
    store = make()
    send(store, record())
    before = deepcopy(store.cost_gate.report())
    original = store.cost_gate.record_overrun

    def fail_after_gate(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after incident")

    monkeypatch.setattr(store.cost_gate, "record_overrun", fail_after_gate)
    with pytest.raises(RuntimeError, match="after incident"):
        store.settle_metadata(
            "a" * 32, "b" * 64, expected_fence=1, attempt_id="c" * 32, audit=audit()
        )
    assert store.cost_gate.report() == before
    assert store.read("a" * 32, "b" * 64)["state"] == "dispatch_unknown"
    with factory() as db:
        assert list(db.scalars(select(ModelCallAudit))) == []
        assert all(row.estimated_cost_micros == 3 for row in db.scalars(select(ModelBudgetUsage)))
