"""Configuration gates do not open a database or fabricate managed dependencies."""

from types import SimpleNamespace

import pytest

from ai_gateway import GatewayConfig, build_gateway
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
)
from tutor_api.blob_store import FilesystemBlobStore
from tutor_api.receipts import SqlReceiptStore
from tutor_api.runtime_dependencies import managed_configuration
from tutor_api.services.parent_invite_rate_limit import RedisInviteRedeemLimiter
from tutor_api.settings import Settings


@pytest.mark.parametrize("environment", ["dev", "staging"])
@pytest.mark.parametrize("unavailable", ["disabled", "missing_env", "circuit_open"])
def test_managed_rejects_external_intent_even_when_no_candidate_is_usable(
    tmp_path, environment, unavailable
):
    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={"env": environment})
    gateway = build_gateway(
        GatewayConfig.model_validate(
            config_dict(
                {
                    "x": external_provider(
                        enabled=unavailable != "disabled", environments=["dev", "staging"]
                    )
                },
                ["x"],
            )
        ),
        env={} if unavailable == "missing_env" else FULL_ENV,
        environment=environment,
        allow_external_calls=True,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"x": ScriptedProvider(hint_ok())},
    )
    if unavailable == "circuit_open":
        for _ in range(gateway._config.defaults.circuit_breaker.failure_threshold):
            gateway._breakers["x"].record_failure()
    assert gateway.external_calls_possible is False
    values[-1] = gateway
    with pytest.raises(ValueError, match="外部模型"):
        managed_configuration(*values)


def dependencies(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    media = FilesystemBlobStore(root, max_bytes=1024)
    identity = SimpleNamespace(authenticate=lambda db, token: None)
    limiter = RedisInviteRedeemLimiter(SimpleNamespace(ping=lambda: True), namespace="unit:")
    settings = Settings(
        env="staging",
        database_url="mysql+pymysql://fixture@localhost/fixture",
        pseudonym_secret="unit-stable-secret",
    )
    return settings, identity, media, limiter, SqlReceiptStore(), None, None


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_configuration_requires_explicit_dependencies(tmp_path, environment):
    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={"env": environment})
    assert managed_configuration(*values)
    for index in (1, 2, 3, 4):
        missing = values.copy()
        missing[index] = None
        with pytest.raises(ValueError, match="生产存储"):
            managed_configuration(*missing)


@pytest.mark.parametrize(
    "flag",
    [
        "seed_sample_content",
        "import_worker_enabled",
        "allow_external_model_calls",
        "local_identity_mock",
    ],
)
def test_managed_does_not_ignore_prototype_or_external_flags(tmp_path, flag):
    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={flag: True})
    with pytest.raises(ValueError):
        managed_configuration(*values)


def test_prod_stays_blocked_even_with_complete_dependencies(tmp_path):
    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={"env": "prod"})
    with pytest.raises(ValueError, match="prod"):
        managed_configuration(*values)


def test_local_mysql_cannot_bootstrap_proto_tables(tmp_path):
    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={"env": "local"})
    with pytest.raises(ValueError, match="SQLite"):
        managed_configuration(*values)


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_accepts_explicit_bounded_loopback_s3_without_io(tmp_path, environment):
    from test_s3_blob_store import FakeS3, local_client_metadata, store

    values = list(dependencies(tmp_path))
    values[0] = values[0].model_copy(update={"env": environment})
    client = FakeS3()
    local_client_metadata(client)
    values[2] = store(client)
    assert client.objects == {}
    assert managed_configuration(*values)
    assert client.objects == {}
    client.meta.endpoint_url = "https://example.com:443"
    with pytest.raises(ValueError, match="loopback"):
        managed_configuration(*values)


def test_falsey_injected_gateway_is_not_silently_replaced(monkeypatch):
    import tutor_api.main as main

    class Gateway:
        external_calls_possible = False

        def __bool__(self):
            return False

    def forbidden(*args, **kwargs):
        pytest.fail("explicit gateway must not fall back")

    monkeypatch.setattr(main, "build_gateway", forbidden)
    gateway = Gateway()
    app = main.create_app(Settings(database_url="sqlite:///:memory:"), gateway=gateway)
    assert app.state.gateway is gateway
    app.state.session_factory.kw["bind"].dispose()
