"""Explicit real Redis invite limits, on the per-test authorized namespace only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from test_durable_receipts import real_coordinator  # noqa: F401

from tutor_api.errors import ApiError
from tutor_api.services.parent_invite_rate_limit import RedisInviteRedeemLimiter


def config(mode="fixed", actor=3, total=5):
    return SimpleNamespace(
        parent_invite_redeem_window_mode=mode,
        parent_invite_redeem_limit=actor,
        parent_invite_redeem_global_limit=total,
        parent_invite_redeem_window_seconds=1,
    )


def allow(limiter, actor, settings):
    try:
        limiter.check(actor, settings, datetime.now(UTC))
        return True
    except ApiError as error:
        assert error.status_code == 429 and error.code == "invite_rate_limited"
        return False


@pytest.mark.parametrize("mode", ["fixed", "sliding"])
def test_real_two_instances_enforce_actor_and_global_atomically(request, mode):
    redis = request.getfixturevalue("real_coordinator")
    independent = redis.client.client()
    first = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    second = RedisInviteRedeemLimiter(independent, namespace=redis.namespace)
    start = Event()
    settings = config(mode)
    settings.parent_invite_redeem_window_seconds = 60

    def attempt(index):
        assert start.wait(3)
        actor = "private-parent-" + str(index % 4)
        return actor, allow(first if index % 2 else second, actor, settings)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(attempt, index) for index in range(20)]
            start.set()
            result = [future.result(timeout=5) for future in futures]
        assert sum(accepted for _, accepted in result) == 5
        assert all(
            sum(accepted for actor, accepted in result if actor == name) <= 3
            for name in {actor for actor, _ in result}
        )
        restarted = RedisInviteRedeemLimiter(independent, namespace=redis.namespace)
        assert not allow(restarted, "new-parent", settings)
        keys = list(redis.client.scan_iter(match=redis.namespace + "*"))
        assert keys and all("private-parent" not in key for key in keys)
        assert all(
            0 < redis.client.pttl(key) <= settings.parent_invite_redeem_window_seconds * 1000
            for key in keys
        )
    finally:
        independent.close()


def test_real_actor_rejection_does_not_charge_global(request):
    redis = request.getfixturevalue("real_coordinator")
    first = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    second = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    settings = config(actor=2, total=10)
    assert allow(first, "same-parent", settings)
    assert allow(second, "same-parent", settings)
    assert not allow(first, "same-parent", settings)
    global_key = redis.namespace + "{parent-invite-limits}:global"
    assert redis.client.zcard(global_key) == 3  # metadata + two accepted attempts


@pytest.mark.parametrize("change", ["mode", "window", "limit"])
def test_real_config_changes_do_not_reset_active_buckets_and_ttl_recovers(request, change):
    redis = request.getfixturevalue("real_coordinator")
    first = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    old = config()
    old.parent_invite_redeem_window_seconds = 3600
    assert allow(first, "parent", old)
    new = config()
    new.parent_invite_redeem_window_seconds = 3600
    if change == "mode":
        new.parent_invite_redeem_window_mode = "sliding"
    elif change == "window":
        new.parent_invite_redeem_window_seconds = 2
    else:
        new.parent_invite_redeem_limit = 4
    restarted = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    assert not allow(restarted, "parent", new)
    for key in redis.client.scan_iter(match=redis.namespace + "*"):
        redis.client.pexpire(key, 0)
    assert allow(restarted, "parent", new)


def test_real_redis_api_replay_role_and_revocation_preserve_authorization(
    request, onboarded, parent, app
):
    from support.parents import invite, link, revoke

    redis = request.getfixturevalue("real_coordinator")
    app.state.settings.parent_invite_redeem_limit = 1
    app.state.parent_invite_limiter = RedisInviteRedeemLimiter(
        redis.client, namespace=redis.namespace
    )
    created = invite(onboarded)
    linked = link(parent, created["code"], key="redis-shared-redeem")
    keys = list(redis.client.scan_iter(match=redis.namespace + "*"))
    members = [redis.client.zrange(key, 0, -1) for key in keys]
    assert created["code"] not in repr(keys + members)
    assert link(parent, created["code"], key="redis-shared-redeem") == linked
    assert (
        parent.error("POST", "/parents/links", expect=429, json={"code": "BAD"})["code"]
        == "invite_rate_limited"
    )
    assert (
        onboarded.error("POST", "/parents/links", expect=403, json={"code": created["code"]})[
            "code"
        ]
        == "forbidden"
    )
    from support.parents import links_of

    revoke(onboarded, links_of(onboarded)["links"][0]["id"])
    assert (
        parent.error("GET", f"/parents/students/{onboarded.user_id}/weekly", expect=404)["code"]
        == "not_found"
    )
    assert link(parent, created["code"], key="redis-shared-redeem") == linked
    assert (
        parent.error("GET", f"/parents/students/{onboarded.user_id}/weekly", expect=404)["code"]
        == "not_found"
    )


@pytest.mark.parametrize("mode", ["fixed", "sliding"])
def test_real_window_aging_preserves_fixed_or_sliding_semantics(request, mode):
    redis = request.getfixturevalue("real_coordinator")
    limiter = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    settings = config(mode, actor=2, total=10)
    settings.parent_invite_redeem_window_seconds = 3600
    assert allow(limiter, "parent", settings)
    keys = list(redis.client.scan_iter(match=redis.namespace + "*"))
    seconds, micros = redis.client.time()
    expired_score = seconds * 1000 + micros // 1000 - 3600001
    for key in keys:
        entries = redis.client.zrangebyscore(key, 0, "+inf")
        assert len(entries) == 1
        redis.client.zadd(key, {entries[0]: expired_score})
    # An old member ages out of a sliding window; a fixed bucket retains it
    # until its key expires. Advance only isolated test data, never wall time.
    assert allow(limiter, "parent", settings)
    assert allow(limiter, "parent", settings) == (mode == "sliding")
    assert not allow(limiter, "parent", settings)
    for key in keys:
        redis.client.pexpire(key, 0)
    assert allow(limiter, "parent", settings)
    assert allow(limiter, "parent", settings)
    assert not allow(limiter, "parent", settings)


def test_real_authentication_failure_is_failclosed_without_secret_echo(request):
    fixture = request.getfixturevalue("real_coordinator")
    redis = pytest.importorskip("redis")
    options = fixture.client.connection_pool.connection_kwargs
    client = redis.Redis(
        host=options["host"],
        port=options["port"],
        db=options["db"],
        password="incorrect-test-only-secret",
        socket_timeout=1,
    )
    try:
        limiter = RedisInviteRedeemLimiter(client, namespace=fixture.namespace)
        with pytest.raises(ApiError) as error:
            limiter.check("parent", config(), datetime.now(UTC))
        assert error.value.status_code == 429
        assert "incorrect-test-only-secret" not in str(error.value)
    finally:
        client.close()


def test_real_redis_is_injected_through_application_factory(request, onboarded, parent, app, clock):
    from starlette.testclient import TestClient

    from support.api import LOOPBACK, ApiClient
    from support.parents import invite, link
    from tutor_api.main import create_app

    fixture = request.getfixturevalue("real_coordinator")
    limiter = RedisInviteRedeemLimiter(fixture.client, namespace=fixture.namespace)
    app.state.settings.parent_invite_redeem_limit = 1
    other_app = create_app(app.state.settings, clock=clock.now, parent_invite_limiter=limiter)
    with TestClient(other_app, client=LOOPBACK) as raw:
        student_api = ApiClient(raw, onboarded.token, onboarded.user_id)
        parent_api = ApiClient(raw, parent.token, parent.user_id)
        created = invite(student_api)
        link(parent_api, created["code"])
        assert (
            parent_api.error("POST", "/parents/links", expect=429, json={"code": "BAD"})["code"]
            == "invite_rate_limited"
        )
        assert other_app.state.parent_invite_limiter is limiter
