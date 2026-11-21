"""Standalone SDK uses the existing SQL intent, budget and audit transactions."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_gateway import GatewayConfig, build_gateway
from ai_gateway.durable import invoke
from ai_gateway.invocation_state import InvocationTransitions
from support import REPO_ROOT
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    SECRET_TEXT,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    make_request,
    timeout,
)
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_maintenance import report_invocations
from tutor_api.services.invocation_store import InvocationStore, intents, metadata

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "sdk.db"))
    metadata.create_all(engine)
    ModelBudgetUsage.__table__.create(engine)
    ModelCallAudit.__table__.create(engine)
    value = InvocationStore(
        sessionmaker(engine),
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
        now=lambda: NOW,
    )
    yield value
    engine.dispose()


def gateway(store, adapter=None):
    adapter = adapter if adapter is not None else ScriptedProvider(hint_ok())
    result = build_gateway(
        GatewayConfig.model_validate(config_dict({"x": external_provider()}, ["x"])),
        env=FULL_ENV,
        environment="local",
        allow_external_calls=True,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"x": adapter},
        now=lambda: NOW,
    )
    result.bind_durable_invocations(store, secret="sdk-test-stable-secret")
    return result, adapter


def request(**kwargs):
    return make_request(student_pseudonym="stu_" + "a" * 32, **kwargs)


def records(store):
    with store.factory() as db:
        return list(db.execute(select(intents)).mappings())


def test_sdk_sends_only_after_committed_attempt_and_settles_once(store):
    class Observe(ScriptedProvider):
        def invoke(self, **kwargs):
            row = records(store)[0]
            assert row["state"] == "dispatch_unknown"
            with store.factory() as db:
                buckets = db.scalars(select(ModelBudgetUsage)).all()
                assert len(buckets) == 2
                assert all(b.request_count == 1 and b.estimated_cost_micros > 0 for b in buckets)
            return super().invoke(**kwargs)

    sdk, adapter = gateway(store, Observe(hint_ok()))
    result = sdk.invoke(request())
    assert result.status == "ok" and result.provider_calls == 1
    value = records(store)[0]["metadata_json"]
    assert value["state"] == "settled_metadata"
    assert value["schema_version"] == 3 and value["context_kind"] == "sdk_request"
    assert SECRET_TEXT not in json.dumps(value)
    assert "session_digest" not in value and "file_digest" not in value
    restarted, _ = gateway(store, adapter)
    replay = restarted.invoke(request(trace_id="new-transport-trace"))
    assert replay.status == "degraded" and replay.validated_output is None
    assert replay.error_code == "INVOCATION_ALREADY_SETTLED"
    assert len(adapter.calls) == 1
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 1
        assert all(b.request_count == 1 for b in db.scalars(select(ModelBudgetUsage)))
    assert report_invocations(store)["items"][0]["context_kind"] == "sdk_request"


def test_guarded_business_invocation_checks_context_before_budget_or_send(store):
    sdk, adapter = gateway(store)
    sdk.require_durable_external_calls()

    def reject(_db):
        raise ValueError("task lease is inactive")

    result = invoke(sdk, request(), store, "sdk-test-stable-secret", context_guard=reject)
    assert result.error_code == "INVOCATION_UNAVAILABLE" and not adapter.calls
    with store.factory() as db:
        assert not db.scalars(select(ModelBudgetUsage)).all()
        assert not db.scalars(select(ModelCallAudit)).all()


def test_sdk_same_key_changed_request_never_sends_again(store):
    sdk, adapter = gateway(store)
    assert sdk.invoke(request()).status == "ok"
    changed = request().model_copy(
        update={"constraints": request().constraints.model_copy(update={"language": "en"})}
    )
    result = sdk.invoke(changed)
    assert result.error_code == "INVOCATION_CONFLICT"
    assert len(adapter.calls) == 1 and len(records(store)) == 1


def test_sdk_crashed_sender_is_not_repeated_by_new_gateway(store):
    sdk, adapter = gateway(store, ScriptedProvider(SystemExit(23)))
    with pytest.raises(SystemExit):
        sdk.invoke(request())
    assert records(store)[0]["state"] == "dispatch_unknown"
    restarted, _ = gateway(store, adapter)
    result = restarted.invoke(request())
    assert result.error_code == "INVOCATION_UNCERTAIN"
    assert len(adapter.calls) == 1
    with store.factory() as db:
        assert db.scalars(select(ModelCallAudit)).all() == []


@pytest.mark.parametrize("operation", ["prepare", "dispatch", "settle_metadata"])
def test_sdk_storage_failure_never_exposes_output_or_private_details(store, monkeypatch, operation):
    sdk, adapter = gateway(store)

    def broken(*args, **kwargs):
        raise RuntimeError("private SQL credential details")

    monkeypatch.setattr(store, operation, broken)
    result = sdk.invoke(request())
    assert result.status == "degraded" and result.validated_output is None
    assert "private" not in result.model_dump_json()
    assert len(adapter.calls) == (1 if operation == "settle_metadata" else 0)
    assert result.provider_calls == len(adapter.calls)


def test_sdk_mode_cannot_bypass_application_durable_or_disabled_policy(store):
    sdk, adapter = gateway(store)
    sdk.require_durable_external_calls()
    result = sdk.invoke(request())
    assert result.status == "degraded" and not adapter.calls and records(store) == []
    sdk.disable_external_calls()
    assert sdk.invoke(request()).status == "degraded"
    assert not adapter.calls and records(store) == []


@pytest.mark.parametrize("policy", ["disabled", "durable"])
def test_sdk_revocation_after_dispatch_keeps_conservative_reservation(store, monkeypatch, policy):
    sdk, adapter = gateway(store)
    original = store.dispatch

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        if policy == "disabled":
            sdk.disable_external_calls()
        else:
            sdk.require_durable_external_calls()
        return value

    monkeypatch.setattr(store, "dispatch", revoke)
    result = sdk.invoke(request())
    assert result.status == "degraded" and not adapter.calls
    assert records(store)[0]["state"] == "outcome_unknown"
    with store.factory() as db:
        assert all(
            b.request_count == 1 and b.estimated_cost_micros > 0
            for b in db.scalars(select(ModelBudgetUsage))
        )


def test_sdk_concurrent_same_key_has_one_sender_and_audit(store):
    sdk, adapter = gateway(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sdk.invoke(request()), range(2)))
    assert sum(result.status == "ok" for result in results) == 1
    assert len(adapter.calls) == 1 and len(records(store)) == 1
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 1
        assert all(b.request_count == 1 for b in db.scalars(select(ModelBudgetUsage)))


def test_sdk_timeout_is_settled_without_legacy_retry_or_fallback(store):
    sdk, adapter = gateway(store, ScriptedProvider(timeout(), hint_ok()))
    response = sdk.invoke(request())
    assert response.error_code == "TIMEOUT" and response.provider_calls == 1
    assert records(store)[0]["state"] == "settled_metadata"
    assert sdk.invoke(request()).error_code == "INVOCATION_ALREADY_SETTLED"
    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", ""),
        ("request_id", "a" * 129),
        ("trace_id", "a" * 65),
        ("student_pseudonym", "private-user-id"),
    ],
)
def test_sdk_invalid_audit_identity_is_rejected_before_preparation(store, field, value):
    sdk, adapter = gateway(store)
    result = sdk.invoke(request().model_copy(update={field: value}))
    assert result.error_code == "INVALID_INVOCATION_IDENTITY"
    assert not adapter.calls and not records(store)


def test_sdk_pause_committed_after_dispatch_blocks_the_adapter(store, monkeypatch):
    from sqlalchemy import update

    from tutor_api.services.invocation_tables import dispatch_gate

    sdk, adapter = gateway(store)
    original = store.dispatch

    def pause(*args, **kwargs):
        value = original(*args, **kwargs)
        with store.factory.begin() as db:
            db.execute(update(dispatch_gate).values(paused=True))
        return value

    monkeypatch.setattr(store, "dispatch", pause)
    assert sdk.invoke(request()).error_code == "INVOCATION_UNCERTAIN"
    assert not adapter.calls


@pytest.mark.parametrize("change", ["provider", "price", "cap"])
def test_sdk_rechecks_authorization_and_price_after_guard_io(store, change):
    sdk, adapter = gateway(store)

    def changed_during_io():
        if change == "provider":
            sdk._config.providers["x"].enabled = False
        elif change == "price":
            sdk._config.providers["x"].pricing.output_per_1k_tokens_micros *= 100
        else:
            sdk._config.budgets.per_request_max_cost_micros = 0
        return True

    sdk.bind_dispatch_guard(changed_during_io)
    assert sdk.invoke(request()).error_code == "INVOCATION_UNCERTAIN"
    assert not adapter.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_kind", "document_ocr"),
        ("session_digest", "a" * 64),
        ("question_version", 1),
        ("file_digest", "a" * 64),
        ("page", 1),
    ],
)
def test_sdk_metadata_cannot_claim_tutoring_or_document_context(store, field, value):
    sdk, _ = gateway(store)
    assert sdk.invoke(request()).status == "ok"
    row = records(store)[0]["metadata_json"]
    row[field] = value
    with pytest.raises(ValueError, match="metadata"):
        store.transitions._checked(row, row["fence"], row["state"])


def test_actual_sdk_process_exit_keeps_attempt_and_prevents_restart_send(store):
    database_url = str(store.factory.kw["bind"].url)
    script = f"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.services.invocation_store import InvocationStore
from unit.test_sdk_durable_invocations import gateway, request, NOW
engine = create_engine({database_url!r})
store = InvocationStore(sessionmaker(engine),
    InvocationTransitions(Path('contracts/model_invocation.schema.json')), now=lambda: NOW)
class ExitWorker:
    def invoke(self, **kwargs):
        os._exit(23)
sdk, _ = gateway(store, ExitWorker())
sdk.invoke(request())
raise AssertionError('adapter exit was not reached')
"""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.update(
        PYTHONUTF8="1",
        PYTHONPATH=os.pathsep.join(
            str(REPO_ROOT / p) for p in ("services/api", "services/ai_gateway", "tests")
        ),
    )
    exited = subprocess.run(
        [sys.executable, "-"],
        input=script.encode(),
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=20,
    )
    assert exited.returncode == 23
    assert records(store)[0]["state"] == "dispatch_unknown"
    sdk, adapter = gateway(store)
    assert sdk.invoke(request()).error_code == "INVOCATION_UNCERTAIN"
    assert not adapter.calls
    with store.factory() as db:
        assert db.scalars(select(ModelCallAudit)).all() == []
        buckets = db.scalars(select(ModelBudgetUsage)).all()
        assert len(buckets) == 2
        assert all(b.request_count == 1 and b.estimated_cost_micros > 0 for b in buckets)
