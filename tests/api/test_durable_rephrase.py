from pathlib import Path

import pytest
from sqlalchemy import select

from ai_gateway import GatewayConfig, build_gateway
from ai_gateway.audit import AuditRecord
from ai_gateway.invocation_state import InvocationTransitions
from support.flows import begin
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    hint_ok,
    local_provider,
    timeout,
)
from tutor_api.gateway_io import DbBudgetStore, pseudonym
from tutor_api.models import ModelBudgetUsage, ModelCallAudit, QuestionVersion, StudySession, User
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.invocation_maintenance import retire_terminal_session
from tutor_api.services.invocation_store import InvocationStore, intents, metadata


def install(onboarded, app, db, clock, *, fails=False, available=True):
    session, _ = begin(onboarded, "math-mono-quadratic")
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == session["question_id"],
            QuestionVersion.version == session["question_version"],
        )
    )
    version.teaching_json = dict(version.teaching_json, concept_rephrase=None, reference_links=[])
    db.commit()
    factory = app.state.session_factory
    metadata.create_all(factory.kw["bind"])
    app.state.invocation_store = InvocationStore(
        factory,
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
        now=clock.now,
    )
    app.state.receipt_store = SqlReceiptStore()
    adapter = ScriptedProvider(timeout() if fails else hint_ok())
    app.state.gateway = build_gateway(
        GatewayConfig.model_validate(config_dict({"m": local_provider(enabled=available)}, ["m"])),
        env={},
        environment="local",
        allow_external_calls=False,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"m": adapter},
        now=clock.now,
    )
    return session, adapter


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("available", [True, False])
def test_http_durable_rephrase_sends_once_and_replays(onboarded, app, db, clock, fails, available):
    session, adapter = install(onboarded, app, db, clock, fails=fails, available=available)
    path = f"/tutor/sessions/{session['id']}/next"
    first = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="durable-real-http-key"
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["events"][0]["type"] == (
        "fallback" if fails or not available else "hint"
    )
    replay = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="durable-real-http-key"
    )
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert replay.headers["Idempotency-Replayed"] == "true"

    assert len(adapter.calls) == int(available)
    db.expire_all()
    assert len(list(db.scalars(select(ModelCallAudit)))) == int(available)
    assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
    assert db.execute(select(intents.c.state)).scalar_one() == (
        "applied" if available else "cancelled_unsent"
    )


def test_http_recovers_settled_result_loss_without_another_send(
    onboarded, app, db, clock, monkeypatch
):
    from tutor_api.services import durable_rephrase

    session, adapter = install(onboarded, app, db, clock)

    def lose_result(*args, **kwargs):
        raise RuntimeError("crash before event application")

    monkeypatch.setattr(durable_rephrase, "finalize_rephrase", lose_result)
    path = f"/tutor/sessions/{session['id']}/next"
    with pytest.raises(RuntimeError, match="crash before event"):
        onboarded.request(
            "POST", path, json={"action": "mark_confused"}, key="recover-settled-result-key"
        )
    assert len(adapter.calls) == 1
    assert db.execute(select(intents.c.state)).scalar_one() == "settled_metadata"
    db.rollback()
    response = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="recover-settled-result-key"
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["events"][0]["type"] == "fallback"
    assert len(adapter.calls) == 1
    replay = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="recover-settled-result-key"
    )
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == response.json()
    assert len(list(db.scalars(select(ModelCallAudit)))) == 1
    assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))


@pytest.mark.parametrize("scope", ["platform", "student"])
@pytest.mark.parametrize("kind", ["requests", "cost"])
def test_http_budget_denial_is_safe_fallback_without_send(onboarded, app, db, clock, scope, kind):
    session, adapter = install(onboarded, app, db, clock)
    limits = app.state.gateway._config.budgets
    limit = limits.platform_daily_requests if scope == "platform" else limits.student_daily_requests
    if kind == "cost":
        setattr(limits, f"{scope}_daily_max_cost_micros", 0)
    requests, cost = (limit, 0) if kind == "requests" else (0, 1)
    key = (
        "platform"
        if scope == "platform"
        else pseudonym(app.state.pseudonym_secret, onboarded.user_id)
    )
    DbBudgetStore(app.state.session_factory, clock.now).add(
        scope, key, clock.now().date(), requests=requests, cost_micros=cost
    )
    response = onboarded.request(
        "POST",
        f"/tutor/sessions/{session['id']}/next",
        json={"action": "mark_confused"},
        key="durable-budget-denial-key",
    )
    assert response.status_code == 200, response.text
    event = response.json()["data"]["events"][0]
    assert event["type"] == "fallback"
    assert event["payload"]["reason_code"] == "BUDGET_EXCEEDED"
    assert adapter.calls == []
    assert list(db.scalars(select(ModelCallAudit))) == []
    rows = list(db.scalars(select(ModelBudgetUsage)))
    assert len(rows) == 1 and rows[0].request_count == requests
    assert rows[0].estimated_cost_micros == cost
    assert db.execute(select(intents.c.state)).scalar_one() == "cancelled_unsent"


def test_http_dispatch_loss_waits_then_closes_without_resend(
    onboarded, app, db, clock, monkeypatch
):
    session, adapter = install(onboarded, app, db, clock)
    original = app.state.gateway.invoke_single_attempt
    lost = []

    def lose_after_send(plan):
        lost.append(original(plan))
        raise RuntimeError("process interrupted after send")

    monkeypatch.setattr(app.state.gateway, "invoke_single_attempt", lose_after_send)
    path = f"/tutor/sessions/{session['id']}/next"
    args = dict(json={"action": "mark_confused"}, key="unknown-send-recovery-key")
    with pytest.raises(RuntimeError, match="interrupted after send"):
        onboarded.request("POST", path, **args)
    waiting = onboarded.request("POST", path, **args)
    assert waiting.status_code == 409
    assert len(adapter.calls) == 1
    clock.advance(app.state.gateway._config.defaults.timeout_ms / 1000 + 1)
    recovered = onboarded.request("POST", path, **args)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["events"][0]["type"] == "fallback"
    assert len(adapter.calls) == 1
    assert list(db.scalars(select(ModelCallAudit))) == []
    assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
    assert db.execute(select(intents.c.state)).scalar_one() == "closed_unknown"
    db.rollback()
    replay = onboarded.request("POST", path, **args)
    assert replay.json() == recovered.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    persisted = db.execute(select(intents.c.metadata_json)).scalar_one()
    db.rollback()
    result = lost[0]
    audit = AuditRecord(
        request_id=adapter.calls[0]["request"].request_id,
        trace_id=result.trace_id,
        student_pseudonym=persisted["budget_key"],
        task_type="tutor_explain",
        provider=result.provider,
        model_id=result.model_id,
        status=result.status,
        error_code=result.error_code,
        provider_calls=1,
        latency_ms=result.latency_ms,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        image_units=result.usage.image_units,
        estimated_cost_micros=result.usage.estimated_cost_micros,
        schema_valid=True,
        review_required=result.review_required,
        created_at=clock.now(),
    )
    for _ in range(2):
        settled = app.state.invocation_store.settle_metadata(
            persisted["invocation_id"],
            persisted["actor_digest"],
            expected_fence=persisted["fence"],
            attempt_id=persisted["attempts"][0]["attempt_id"],
            audit=audit,
        )
        assert settled["state"] == "closed_unknown"
    assert len(list(db.scalars(select(ModelCallAudit)))) == 1
    assert db.execute(select(intents.c.active_session_digest)).scalar_one() is None


def test_context_change_retires_old_intent_and_allows_new_action(onboarded, app, db, clock):
    session, adapter = install(onboarded, app, db, clock)
    path = f"/tutor/sessions/{session['id']}/next"
    original = adapter.invoke
    changed = False

    def invoke(**kwargs):
        nonlocal changed
        if not changed:
            changed = True
            response = onboarded.request(
                "POST", path, json={"action": "request_hint"}, key="concurrent-reviewed-hint"
            )
            assert response.status_code == 200
        return original(**kwargs)

    adapter.invoke = invoke
    stale = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="stale-context-model-key"
    )
    assert stale.status_code == 409, stale.text
    assert db.execute(select(intents.c.state)).scalar_one() == "stale"
    assert db.execute(select(intents.c.active_session_digest)).scalar_one() is None
    assert len(adapter.calls) == 1
    db.rollback()
    fresh = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="fresh-context-model-key"
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["data"]["events"][0]["meta"]["source"] == "model"
    assert len(adapter.calls) == 2
    repeated = onboarded.request(
        "POST", path, json={"action": "mark_confused"}, key="stale-context-model-key"
    )
    assert repeated.status_code == 409
    assert len(adapter.calls) == 2


@pytest.mark.parametrize("terminal", ["disabled", "done"])
def test_targeted_maintenance_retires_only_terminal_intent(
    onboarded, app, db, clock, monkeypatch, terminal, new_student
):
    session, adapter = install(onboarded, app, db, clock)
    original = app.state.gateway.invoke_single_attempt

    def crash(plan):
        original(plan)
        raise RuntimeError("maintenance fixture interruption")

    monkeypatch.setattr(app.state.gateway, "invoke_single_attempt", crash)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        onboarded.request(
            "POST",
            f"/tutor/sessions/{session['id']}/next",
            json={"action": "mark_confused"},
            key="maintenance-targeted-key",
        )
    store = app.state.invocation_store
    options = dict(secret=app.state.pseudonym_secret)
    other = new_student()
    assert retire_terminal_session(store, other.user_id, session["id"], apply=True, **options) == 0
    assert (
        retire_terminal_session(store, onboarded.user_id, session["id"], apply=True, **options) == 0
    )
    if terminal == "disabled":
        db.get(User, onboarded.user_id).status = "disabled"
    else:
        db.get(StudySession, session["id"]).state = "DONE"
    db.commit()
    assert retire_terminal_session(store, onboarded.user_id, session["id"], **options) == 1
    assert db.execute(select(intents.c.state)).scalar_one() == "dispatch_unknown"
    db.rollback()
    assert (
        retire_terminal_session(store, onboarded.user_id, session["id"], apply=True, **options) == 1
    )
    assert (
        retire_terminal_session(store, onboarded.user_id, session["id"], apply=True, **options) == 0
    )
    assert db.execute(select(intents.c.state)).scalar_one() == "stale"
    assert db.execute(select(intents.c.active_session_digest)).scalar_one() is None
    assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
    assert len(adapter.calls) == 1
