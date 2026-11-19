import pytest
from sqlalchemy import inspect
from starlette.testclient import TestClient

from ai_gateway import GatewayConfig, build_gateway
from support.cost_cases import audit, record
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    hint_ok,
    local_provider,
    make_request,
)
from tutor_api.main import create_app
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.invocation_tables import dispatch_gate


def gateway(clock):
    adapter = ScriptedProvider(hint_ok())
    result = build_gateway(
        GatewayConfig.model_validate(config_dict({"m": local_provider()}, ["m"])),
        env={},
        environment="local",
        allow_external_calls=False,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"m": adapter},
        now=clock.now,
    )
    return result, adapter


@pytest.mark.parametrize("phase", ["running", "restart_disabled", "storage_missing"])
def test_application_guard_cannot_be_bypassed_by_legacy_invocation_or_flag_change(
    settings, clock, phase
):
    configured = settings.model_copy(
        update=dict(
            durable_model_invocations_enabled=True,
            pseudonym_secret="stable-self-authored-secret",
            model_cost_overrun_policy="pause_platform",
        )
    )
    g, adapter = gateway(clock)
    app = create_app(configured, receipt_store=SqlReceiptStore(), gateway=g, clock=clock.now)
    with TestClient(app):
        store = app.state.invocation_store
        value = record()
        store.prepare(value)
        store.dispatch(
            "a" * 32,
            "b" * 64,
            expected_fence=1,
            attempt_id="c" * 32,
            estimated_cost_micros=3,
            request_cost_cap=10,
            student_limit=10,
            platform_limit=10,
        )
        store.settle_metadata(
            "a" * 32, "b" * 64, expected_fence=1, attempt_id="c" * 32, audit=audit()
        )
        if phase == "storage_missing":
            dispatch_gate.drop(app.state.session_factory.kw["bind"])
        if phase != "restart_disabled":
            result = g.invoke(make_request())
            assert result.error_code == (
                "BUDGET_UNAVAILABLE" if phase == "storage_missing" else "BUDGET_EXCEEDED"
            )
            assert adapter.calls == []
    if phase == "restart_disabled":
        g, adapter = gateway(clock)
        second = create_app(
            configured.model_copy(
                update=dict(
                    durable_model_invocations_enabled=False,
                    model_cost_overrun_policy="record_only",
                )
            ),
            gateway=g,
            clock=clock.now,
        )
        with TestClient(second):
            assert second.state.invocation_store is None
            assert g.invoke(make_request()).error_code == "BUDGET_EXCEEDED"
            assert adapter.calls == []


def test_partial_cost_schema_is_not_silently_ignored_when_feature_is_disabled(settings, clock):
    from tutor_api.db import make_engine

    engine = make_engine(settings.database_url, settings=settings)
    dispatch_gate.create(engine)
    engine.dispose()
    app = create_app(settings, clock=clock.now)
    with pytest.raises(ValueError, match="成本保护"), TestClient(app):
        pass
    assert (
        "model_budget_incidents"
        not in inspect(app.state.session_factory.kw["bind"]).get_table_names()
    )


def test_daily_cost_configuration_requires_durable_startup(settings, clock):
    g, _ = gateway(clock)
    g._config.budgets.student_daily_max_cost_micros = 0
    app = create_app(settings, gateway=g, clock=clock.now)
    with pytest.raises(ValueError, match="每日金额额度"), TestClient(app):
        pass
