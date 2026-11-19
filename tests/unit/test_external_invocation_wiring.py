"""Business external sends require the durable seam, even after config changes."""

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from ai_gateway import GatewayConfig, build_gateway
from support.flows import begin
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    timeout,
)
from tutor_api.main import create_app
from tutor_api.models import ModelBudgetUsage, ModelCallAudit, QuestionVersion
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.invocation_store import intents


def external_gateway(clock, *, enabled=True, allow=True, fallback=False):
    external = ScriptedProvider(hint_ok())
    local = ScriptedProvider(hint_ok())
    providers = {"x": external_provider(enabled=enabled)}
    if fallback:
        providers["m"] = local_provider()
    gateway = build_gateway(
        GatewayConfig.model_validate(config_dict(providers, list(providers))),
        env=FULL_ENV,
        environment="local",
        allow_external_calls=allow,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"x": external, "m": local},
        now=clock.now,
    )
    return gateway, external, local


@pytest.mark.parametrize("enabled", [True, False])
def test_injected_external_intent_requires_durable_configuration(settings, clock, enabled):
    gateway, _, _ = external_gateway(clock, enabled=enabled)
    with pytest.raises(ValueError, match="外部模型.*持久"):
        create_app(settings, gateway=gateway)


def test_settings_external_intent_requires_durable_configuration(settings):
    with pytest.raises(ValueError, match="外部模型.*持久"):
        create_app(settings.model_copy(update={"allow_external_model_calls": True}))


@pytest.mark.parametrize("durable", [True, False])
def test_application_never_sends_external_through_legacy_even_after_flag_change(
    settings, clock, durable
):
    gateway, external, local = external_gateway(clock, allow=durable, fallback=True)
    configured = settings.model_copy(
        update={
            "durable_model_invocations_enabled": durable,
            "pseudonym_secret": "stable-wiring-test-secret",
        }
    )
    app = create_app(
        configured,
        gateway=gateway,
        clock=clock.now,
        receipt_store=SqlReceiptStore() if durable else None,
    )
    with TestClient(app):
        gateway._allow_external_calls = True
        result = gateway.invoke(make_request())
        assert result.status == "ok"
        assert result.provider == "m"
        assert external.calls == []
        assert len(local.calls) == 1
        if durable:
            result = gateway.invoke_single_attempt(gateway.prepare_single_attempt(make_request()))
            assert result.provider == "x"
            assert len(external.calls) == 1


@pytest.mark.parametrize("gap", ["budget_commit", "retry_backoff"])
def test_legacy_rechecks_durable_policy_after_io(clock, gap, monkeypatch):
    gateway, external, _ = external_gateway(clock)
    if gap == "budget_commit":
        original = gateway._budget_store.record_cost

        def commit(*args, **kwargs):
            original(*args, **kwargs)
            gateway.require_durable_external_calls()

        monkeypatch.setattr(gateway._budget_store, "record_cost", commit)
    else:
        external.script = [timeout(), hint_ok()]
        monkeypatch.setattr(gateway, "_sleep", lambda _: gateway.require_durable_external_calls())
    result = gateway.invoke(make_request())
    assert result.status == "degraded"
    assert len(external.calls) == int(gap == "retry_backoff")


def test_business_rephrase_uses_startup_durable_store(custom_student, settings, clock):
    gateway, external, _ = external_gateway(clock)
    configured = settings.model_copy(
        update={
            "allow_external_model_calls": True,
            "durable_model_invocations_enabled": True,
            "pseudonym_secret": "stable-business-test-secret",
        }
    )
    app, learner = custom_student(
        settings=configured, gateway=gateway, receipt_store=SqlReceiptStore()
    )
    session, _ = begin(learner, "math-mono-quadratic")
    with app.state.session_factory() as db:
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == session["question_id"],
                QuestionVersion.version == session["question_version"],
            )
        )
        version.teaching_json = dict(
            version.teaching_json, concept_rephrase=None, reference_links=[]
        )
        db.commit()
    path = f"/tutor/sessions/{session['id']}/next"
    first = learner.post(path, json={"action": "mark_confused"}, key="external-durable-key")
    replay = learner.post(path, json={"action": "mark_confused"}, key="external-durable-key")
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(external.calls) == 1
    with app.state.session_factory() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == "applied"
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        usage = list(db.scalars(select(ModelBudgetUsage)))
        assert len(usage) == 2
        assert all(row.request_count == 1 and row.estimated_cost_micros > 0 for row in usage)


@pytest.mark.parametrize("enabled", [True, False])
def test_dev_factory_explicitly_wires_sql_receipts_only_when_enabled(monkeypatch, enabled):
    import run_dev_api

    import tutor_api.main as main

    seen = {}
    monkeypatch.setenv("TUTOR_DURABLE_MODEL_INVOCATIONS_ENABLED", str(enabled).lower())
    monkeypatch.setattr(
        main,
        "create_app",
        lambda settings, **kwargs: seen.update(
            enabled=settings.durable_model_invocations_enabled, **kwargs
        ),
    )
    run_dev_api.create_dev_app()
    assert seen["enabled"] is enabled
    assert isinstance(seen["receipt_store"], SqlReceiptStore) is enabled


@pytest.mark.parametrize("durable", [True, False])
def test_managed_runtime_blocks_external_in_every_seam_after_flag_change(clock, durable):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tutor_api.services.invocation_runtime import initialize
    from tutor_api.services.invocation_store import metadata
    from tutor_api.settings import Settings

    gateway, adapter, _ = external_gateway(clock)
    plan = gateway.prepare_single_attempt(make_request())
    gateway._allow_external_calls = False
    engine = create_engine("sqlite://")
    try:
        metadata.create_all(engine)
        initialize(
            engine,
            sessionmaker(engine),
            Settings(
                durable_model_invocations_enabled=durable, pseudonym_secret="stable-test-secret"
            ),
            SqlReceiptStore() if durable else None,
            clock.now,
            managed=True,
            gateway=gateway,
        )
        gateway._allow_external_calls = True
        gateway.require_durable_external_calls()
        assert gateway.invoke(make_request()).status == "degraded"
        assert gateway.invoke_single_attempt(plan).error_code == "MODEL_UNAVAILABLE"
        with pytest.raises(ValueError, match="No usable candidate"):
            gateway.prepare_single_attempt(make_request())
        assert adapter.calls == []
    finally:
        engine.dispose()
