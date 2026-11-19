from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from tutor_api.main import create_app
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.invocation_runtime import initialize
from tutor_api.settings import Settings


@pytest.mark.parametrize(
    "secret,receipts", [(None, SqlReceiptStore()), ("stable-test-secret", None)]
)
def test_enabled_invocations_require_stable_identity_and_formal_receipts(secret, receipts):
    configured = Settings(durable_model_invocations_enabled=True, pseudonym_secret=secret)
    with pytest.raises(ValueError, match="正式SQL回执"):
        create_app(configured, receipt_store=receipts)


@pytest.mark.parametrize("policy", ["record_only", "pause_platform"])
def test_local_startup_explicitly_wires_store(settings, clock, policy):
    configured = settings.model_copy(
        update=dict(
            durable_model_invocations_enabled=True,
            pseudonym_secret="stable-runtime-test-secret",
            model_cost_overrun_policy=policy,
        )
    )
    app = create_app(configured, receipt_store=SqlReceiptStore(), clock=clock.now)
    assert app.state.invocation_store is None
    with TestClient(app):
        assert app.state.invocation_store is not None
        assert app.state.invocation_store.cost_gate.policy == policy
        assert (
            "model_invocation_intents"
            in inspect(app.state.session_factory.kw["bind"]).get_table_names()
        )


def test_import_worker_receives_initialized_durable_store(settings, clock, monkeypatch):
    import tutor_api.main as main

    seen = []

    class Worker:
        def __init__(self, factory, settings, clock, gateway, invocation_store=None):
            seen.append(invocation_store)

        def start(self):
            assert seen[-1] is not None

        def close(self):
            pass

    monkeypatch.setattr(main, "ImportWorker", Worker)
    configured = settings.model_copy(
        update=dict(
            durable_model_invocations_enabled=True,
            pseudonym_secret="stable-runtime-secret",
            import_worker_enabled=True,
        )
    )
    app = create_app(configured, receipt_store=SqlReceiptStore(), clock=clock.now)
    with TestClient(app):
        assert seen == [app.state.invocation_store]


def test_managed_initialization_never_creates_missing_table(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "managed-probe.db"))
    settings = Settings(
        durable_model_invocations_enabled=True, pseudonym_secret="stable-test-secret"
    )
    with pytest.raises(ValueError, match="迁移未就绪"):
        initialize(
            engine,
            sessionmaker(engine),
            settings,
            SqlReceiptStore(),
            lambda: datetime.now(UTC),
            managed=True,
        )
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_pause_policy_cannot_silently_run_without_durable_dispatch():
    with pytest.raises(ValueError, match="暂停策略"):
        create_app(Settings(model_cost_overrun_policy="pause_platform"))


def test_managed_014_only_database_is_not_silently_upgraded(tmp_path):
    from tutor_api.services.invocation_store import intents

    engine = create_engine("sqlite:///" + str(tmp_path / "old-014.db"))
    intents.create(engine)
    settings = Settings(durable_model_invocations_enabled=True, pseudonym_secret="stable-secret")
    with pytest.raises(ValueError, match="成本保护迁移"):
        initialize(
            engine,
            sessionmaker(engine),
            settings,
            SqlReceiptStore(),
            lambda: datetime.now(UTC),
            managed=True,
        )
    assert inspect(engine).get_table_names() == [intents.name]
    engine.dispose()
