import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "setup_deepseek", Path(__file__).resolve().parents[2] / "tools/setup_deepseek.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_windows_reads_only_named_user_variable(monkeypatch):
    calls = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def query(key, name):
        calls.append(name)
        return "user-secret", 1

    registry = SimpleNamespace(
        HKEY_CURRENT_USER=123,
        REG_SZ=1,
        REG_EXPAND_SZ=2,
        OpenKey=lambda hive, path: Key() if (hive, path) == (123, "Environment") else None,
        QueryValueEx=query,
    )
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert setup.read_user_key() == "user-secret"
    assert calls == [setup.KEY_ENV]


def test_defaults_load_only_nonsecret_names(monkeypatch, tmp_path):
    defaults = tmp_path / "defaults.env"
    defaults.write_text(
        "DEEPSEEK_BASE_URL=https://test.example\nDEEPSEEK_MODEL_FLASH=test-model\nDeepSeek_ANTHROPIC_AUTH_TOKEN=file-secret\n"
    )
    monkeypatch.setattr(setup, "DEFAULTS", defaults)
    monkeypatch.setattr(setup, "read_user_key", lambda: "user-secret")
    monkeypatch.delenv(setup.KEY_ENV, raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH", "existing-model")
    setup.load_environment()
    assert setup.os.environ[setup.KEY_ENV] == "user-secret"
    assert setup.os.environ["DEEPSEEK_BASE_URL"] == "https://test.example"
    assert setup.os.environ["DEEPSEEK_MODEL_FLASH"] == "existing-model"


def test_profile_is_safe_and_flash_first():
    from ai_gateway.config import load_config

    config = load_config(setup.PROFILE)
    provider = config.providers["deepseek"]
    assert provider.api_key_env == setup.KEY_ENV
    assert provider.base_url_env == "DEEPSEEK_BASE_URL"
    assert not provider.enabled and not provider.compliance_approved
    assert not provider.pricing.verified
    for route in config.routes.values():
        assert route.candidates[0].provider == "deepseek"
        assert route.candidates[0].model_env == "DEEPSEEK_MODEL_FLASH"


def test_prepare_does_not_overwrite(tmp_path):
    target = tmp_path / "routes.yaml"
    assert setup.prepare(target)
    target.write_text("existing", encoding="utf-8")
    assert not setup.prepare(target)
    assert target.read_text() == "existing"
    assert setup.prepare(target, force=True)


def test_user_key_fallback_is_not_persisted(monkeypatch, tmp_path):
    monkeypatch.delenv(setup.KEY_ENV, raising=False)
    monkeypatch.setattr(setup, "read_user_key", lambda: "user-secret")
    assert setup.read_key() == "user-secret"
    target = tmp_path / "routes.yaml"
    setup.prepare(target)
    assert "user-secret" not in target.read_text()


def test_missing_key_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv(setup.KEY_ENV, raising=False)
    monkeypatch.setattr(setup, "read_user_key", lambda: None)
    assert setup.check_models("https://api.deepseek.com", None) == 1
    assert "missing" in capsys.readouterr().out


@pytest.mark.parametrize("status", [200, 401, 500])
def test_check_redacts_body_and_has_timeout(status, capsys):
    def handle(request):
        assert request.extensions["timeout"]["read"] == 10
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(status, json={"data": [{"id": "deepseek-flash"}], "secret": "secret"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert setup.check_models("https://api.deepseek.com", "secret", client=client) == (
            status != 200
        )
    output = capsys.readouterr().out
    assert "secret" not in output
    assert str(status) in output
    assert ("deepseek-flash" in output) == (status == 200)


def test_transport_error_redacted(capsys):
    def handle(request):
        raise httpx.ReadTimeout("secret body", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert setup.check_models("https://api.deepseek.com", "secret", client=client) == 1
    assert "secret" not in capsys.readouterr().out


def test_model_identifier_cannot_reflect_credentials(capsys):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "prefix-secret-suffix"}]})
        )
    ) as client:
        assert setup.check_models("https://test.example", "secret", client=client) == 0
    assert "secret" not in capsys.readouterr().out
