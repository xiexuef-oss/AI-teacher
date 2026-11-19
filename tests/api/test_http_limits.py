import pytest
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from support.api import LOOPBACK, ApiClient
from tutor_api.main import create_app
from tutor_api.services.http_limits import RedisHttpLimiter


def limited(settings, clock, **values):
    configured = settings.model_copy(update={"http_limits_enabled": True, **values})
    return create_app(configured, clock=clock.now)


def test_peer_limit_applies_to_invalid_tokens_and_health_stays_available(settings, clock):
    app = limited(settings, clock, http_limit_per_peer=1)
    with TestClient(app, client=LOOPBACK) as raw:
        client = ApiClient(raw, token="not-a-token")
        assert client.get("/profile").status_code == 401
        denied = client.get(
            "/profile",
            headers={
                "X-Forwarded-For": "203.0.113.99",
                "Authorization": "Bearer changed-invalid-token",
            },
        )
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "rate_limited"
        assert int(denied.headers["retry-after"]) >= 1
        assert client.get("/health").status_code == 200


def test_actor_limit_uses_authenticated_identity_and_preserves_cors(settings, clock, student):
    app = limited(settings, clock, http_limit_per_actor=1)
    with TestClient(app, client=LOOPBACK) as raw:
        client = ApiClient(raw, token=student.token)
        assert client.get("/profile").status_code == 200
        denied = client.get("/profile", headers={"Origin": "http://127.0.0.1:7357"})
        assert denied.status_code == 429
        assert denied.headers["access-control-allow-origin"] == "http://127.0.0.1:7357"
        assert "retry-after" in denied.headers["access-control-expose-headers"].lower()


def test_oversized_body_never_reaches_business_and_preserves_request_id(settings, clock, student):
    app = limited(settings, clock, http_max_body_bytes=1024)
    with TestClient(app, client=LOOPBACK) as raw:
        client = ApiClient(raw, token=student.token)
        before = client.data("GET", "/profile")
        result = client.request(
            "PUT", "/profile", content=b" " * 2000, headers={"X-Request-Id": "size-check"}
        )
        assert result.status_code == 413
        assert result.headers["x-request-id"] == "size-check"
        assert client.data("GET", "/profile") == before


def test_redis_failure_denies_without_ram_fallback_or_private_detail(settings, clock):
    from types import SimpleNamespace

    class Unavailable:
        connection_pool = SimpleNamespace(
            connection_kwargs={
                "socket_timeout": 1,
                "socket_connect_timeout": 1,
                "retry": SimpleNamespace(get_retries=lambda: 0),
            }
        )

        def eval(self, *args):
            raise RuntimeError("private-connection-detail")

    app = create_app(
        settings.model_copy(update={"http_limits_enabled": True}),
        clock=clock.now,
        http_limiter=RedisHttpLimiter(Unavailable(), namespace="test-unavailable:"),
    )
    with TestClient(app, client=LOOPBACK) as raw:
        response = ApiClient(raw).get("/profile")
        assert response.status_code == 429
        assert "private-connection-detail" not in response.text


def test_nonlocal_enabled_limits_require_explicit_shared_backend_before_database(
    settings, monkeypatch
):
    monkeypatch.setattr(
        "tutor_api.main.make_engine", lambda *a: pytest.fail("database must not open")
    )
    with pytest.raises(ValueError, match="共享Redis"):
        create_app(settings.model_copy(update={"env": "staging", "http_limits_enabled": True}))


def test_real_dev_launcher_does_not_enable_forwarded_peer_rewrite(settings, clock, monkeypatch):
    import os
    import sys

    import run_dev_api
    import uvicorn

    options = {}
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(sys, "argv", ["run_dev_api.py"])
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: options.update(kwargs))
    run_dev_api.main()
    app = limited(settings, clock, http_limit_per_peer=1)
    served = (
        ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
        if options.get("proxy_headers", True)
        else app
    )
    with TestClient(served, client=LOOPBACK) as raw:
        api = ApiClient(raw)
        assert api.get("/profile", headers={"X-Forwarded-For": "127.0.0.2"}).status_code == 401
        assert api.get("/profile", headers={"X-Forwarded-For": "127.0.0.3"}).status_code == 429


def test_route_quota_uses_template_not_resource_id_and_does_not_block_other_routes(
    settings, clock, student
):
    app = limited(settings, clock, http_route_requests={"GET /sessions/{session_id}": 1})
    with TestClient(app, client=LOOPBACK) as raw:
        api = ApiClient(raw, token=student.token)
        assert api.get("/sessions/00000000-0000-0000-0000-000000000001").status_code == 404
        assert api.get("/sessions/00000000-0000-0000-0000-000000000002").status_code == 429
        assert api.get("/profile").status_code == 200


@pytest.mark.parametrize(
    "route",
    ["GET /health", "GET /not-declared", "GET /sessions/00000000-0000-0000-0000-000000000001"],
)
def test_route_configuration_rejects_public_or_resource_specific_paths(settings, clock, route):
    with pytest.raises(ValueError, match="模板"):
        limited(settings, clock, http_route_requests={route: 1})
