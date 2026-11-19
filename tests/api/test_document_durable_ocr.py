from pathlib import Path

import pytest
from sqlalchemy import select
from test_document_import_jobs import PATH
from test_document_import_worker import queued
from test_document_ocr_recovery import PowerLoss

from ai_gateway import GatewayConfig, build_gateway
from ai_gateway.invocation_state import InvocationTransitions
from support.documents import png_image
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    timeout,
)
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob, DocumentImportOcrAttempt
from tutor_api.services.document_import_worker import process_next
from tutor_api.services.invocation_store import InvocationStore, intents, metadata


def scan_parser(*args, **kwargs):
    if "page" in kwargs:
        return {"png": "self-authored-preview"}
    return {
        "pages": [
            {
                "number": 1,
                "text": "",
                "method": "unavailable",
                "confidence": None,
                "warnings": [],
                "media_refs": [],
            }
        ]
    }


def install(app, clock, *, available=True, fails=False, platform_limit=20, daily_cost_cap=None):
    app.state.settings.import_ocr_mode = "configured"
    app.state.settings.pseudonym_secret = "stable-self-authored-ocr-secret"
    factory = app.state.session_factory
    metadata.create_all(factory.kw["bind"])
    store = InvocationStore(
        factory,
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
        now=clock.now,
    )
    adapter = ScriptedProvider(
        timeout() if fails else {"stem_text": "1. 自编OCR恢复题", "expressions": []}
    )
    gateway = build_gateway(
        GatewayConfig.model_validate(
            config_dict(
                {"x": external_provider(enabled=available)},
                ["x"],
                budgets={
                    "platform_daily_requests": platform_limit,
                    "platform_daily_max_cost_micros": daily_cost_cap,
                },
            )
        ),
        env=FULL_ENV,
        environment="local",
        allow_external_calls=True,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"x": adapter},
        now=clock.now,
    )
    return store, gateway, adapter


@pytest.mark.parametrize("fails", [False, True])
def test_durable_ocr_reserves_and_settles_once_without_gateway_retry(reviewer, app, clock, fails):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    store, gateway, adapter = install(app, clock, fails=fails)
    assert process_next(
        app.state.session_factory,
        app.state.settings,
        clock.now,
        parser=scan_parser,
        gateway=gateway,
        invocation_store=store,
    )
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["files"][0]["status"] == ("needs_ocr" if fails else "ready")
    assert len(adapter.calls) == 1
    with app.state.session_factory() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == "applied"
        audit = db.scalar(select(ModelCallAudit))
        assert audit.task_type == "ocr_extract" and audit.provider_calls == 1
        buckets = list(db.scalars(select(ModelBudgetUsage)))
        assert len(buckets) == 2 and all(row.request_count == 1 for row in buckets)


@pytest.mark.parametrize(
    "available,platform_limit,daily_cost_cap,image_price",
    [(False, 20, None, 5000), (True, 0, None, 5000), (True, 20, 0, 5000), (True, 20, None, None)],
)
def test_durable_ocr_unsent_fallback_does_not_consume_quota(
    reviewer, app, clock, available, platform_limit, daily_cost_cap, image_price
):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    store, gateway, adapter = install(
        app,
        clock,
        available=available,
        platform_limit=platform_limit,
        daily_cost_cap=daily_cost_cap,
    )
    gateway._config.providers["x"].pricing.image_unit_micros = image_price
    process_next(
        app.state.session_factory,
        app.state.settings,
        clock.now,
        parser=scan_parser,
        gateway=gateway,
        invocation_store=store,
    )
    assert adapter.calls == []
    assert reviewer.data("GET", f"{PATH}/{job_id}")["files"][0]["status"] == "needs_ocr"
    with app.state.session_factory() as db:
        assert list(db.scalars(select(ModelCallAudit))) == []
        assert list(db.scalars(select(ModelBudgetUsage))) == []
        assert list(db.scalars(select(DocumentImportOcrAttempt))) == []


@pytest.mark.parametrize("loss_at", ["audit", "page", "settlement_race"])
def test_durable_ocr_recovers_dispatch_loss_without_resending(
    reviewer, app, clock, monkeypatch, loss_at
):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    store, gateway, adapter = install(app, clock)
    settle = store.settle_metadata
    captured = []

    def lose_audit(*args, **kwargs):
        captured.append((args, kwargs))
        raise PowerLoss()

    apply = store.applied_in_transaction
    if loss_at != "page":
        monkeypatch.setattr(store, "settle_metadata", lose_audit)
    else:
        monkeypatch.setattr(store, "applied_in_transaction", lose_audit)
    args = (app.state.session_factory, app.state.settings, clock.now)
    kwargs = dict(parser=scan_parser, gateway=gateway, invocation_store=store)
    with pytest.raises(PowerLoss):
        process_next(*args, **kwargs)
    with app.state.session_factory() as db:
        assert db.scalar(select(DocumentImportFile)).pages_json == []
        assert db.scalar(select(DocumentImportOcrAttempt)).state == "dispatch_unknown"
    monkeypatch.setattr(store, "settle_metadata", settle)
    monkeypatch.setattr(store, "applied_in_transaction", apply)
    raced = []
    if loss_at == "settlement_race":
        read = store.read

        def settle_after_snapshot(*args, **kwargs):
            snapshot = read(*args, **kwargs)
            if not raced:
                late_args, late_kwargs = captured[0]
                settle(*late_args, **late_kwargs)
                raced.append(True)
            return snapshot

        monkeypatch.setattr(store, "read", settle_after_snapshot)
    clock.advance(seconds=app.state.settings.import_worker_lease_seconds + 1)
    assert process_next(*args, **kwargs)
    assert len(adapter.calls) == 1
    assert reviewer.data("GET", f"{PATH}/{job_id}")["files"][0]["status"] == "needs_ocr"
    with app.state.session_factory() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == (
            "closed_unknown" if loss_at == "audit" else "applied"
        )
        assert len(list(db.scalars(select(ModelCallAudit)))) == int(loss_at != "audit")
        assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
    if loss_at == "settlement_race":
        assert raced == [True]
    if loss_at == "audit":
        args, kwargs = captured[0]
        for _ in range(2):
            assert settle(*args, **kwargs)["state"] == "closed_unknown"
        with app.state.session_factory() as db:
            assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        assert reviewer.data("GET", f"{PATH}/{job_id}")["files"][0]["status"] == "needs_ocr"


@pytest.mark.parametrize("invalidated", ["cancelled", "takeover"])
def test_durable_ocr_late_response_settles_cost_but_retires_business_context(
    reviewer, app, clock, monkeypatch, invalidated
):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    store, gateway, adapter = install(app, clock)
    invoke = adapter.invoke

    def late_response(*args, **kwargs):
        result = invoke(*args, **kwargs)
        with app.state.session_factory() as db:
            job = db.get(DocumentImportJob, job_id)
            if invalidated == "cancelled":
                job.status = "cancelled"
            else:
                job.lease_id = "new-worker"
            db.commit()
        return result

    monkeypatch.setattr(adapter, "invoke", late_response)
    process_next(
        app.state.session_factory,
        app.state.settings,
        clock.now,
        parser=scan_parser,
        gateway=gateway,
        invocation_store=store,
    )
    with app.state.session_factory() as db:
        assert db.execute(select(intents.c.state)).scalar_one() == "stale"
        assert db.scalar(select(DocumentImportFile)).pages_json == []
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        assert all(row.request_count == 1 for row in db.scalars(select(ModelBudgetUsage)))
