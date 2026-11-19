import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_managed_tutor_transactions import dependencies, mysql_engine, real_coordinator, tutor_case  # noqa: F401

from ai_gateway import GatewayConfig, build_gateway
from ai_gateway.invocation_state import InvocationTransitions
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    hint_ok,
    local_provider,
    timeout,
)
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_store import InvocationStore, intents


def test_managed_startup_optin_wires_invocation_store(dependencies):  # noqa: F811
    from starlette.testclient import TestClient
    from test_managed_runtime import build

    from support.api import LOOPBACK

    selected = list(dependencies)
    selected[3] = selected[3].model_copy(update={"durable_model_invocations_enabled": True})
    app = build(tuple(selected))
    with TestClient(app, client=LOOPBACK):
        assert isinstance(app.state.invocation_store, InvocationStore)


def install(case, *, fails=False):
    payload = json.loads(json.dumps(case["payload"]))
    payload["question"]["teaching"]["concept_rephrase"] = None
    created = case["author"].data("POST", "/admin/question-imports", expect=201, json=payload)
    for decision, revision in [("approve", 1), ("publish", 2)]:
        case["reviewer"].data(
            "POST",
            f"/admin/questions/{created['id']}/review",
            json=dict(expected_version=1, expected_review_revision=revision, decision=decision),
        )
    session = case["student"].data(
        "POST", "/sessions", expect=201, json=dict(question_id=created["id"], origin="practice")
    )
    adapter = ScriptedProvider(timeout() if fails else hint_ok())
    original = adapter.invoke

    def guarded_send(**kwargs):
        with case["factory"]() as db:
            assert db.execute(select(intents.c.state)).scalar_one() == "dispatch_unknown"
            assert db.scalar(select(func.count()).select_from(ModelCallAudit)) == 0
            assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
        return original(**kwargs)

    adapter.invoke = guarded_send
    app = case["app"]
    app.state.invocation_store = InvocationStore(
        case["factory"], InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    )
    app.state.gateway = build_gateway(
        GatewayConfig.model_validate(
            config_dict({"m": local_provider(environments=["staging"])}, ["m"])
        ),
        env={},
        environment="staging",
        allow_external_calls=False,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"m": adapter},
    )
    path = f"/tutor/sessions/{session['id']}/next"
    return session, adapter, path


@pytest.mark.parametrize("fails", [False, True])
def test_managed_mysql_http_single_send_and_receipt_replay(tutor_case, fails):  # noqa: F811
    case = tutor_case
    session, adapter, path = install(case, fails=fails)
    first = case["student"].request(
        "POST", path, json={"action": "mark_confused"}, key="mysql-http-model-key"
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["events"][0]["type"] == ("fallback" if fails else "hint")
    replay = case["student"].request(
        "POST", path, json={"action": "mark_confused"}, key="mysql-http-model-key"
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(adapter.calls) == 1
    with case["factory"]() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == "applied"
        assert db.scalar(select(func.count()).select_from(ModelCallAudit)) == 1
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2 and all(row.request_count == 1 for row in rows)


@pytest.mark.parametrize("use_redis", [True, False])
def test_mysql_concurrent_expired_dispatch_recovery(
    tutor_case, real_coordinator, monkeypatch, use_redis  # noqa: F811
):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    from threading import Barrier

    from support.clock import FakeClock
    from tutor_api.idempotency import key_digest
    from tutor_api.models import IdempotencyReceipt, TutorEventRow

    case = tutor_case
    session, adapter, path = install(case)
    clock = FakeClock(datetime.now(UTC))
    app = case["app"]
    app.state.clock = clock.now
    app.state.invocation_store.now = clock.now
    app.state.receipt_coordinator = real_coordinator if use_redis else None
    original = app.state.gateway.invoke_single_attempt

    def lost_after_send(plan):
        original(plan)
        raise RuntimeError("simulated worker interruption")

    monkeypatch.setattr(app.state.gateway, "invoke_single_attempt", lost_after_send)
    args = dict(json={"action": "mark_confused"}, key="mysql-expired-dispatch-key")
    with pytest.raises(RuntimeError, match="worker interruption"):
        case["student"].request("POST", path, **args)
    waiting = case["student"].request("POST", path, **args)
    assert waiting.status_code == 409
    clock.advance(app.state.gateway._config.defaults.timeout_ms / 1000 + 1)
    barrier = Barrier(8)

    def recover(_):
        barrier.wait(timeout=10)
        return case["student"].request("POST", path, **args)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(recover, range(8)))
    assert all(response.status_code in (200, 409) for response in responses)
    assert any(response.status_code == 200 for response in responses)
    replay = case["student"].request("POST", path, **args)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(adapter.calls) == 1
    with case["factory"]() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == "closed_unknown"
        assert db.scalar(select(func.count()).select_from(ModelCallAudit)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(TutorEventRow)
                .where(TutorEventRow.session_id == session["id"])
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyReceipt)
                .where(
                    IdempotencyReceipt.key_digest
                    == key_digest(case["tokens"]["student"], args["key"])
                )
            )
            == 1
        )
        assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
