import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from unit.test_sdk_durable_invocations import NOW, records, request
from unit.test_sdk_durable_invocations import store as store

from ai_gateway import GatewayConfig, build_gateway
from ai_gateway.audit import AuditRecord
from ai_gateway.errors import ProviderError
from ai_gateway.providers import OpenAICompatAdapter
from support import REPO_ROOT
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    local_provider,
)
from tutor_api.models import ModelBudgetUsage, ModelCallAudit


def prepared(store):
    return store.prepare(
        dict(
            schema_version=3,
            invocation_id="a" * 32,
            actor_digest="b" * 64,
            budget_key="stu_" + "b" * 32,
            context_kind="sdk_request",
            resource_digest="c" * 64,
            context_generation=0,
            context_digest="d" * 64,
            fingerprint="e" * 64,
            quota_day=NOW.date().isoformat(),
            fence=1,
            state="prepared",
            attempts=[],
        )
    )


def dispatch(store, record, *, attempt="f" * 32, cap=100, estimate=3):
    return store.dispatch(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=record["fence"],
        attempt_id=attempt,
        estimated_cost_micros=estimate,
        request_cost_cap=cap,
        student_limit=1,
        platform_limit=1,
        recover_after=NOW + timedelta(seconds=10),
    )


def settle(store, record, *, retry=True, cost=3, status="degraded"):
    audit = AuditRecord(
        request_id="request",
        trace_id="trace",
        student_pseudonym=record["budget_key"],
        task_type="tutor_hint",
        provider="x",
        model_id="test",
        status=status,
        error_code="SCHEMA_INVALID" if status != "ok" else None,
        provider_calls=1,
        latency_ms=1,
        input_tokens=None,
        output_tokens=None,
        image_units=None,
        estimated_cost_micros=cost,
        schema_valid=False,
        review_required=False,
        created_at=NOW,
    )
    return store.settle_metadata(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=record["fence"],
        attempt_id=record["attempts"][-1]["attempt_id"],
        audit=audit,
        retryable_failure=retry,
    )


def test_next_attempt_commits_fence_and_cost_but_not_second_request(store):
    first = dispatch(store, prepared(store))
    first = settle(store, first)
    second = dispatch(store, first, attempt="1" * 32, estimate=4)
    assert second["fence"] == 2
    assert [a["state"] for a in second["attempts"]] == ["settled", "dispatch_unknown"]
    assert [a["fence"] for a in second["attempts"]] == [1, 2]
    with store.factory() as db:
        assert all(
            b.request_count == 1 and b.estimated_cost_micros == 7
            for b in db.scalars(select(ModelBudgetUsage))
        )
    result = settle(store, second, retry=False, cost=4, status="ok")
    assert result["state"] == "settled_metadata"
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 2


@pytest.mark.parametrize(
    "state", ["dispatch_unknown", "outcome_unknown", "settled_without_retry", "success"]
)
def test_no_next_attempt_from_unknown_or_nonretryable_result(store, state):
    record = dispatch(store, prepared(store))
    if state == "outcome_unknown":
        record = store.mark_unknown(
            record["invocation_id"], record["actor_digest"], expected_fence=1
        )
    elif state in ("settled_without_retry", "success"):
        record = settle(
            store, record, retry=False, status="ok" if state == "success" else "degraded"
        )
    with pytest.raises(ValueError):
        dispatch(store, record, attempt="1" * 32)


def test_next_attempt_cap_includes_prior_observed_overrun(store):
    record = settle(store, dispatch(store, prepared(store)), cost=9)
    with pytest.raises(ValueError):
        dispatch(store, record, attempt="1" * 32, cap=11, estimate=3)
    assert store.read(record["invocation_id"], record["actor_digest"]) == record
    with store.factory() as db:
        assert all(
            b.estimated_cost_micros == 9 and b.request_count == 1
            for b in db.scalars(select(ModelBudgetUsage))
        )


def test_only_one_concurrent_continuation_wins(store):
    record = settle(store, dispatch(store, prepared(store)))

    def attempt(index):
        try:
            dispatch(store, record, attempt=f"{index:032x}")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(1, 5))) == 1


def test_success_cannot_be_marked_retryable(store):
    record = dispatch(store, prepared(store))
    with pytest.raises(ValueError):
        settle(store, record, retry=True, status="ok")


def test_stale_first_fence_cannot_settle_latest_attempt(store):
    record = settle(store, dispatch(store, prepared(store)))
    second = dispatch(store, record, attempt="1" * 32)
    with pytest.raises(ValueError):
        settle(store, dict(second, fence=1))
    assert store.read(record["invocation_id"], record["actor_digest"]) == second


def sdk(store, first, second=None, *, retries=1, second_external=True):
    providers = {"x": external_provider()}
    adapters = {"x": first}
    if second is not None:
        providers["y"] = external_provider() if second_external else local_provider()
        adapters["y"] = second
    config = config_dict(providers, list(providers), defaults={"max_retries": retries})
    gateway = build_gateway(
        GatewayConfig.model_validate(config),
        env=FULL_ENV,
        environment="local",
        allow_external_calls=True,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides=adapters,
        now=lambda: NOW,
        sleep=lambda _: None,
    )
    gateway.bind_durable_invocations(store, secret="sdk-chain-test-secret")
    return gateway


def known_failure():
    return ProviderError("unavailable", "confirmed HTTP 503", outcome_known=True)


def test_sdk_retry_uses_separate_durable_attempts_and_audits(store):
    adapter = ScriptedProvider(known_failure(), hint_ok())
    gateway = sdk(store, adapter)
    response = gateway.invoke(request())
    assert response.status == "ok" and response.provider_calls == 2
    assert len(adapter.calls) == 2
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 2
        assert all(
            b.request_count == 1 and b.estimated_cost_micros > 0
            for b in db.scalars(select(ModelBudgetUsage))
        )
    assert gateway.invoke(request()).error_code == "INVOCATION_ALREADY_SETTLED"
    assert len(adapter.calls) == 2


@pytest.mark.parametrize("allowed", [False, True])
def test_sdk_completed_failure_fallback_respects_cross_provider_policy(store, allowed):
    first = ScriptedProvider(known_failure())
    second = ScriptedProvider(hint_ok())
    gateway = sdk(store, first, second, retries=0)
    value = request()
    value.privacy_policy.allow_cross_provider_fallback = allowed
    response = gateway.invoke(value)
    assert len(first.calls) == 1
    assert len(second.calls) == int(allowed)
    assert response.status == ("ok" if allowed else "degraded")
    assert response.provider_calls == 1 + int(allowed)


def test_unknown_network_failure_never_retries_or_falls_back(store):
    first = ScriptedProvider(ProviderError("unavailable", "connection reset"))
    second = ScriptedProvider(hint_ok())
    gateway = sdk(store, first, second)
    value = request()
    value.privacy_policy.allow_cross_provider_fallback = True
    response = gateway.invoke(value)
    assert response.status == "degraded"
    assert len(first.calls) == 1 and second.calls == []


def test_backoff_revocation_stops_next_send(store):
    first = ScriptedProvider(known_failure(), hint_ok())
    gateway = sdk(store, first)
    gateway._sleep = lambda _: setattr(gateway._config.providers["x"], "enabled", False)
    assert gateway.invoke(request()).status == "degraded"
    assert len(first.calls) == 1


def test_latest_attempt_deadline_and_audit_are_used(store):
    record = settle(store, dispatch(store, prepared(store)))
    store.now = lambda: NOW + timedelta(days=1, seconds=20)
    second = store.dispatch(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=1,
        attempt_id="1" * 32,
        estimated_cost_micros=3,
        request_cost_cap=100,
        student_limit=1,
        platform_limit=1,
        recover_after=NOW + timedelta(days=1, seconds=40),
    )
    assert second["quota_day"] == record["quota_day"]
    with pytest.raises(ValueError, match="still be running"):
        store.mark_unknown(
            second["invocation_id"], second["actor_digest"], expected_fence=2, require_due=True
        )
    store.now = lambda: NOW + timedelta(days=1, seconds=41)
    unknown = store.mark_unknown(
        second["invocation_id"], second["actor_digest"], expected_fence=2, require_due=True
    )
    assert unknown["attempts"][0]["state"] == "settled"
    assert unknown["attempts"][1]["state"] == "outcome_unknown"


def test_prior_missing_or_successful_audit_cannot_continue(store):
    record = settle(store, dispatch(store, prepared(store)))
    with store.factory.begin() as db:
        audit = db.get(ModelCallAudit, record["attempts"][0]["attempt_id"])
        audit.status = "ok"
    with pytest.raises(ValueError):
        dispatch(store, record, attempt="1" * 32)
    with store.factory.begin() as db:
        db.delete(db.get(ModelCallAudit, record["attempts"][0]["attempt_id"]))
    with pytest.raises(ValueError):
        dispatch(store, record, attempt="1" * 32)


def test_schema_rejection_can_use_configured_fallback(store):
    first = ScriptedProvider({"invalid": "output"})
    second = ScriptedProvider(hint_ok())
    gateway = sdk(store, first, second)
    value = request()
    value.privacy_policy.allow_cross_provider_fallback = True
    response = gateway.invoke(value)
    assert response.status == "ok" and response.provider_calls == 2
    assert len(first.calls) == len(second.calls) == 1


def test_external_classification_cannot_change_after_reservation(store, monkeypatch):
    first = ScriptedProvider(hint_ok())
    gateway = sdk(store, first)
    original = store.dispatch

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        gateway._config.providers["x"].external = False
        gateway._config.providers["x"].kind = "mock"
        return result

    monkeypatch.setattr(store, "dispatch", changed)
    assert gateway.invoke(request()).error_code == "INVOCATION_UNCERTAIN"
    assert first.calls == []


def test_real_exit_on_second_attempt_keeps_both_reservations_and_no_restart_send(store):
    database_url = str(store.factory.kw["bind"].url)
    script = f"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.services.invocation_store import InvocationStore
from unit.test_sdk_attempt_chain import sdk, known_failure, request, NOW
store=InvocationStore(sessionmaker(create_engine({database_url!r})),
    InvocationTransitions(Path('contracts/model_invocation.schema.json')),now=lambda:NOW)
class ExitSecond:
    calls=0
    def invoke(self,**kwargs):
        self.calls+=1
        if self.calls==1: raise known_failure()
        os._exit(23)
sdk(store,ExitSecond()).invoke(request())
raise AssertionError('second dispatch was not reached')
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
    result = subprocess.run(
        [sys.executable, "-"],
        input=script.encode(),
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    record = records(store)[0]["metadata_json"]
    assert [a["state"] for a in record["attempts"]] == ["settled", "dispatch_unknown"]
    assert record["fence"] == 2
    adapter = ScriptedProvider(hint_ok())
    assert sdk(store, adapter).invoke(request()).error_code == "INVOCATION_UNCERTAIN"
    assert adapter.calls == []
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 1
        reserved = sum(a["estimated_cost_micros"] for a in record["attempts"])
        assert all(
            b.request_count == 1 and b.estimated_cost_micros == reserved
            for b in db.scalars(select(ModelBudgetUsage))
        )


def test_cumulative_cap_can_choose_a_cheaper_configured_fallback(store):
    first = ScriptedProvider(known_failure(), hint_ok())
    second = ScriptedProvider(hint_ok())
    gateway = sdk(store, first, second, second_external=False)
    value = request()
    estimate = gateway.prepare_single_attempt(value).estimated_cost_micros
    gateway._config.budgets.per_request_max_cost_micros = estimate
    response = gateway.invoke(value)
    assert response.status == "ok" and response.provider == "y"
    assert len(first.calls) == len(second.calls) == 1
    with store.factory() as db:
        assert all(
            b.request_count == 1 and b.estimated_cost_micros == estimate
            for b in db.scalars(select(ModelBudgetUsage))
        )


def test_http_response_retry_observes_committed_second_attempt(store):
    calls = []

    def handler(_request):
        calls.append(True)
        value = records(store)[0]["metadata_json"]
        assert len(value["attempts"]) == len(calls)
        assert value["attempts"][-1]["state"] == "dispatch_unknown"
        with store.factory() as db:
            assert len(db.scalars(select(ModelCallAudit)).all()) == len(calls) - 1
            assert all(b.request_count == 1 for b in db.scalars(select(ModelBudgetUsage)))
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        import json

        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(hint_ok())}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    adapter = OpenAICompatAdapter(
        base_url="https://models.invalid/v1",
        api_key="test-not-real",
        transport=httpx.MockTransport(handler),
    )
    response = sdk(store, adapter).invoke(request())
    assert response.status == "ok" and response.provider_calls == 2 and len(calls) == 2


def test_failed_second_settlement_keeps_first_audit_and_never_delivers_output(store, monkeypatch):
    adapter = ScriptedProvider(known_failure(), hint_ok())
    gateway = sdk(store, adapter)
    original = store.settle_metadata

    def fail_second(*args, **kwargs):
        if len(records(store)[0]["metadata_json"]["attempts"]) == 2:
            raise RuntimeError("private storage failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "settle_metadata", fail_second)
    response = gateway.invoke(request())
    assert response.error_code == "INVOCATION_UNCERTAIN" and response.validated_output is None
    assert response.provider_calls == 2
    assert [a["state"] for a in records(store)[0]["metadata_json"]["attempts"]] == [
        "settled",
        "dispatch_unknown",
    ]
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 1
