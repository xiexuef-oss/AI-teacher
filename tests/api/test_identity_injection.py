import pytest
from starlette.testclient import TestClient

from support.api import LOOPBACK, ApiClient
from tutor_api.auth import LocalMockIdentityProvider, Principal
from tutor_api.main import create_app


def test_injected_identity_preserves_role_and_ownership(settings, clock, student, parent):
    class Provider:
        def authenticate(self, db, token):
            return {
                "test-student": Principal(student.user_id, "student"),
                "test-parent": Principal(parent.user_id, "parent"),
            }.get(token)

    app = create_app(
        settings.model_copy(update={"local_identity_mock": False}),
        clock=clock.now,
        identity_provider=Provider(),
    )
    with TestClient(app, client=LOOPBACK) as raw:
        own = ApiClient(raw, token="test-student", user_id=student.user_id)
        own.data("GET", "/profile")
        assert ApiClient(raw, token="test-parent").request("GET", "/profile").status_code == 403
        assert ApiClient(raw, token="unknown").request("GET", "/profile").status_code == 401
        assert own.request("POST", "/dev/local-identities", key=False).status_code == 404


def test_injected_local_mock_cannot_bypass_environment_restriction(settings):
    restricted = settings.model_copy(
        update={"env": "prod", "local_identity_mock": False, "pseudonym_secret": "test-secret"}
    )
    with pytest.raises(ValueError, match="local"):
        create_app(restricted, identity_provider=LocalMockIdentityProvider())


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_nonlocal_cannot_silently_bootstrap_prototype_storage(settings, monkeypatch, environment):
    import tutor_api.main as main

    def forbidden_engine(*args, **kwargs):
        raise AssertionError("must reject before opening or creating database")

    monkeypatch.setattr(main, "make_engine", forbidden_engine)
    restricted = settings.model_copy(
        update={"env": environment, "local_identity_mock": False, "pseudonym_secret": "test-secret"}
    )
    with pytest.raises(ValueError, match="生产存储"):
        create_app(restricted)
