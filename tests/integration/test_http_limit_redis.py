# ruff: noqa: F811 -- imported pytest fixtures intentionally share test parameter names
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from starlette.testclient import TestClient
from test_durable_receipts import real_coordinator  # noqa: F401
from test_managed_runtime import dependencies  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from support.api import LOOPBACK, ApiClient
from tutor_api.main import create_app
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.http_limits import RedisHttpLimiter


@pytest.fixture
def http_client(real_coordinator):
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    source = real_coordinator.client.connection_pool.connection_kwargs
    connection = {key: source.get(key) for key in ("host", "port", "username", "password", "db")}
    client = Redis(
        **connection,
        socket_timeout=3,
        socket_connect_timeout=3,
        retry=Retry(NoBackoff(), 0),
        decode_responses=True,
    )
    try:
        yield client
    finally:
        client.close()


def test_two_api_instances_share_preauth_global_window(
    settings, clock, real_coordinator, http_client
):
    settings = settings.model_copy(update={"http_limits_enabled": True, "http_limit_global": 1})
    limiter1 = RedisHttpLimiter(http_client, namespace=real_coordinator.namespace + "http:")
    limiter2 = RedisHttpLimiter(http_client, namespace=real_coordinator.namespace + "http:")
    first = create_app(settings, clock=clock.now, http_limiter=limiter1)
    second = create_app(settings, clock=clock.now, http_limiter=limiter2)
    with (
        TestClient(first, client=LOOPBACK) as raw1,
        TestClient(second, client=("127.0.0.2", 50001)) as raw2,
    ):
        assert ApiClient(raw1).get("/profile").status_code == 401
        assert ApiClient(raw2).get("/profile").status_code == 429
        assert ApiClient(raw2).get("/health").status_code == 200


def test_authenticated_quota_is_atomic_under_eight_requests(
    settings, clock, real_coordinator, student, http_client
):  # noqa: F811
    settings = settings.model_copy(update={"http_limits_enabled": True, "http_limit_per_actor": 1})
    limiter = RedisHttpLimiter(http_client, namespace=real_coordinator.namespace + "http:")
    app = create_app(settings, clock=clock.now, http_limiter=limiter)
    with TestClient(app, client=LOOPBACK) as raw:
        barrier = Barrier(8)

        def request(_):
            barrier.wait(timeout=5)
            return ApiClient(raw, token=student.token).get("/profile").status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(8)))
    assert results.count(200) == 1
    assert results.count(429) == 7


def test_managed_http_startup_checks_redis_without_charging_quota(dependencies, http_client):
    _, _, _, configured, identity, media, invite_limiter = dependencies
    settings = configured.model_copy(update={"http_limits_enabled": True})
    namespace = invite_limiter.namespace + "http-startup:"
    shared = RedisHttpLimiter(http_client, namespace=namespace)
    before = set(shared.client.scan_iter(match=namespace + "*"))
    app = create_app(
        settings,
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=invite_limiter,
        receipt_store=SqlReceiptStore(),
        http_limiter=shared,
    )
    with TestClient(app, client=LOOPBACK) as raw:
        assert ApiClient(raw).get("/health").status_code == 200
        assert set(shared.client.scan_iter(match=namespace + "*")) == before
        assert ApiClient(raw, token="student").get("/profile").status_code == 200


@pytest.mark.parametrize("kind", ["actor", "route"])
def test_authenticated_limits_shared_between_two_instances(
    settings, clock, real_coordinator, http_client, student, kind
):
    updates = {"http_limits_enabled": True}
    if kind == "actor":
        updates["http_limit_per_actor"] = 1
    else:
        updates["http_route_requests"] = {"GET /profile": 1}
    settings = settings.model_copy(update=updates)
    first = create_app(
        settings,
        clock=clock.now,
        http_limiter=RedisHttpLimiter(
            http_client, namespace=real_coordinator.namespace + "routes:"
        ),
    )
    second = create_app(
        settings,
        clock=clock.now,
        http_limiter=RedisHttpLimiter(
            http_client, namespace=real_coordinator.namespace + "routes:"
        ),
    )
    with TestClient(first, client=LOOPBACK) as raw1, TestClient(second, client=LOOPBACK) as raw2:
        assert ApiClient(raw1, token=student.token).get("/profile").status_code == 200
        assert ApiClient(raw2, token=student.token).get("/profile").status_code == 429
