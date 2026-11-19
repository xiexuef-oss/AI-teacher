import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from unit.test_sdk_attempt_chain import known_failure, sdk
from unit.test_sdk_durable_invocations import NOW, records, request
from unit.test_sdk_durable_invocations import store as store

from support import REPO_ROOT
from support.gateway_fakes import ScriptedProvider, hint_ok
from tutor_api.models import ModelCallAudit
from tutor_api.services.invocation_store import intents


def checkpoint(store):
    adapter = ScriptedProvider(known_failure())
    gateway = sdk(store, adapter)

    def exit_before_retry(_):
        raise SystemExit(23)

    gateway._sleep = exit_before_retry
    with pytest.raises(SystemExit):
        gateway.invoke(request())
    assert len(adapter.calls) == 1
    assert records(store)[0]["state"] == "settled_metadata"
    return records(store)[0]["metadata_json"]


def test_known_failed_request_resumes_after_restart_without_resending_first_attempt(store):
    first = checkpoint(store)
    adapter = ScriptedProvider(hint_ok())
    response = sdk(store, adapter).invoke(request())
    assert response.status == "ok" and response.provider_calls == 1
    assert len(adapter.calls) == 1
    result = records(store)[0]["metadata_json"]
    assert result["attempts"][0] == first["attempts"][0]
    assert len(result["attempts"]) == 2 and result["fence"] == 2
    with store.factory() as db:
        assert len(db.scalars(select(ModelCallAudit)).all()) == 2


def test_two_restart_workers_only_dispatch_one_next_attempt(store):
    checkpoint(store)
    adapter = ScriptedProvider(hint_ok())
    gateways = [sdk(store, adapter), sdk(store, adapter)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda g: g.invoke(request()), gateways))
    assert sum(r.status == "ok" for r in responses) == 1
    assert len(adapter.calls) == 1


def test_changed_route_does_not_guess_a_restart_cursor(store):
    before = checkpoint(store)
    first, second = ScriptedProvider(hint_ok()), ScriptedProvider(hint_ok())
    response = sdk(store, first, second).invoke(request())
    assert response.error_code == "INVOCATION_CONFLICT"
    assert first.calls == second.calls == []
    assert records(store)[0]["metadata_json"] == before


def test_completed_success_still_does_not_recreate_model_text(store):
    checkpoint(store)
    assert sdk(store, ScriptedProvider(hint_ok())).invoke(request()).status == "ok"
    adapter = ScriptedProvider(hint_ok())
    response = sdk(store, adapter).invoke(request())
    assert response.error_code == "INVOCATION_ALREADY_SETTLED"
    assert response.validated_output is None and adapter.calls == []


def test_unknown_attempt_never_resumes_even_with_a_persisted_cursor(store):
    adapter = ScriptedProvider(SystemExit(23))
    with pytest.raises(SystemExit):
        sdk(store, adapter).invoke(request())
    first = records(store)[0]["metadata_json"]
    assert first["attempts"][0]["sdk_context"]["continuation"] == "none"
    restarted = ScriptedProvider(hint_ok())
    response = sdk(store, restarted).invoke(request())
    assert response.error_code == "INVOCATION_UNCERTAIN"
    assert restarted.calls == []


def test_fallback_cursor_skips_the_completed_provider_after_restart(store, monkeypatch):
    first, second = ScriptedProvider({"invalid": True}), ScriptedProvider(hint_ok())
    gateway = sdk(store, first, second, retries=0)
    value = request()
    value.privacy_policy.allow_cross_provider_fallback = True
    original = store.dispatch

    def exit_before_fallback(*args, **kwargs):
        if records(store) and records(store)[0]["metadata_json"]["attempts"]:
            raise SystemExit(23)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "dispatch", exit_before_fallback)
    with pytest.raises(SystemExit):
        gateway.invoke(value)
    monkeypatch.setattr(store, "dispatch", original)
    assert (
        records(store)[0]["metadata_json"]["attempts"][0]["sdk_context"]["continuation"]
        == "fallback"
    )
    restarted_first, restarted_second = ScriptedProvider(hint_ok()), ScriptedProvider(hint_ok())
    response = sdk(store, restarted_first, restarted_second, retries=0).invoke(value)
    assert response.status == "ok" and response.provider == "y"
    assert restarted_first.calls == [] and len(restarted_second.calls) == 1


def test_store_rejects_a_rewound_cursor_without_changing_the_record(store):
    before = checkpoint(store)
    cursor = dict(before["attempts"][0]["sdk_context"], continuation="none")
    with pytest.raises(ValueError):
        store.dispatch(
            before["invocation_id"],
            before["actor_digest"],
            expected_fence=1,
            attempt_id="a" * 32,
            estimated_cost_micros=1,
            request_cost_cap=50000,
            student_limit=200,
            platform_limit=20000,
            recover_after=NOW + timedelta(seconds=10),
            sdk_context=cursor,
        )
    assert records(store)[0]["metadata_json"] == before


def test_legacy_failed_metadata_without_a_cursor_is_not_fabricated_into_resume(store):
    before = checkpoint(store)
    before["attempts"][0].pop("sdk_context")
    with store.factory.begin() as db:
        db.execute(
            update(intents)
            .where(intents.c.id == before["invocation_id"])
            .values(metadata_json=before)
        )
    adapter = ScriptedProvider(hint_ok())
    assert sdk(store, adapter).invoke(request()).error_code == "INVOCATION_ALREADY_SETTLED"
    assert adapter.calls == []


def test_real_process_exit_after_confirmed_failure_can_resume(store):
    database_url = str(store.factory.kw["bind"].url)
    script = f"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.services.invocation_store import InvocationStore
from unit.test_sdk_attempt_chain import sdk,known_failure,request,NOW
from support.gateway_fakes import ScriptedProvider
store=InvocationStore(sessionmaker(create_engine({database_url!r})),
    InvocationTransitions(Path('contracts/model_invocation.schema.json')),now=lambda:NOW)
gateway=sdk(store,ScriptedProvider(known_failure()))
gateway._sleep=lambda _:os._exit(23)
gateway.invoke(request())
raise AssertionError('failure checkpoint was not reached')
"""
    env = {
        k: os.environ[k] for k in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ
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
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    first = records(store)[0]["metadata_json"]
    assert first["state"] == "settled_metadata" and len(first["attempts"]) == 1
    adapter = ScriptedProvider(hint_ok())
    response = sdk(store, adapter).invoke(request(trace_id="restart-transport"))
    assert response.status == "ok" and response.trace_id == "restart-transport"
    assert len(adapter.calls) == 1 and len(records(store)[0]["metadata_json"]["attempts"]) == 2


def test_restart_restores_external_history_before_applying_privacy_policy(store):
    first, second = ScriptedProvider({"invalid": True}), ScriptedProvider(hint_ok())
    value = request()
    assert sdk(store, first, second, retries=0).invoke(value).status == "degraded"
    assert len(first.calls) == 1 and second.calls == []
    restarted_first, restarted_second = ScriptedProvider(hint_ok()), ScriptedProvider(hint_ok())
    response = sdk(store, restarted_first, restarted_second, retries=0).invoke(value)
    assert response.status == "degraded"
    assert restarted_first.calls == restarted_second.calls == []


def test_provider_digest_mismatch_cannot_authorize_a_restart(store):
    value = checkpoint(store)
    value["attempts"][0]["sdk_context"]["provider_digest"] = "f" * 64
    with store.factory.begin() as db:
        db.execute(
            update(intents)
            .where(intents.c.id == value["invocation_id"])
            .values(metadata_json=value)
        )
    adapter = ScriptedProvider(hint_ok())
    response = sdk(store, adapter).invoke(request())
    assert response.error_code == "INVOCATION_CONFLICT"
    assert adapter.calls == []
    assert records(store)[0]["metadata_json"] == value


def test_changed_resolved_model_cannot_reuse_the_restart_cursor(store):
    before = checkpoint(store)
    adapter = ScriptedProvider(hint_ok())
    gateway = sdk(store, adapter)
    gateway._env = {**gateway._env, "X_MODEL": "another-test-model"}
    assert gateway.invoke(request()).error_code == "INVOCATION_CONFLICT"
    assert adapter.calls == []
    assert records(store)[0]["metadata_json"] == before
