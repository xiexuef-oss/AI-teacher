"""后端基础：请求 ID、错误信封、本地身份 Mock、回环限制、planned 接口。"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from support.api import LOOPBACK, ApiClient
from support.contract import API_PREFIX, load_openapi

# ---------------------------------------------------------------- 健康检查与请求 ID


def test_health_reports_key_switches(anon, clock):
    data = anon.data("GET", "/health", auth=False)

    assert data["status"] == "ok"
    assert data["api_version"] == "v1"
    assert data["contract_version"] == load_openapi()["info"]["version"]
    assert data["environment"] == "local"
    assert data["local_identity_mock"] is True
    assert data["external_model_calls"] is False
    assert data["server_time"] == "2026-11-10T08:00:00Z"


def test_request_id_is_echoed(anon):
    response = anon.get("/health", auth=False, headers={"X-Request-Id": "req-abc.123"})
    assert response.headers["x-request-id"] == "req-abc.123"


def test_request_id_is_generated_when_missing(anon):
    first = anon.get("/health", auth=False).headers["x-request-id"]
    second = anon.get("/health", auth=False).headers["x-request-id"]
    assert len(first) >= 16 and first != second


def test_malformed_request_id_is_replaced(anon):
    response = anon.get("/health", auth=False, headers={"X-Request-Id": "bad id <script>"})
    assert response.headers["x-request-id"] != "bad id <script>"
    assert "<" not in response.headers["x-request-id"]


# ---------------------------------------------------------------- 跨域（本地开发时 Flutter Web 与 API 不同源）

PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,x-request-id",
}


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:8080"])
def test_local_environment_accepts_cross_origin_calls_from_this_machine(client, origin):
    preflight = client.options(f"{API_PREFIX}/sessions", headers={"Origin": origin, **PREFLIGHT})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    allowed = preflight.headers["access-control-allow-headers"].lower()
    assert all(
        h in allowed for h in ("authorization", "content-type", "idempotency-key", "x-request-id")
    )
    assert preflight.headers["x-request-id"], "预检响应同样回显请求 ID"

    response = client.get(f"{API_PREFIX}/health", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "x-request-id" in exposed and "idempotency-replayed" in exposed


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost.evil.example", "https://localhost:5173"]
)
def test_other_origins_get_no_cors_grant(client, origin):
    response = client.get(f"{API_PREFIX}/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in response.headers

    preflight = client.options(f"{API_PREFIX}/sessions", headers={"Origin": origin, **PREFLIGHT})
    assert "access-control-allow-origin" not in preflight.headers


def test_non_local_environment_sends_no_cors_headers(settings, clock):
    from tutor_api.main import create_app

    dev = settings.model_copy(update={"env": "dev", "local_identity_mock": False})
    with TestClient(create_app(dev, clock=clock.now), client=LOOPBACK) as raw:
        response = raw.get(f"{API_PREFIX}/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------- 错误信封


def test_unknown_route_uses_error_envelope(client):
    response = client.get(f"{API_PREFIX}/no-such-thing", headers={"X-Request-Id": "req-404"})

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == "req-404" == response.headers["x-request-id"]
    assert error["details"] == {}


def test_unexpected_errors_never_expose_stack_traces(app):
    @app.get(f"{API_PREFIX}/_boom")
    def boom():
        raise RuntimeError("secret internal detail: db password is hunter2")

    with TestClient(app, client=LOOPBACK, raise_server_exceptions=False) as raw:
        response = raw.get(f"{API_PREFIX}/_boom")

    assert response.status_code == 500
    assert response.headers["x-request-id"]
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == response.headers["x-request-id"]
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text and "RuntimeError" not in response.text


def test_validation_errors_do_not_echo_input(student):
    error = student.error(
        "PUT", "/profile", expect=422, json={"region_code": "SECRET-INPUT-99", "subjects": ["math"]}
    )

    assert error["code"] == "validation_error"
    assert error["details"]["errors"], "应指出出错的字段"
    assert error["details"]["errors"][0]["field"] == "region_code"
    assert "SECRET-INPUT-99" not in str(error)


def test_malformed_json_body_is_a_validation_error(student):
    error = student.error("PUT", "/profile", expect=422, content=b"{not json")
    assert error["code"] == "validation_error"


# ---------------------------------------------------------------- 本地身份 Mock（Q-03）


def test_create_identity_returns_random_bearer(anon):
    first = anon.data("POST", "/dev/local-identities", expect=201, auth=False, key=False)
    second = anon.data("POST", "/dev/local-identities", expect=201, auth=False, key=False)

    assert first["role"] == "student" and first["token_type"] == "Bearer"
    assert len(first["access_token"]) >= 32
    assert first["access_token"] != second["access_token"]
    assert first["user_id"] != second["user_id"]


def test_token_is_stored_only_as_hash(anon, db):
    identity = anon.data("POST", "/dev/local-identities", expect=201, auth=False, key=False)
    token = identity["access_token"]

    rows = db.execute(text("SELECT token_hash, user_id FROM proto_local_identities")).all()

    assert [(r.token_hash, r.user_id) for r in rows] == [
        (hashlib.sha256(token.encode()).hexdigest(), identity["user_id"])
    ]


def test_bearer_authenticates_the_student_it_was_issued_to(student):
    assert student.data("GET", "/profile")["user_id"] == student.user_id


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-real-token-000000000000000000000000"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "bearer "},
    ],
    ids=["missing", "unknown-token", "wrong-scheme", "no-token", "empty-token"],
)
def test_requests_without_a_valid_token_are_401(anon, headers):
    error = anon.error("GET", "/profile", expect=401, headers=headers)
    assert error["code"] == "unauthenticated"


def test_identity_endpoint_is_hidden_when_mock_is_disabled(settings, clock):
    from tutor_api.main import create_app

    app = create_app(settings.model_copy(update={"local_identity_mock": False}), clock=clock.now)
    with TestClient(app, client=LOOPBACK) as raw:
        api = ApiClient(raw)

        hidden = api.error("POST", "/dev/local-identities", expect=404, auth=False, key=False)
        health = api.data("GET", "/health", auth=False)
        profile = api.error(
            "GET", "/profile", expect=401, headers={"Authorization": "Bearer " + "x" * 43}
        )

    assert hidden["code"] == "not_found"
    assert health["local_identity_mock"] is False
    assert profile["code"] == "unauthenticated"


def test_identity_mock_cannot_be_enabled_outside_local():
    from tutor_api.settings import Settings

    with pytest.raises(ValueError, match="local"):
        Settings(env="prod", local_identity_mock=True, pseudonym_secret="s")


def test_non_local_environment_requires_pseudonym_secret():
    from tutor_api.settings import Settings

    with pytest.raises(ValueError, match="PSEUDONYM"):
        Settings(env="staging", pseudonym_secret=None)


def test_non_loopback_client_is_rejected_while_mock_is_enabled(app):
    """回环限制是中间件层的整体拦截（对所有路径生效），不属于单个操作的契约，这里用原始客户端核对。"""
    with TestClient(app, client=("203.0.113.9", 4444)) as remote:
        for method, path in (
            ("GET", "/health"),
            ("POST", "/dev/local-identities"),
            ("GET", "/profile"),
        ):
            response = remote.request(method, API_PREFIX + path)

            assert response.status_code == 403, path
            error = response.json()["error"]
            assert error["code"] == "loopback_only", path
            assert error["request_id"] == response.headers["x-request-id"]
            assert set(error) == {"code", "message", "details", "request_id"}


def test_loopback_restriction_does_not_apply_without_the_mock(settings, clock):
    from tutor_api.main import create_app

    app = create_app(settings.model_copy(update={"local_identity_mock": False}), clock=clock.now)
    with TestClient(app, client=("203.0.113.9", 4444)) as remote:
        assert ApiClient(remote).data("GET", "/health", auth=False)["status"] == "ok"


# ---------------------------------------------------------------- planned 接口

PLANNED_CALLS = [
    ("POST", "/media/uploads"),
    ("POST", "/scans"),
    ("GET", f"/scans/{uuid.uuid4()}"),
    ("POST", f"/scans/{uuid.uuid4()}/confirm"),
]


@pytest.mark.parametrize(("method", "path"), PLANNED_CALLS, ids=[p for _, p in PLANNED_CALLS])
def test_planned_operations_return_501(student, method, path):
    error = student.error(method, path, expect=501, json={} if method == "POST" else None)
    assert error["code"] == "not_implemented"


@pytest.mark.parametrize(("method", "path"), PLANNED_CALLS, ids=[p for _, p in PLANNED_CALLS])
def test_planned_operations_still_require_authentication(anon, method, path):
    error = anon.error(method, path, expect=401, json={} if method == "POST" else None)
    assert error["code"] == "unauthenticated"
