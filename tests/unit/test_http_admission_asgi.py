import asyncio
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.responses import Response

from tutor_api.middleware import RequestContextMiddleware
from tutor_api.services.http_limits import (
    HttpLimitsMiddleware,
    InMemoryHttpLimiter,
    RedisHttpLimiter,
)
from tutor_api.settings import Settings


def scope():
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/profile",
        "headers": [],
        "client": ("127.0.0.1", 5000),
        "query_string": b"",
    }


def policy(app, **settings):
    return RequestContextMiddleware(
        HttpLimitsMiddleware(
            app,
            settings=Settings(http_limits_enabled=True, **settings),
            limiter=InMemoryHttpLimiter(),
            clock=lambda: datetime.now(UTC),
        ),
        loopback_only=False,
    )


def test_actual_stream_size_is_enforced_despite_smaller_declared_length():
    async def exercise():
        called, responses = [], []

        async def app(*args):
            called.append(True)

        messages = iter(
            [
                {"type": "http.request", "body": b"x" * 600, "more_body": True},
                {"type": "http.request", "body": b"y" * 600, "more_body": False},
            ]
        )

        async def receive():
            return next(messages)

        async def send(message):
            responses.append(message)

        request = scope()
        request["headers"] = [(b"content-length", b"1")]
        await policy(app, http_max_body_bytes=1024)(request, receive, send)
        assert not called
        assert responses[0]["status"] == 413
        assert json.loads(responses[1]["body"])["error"]["request_id"]

    asyncio.run(exercise())


def test_slow_body_times_out_without_starting_business():
    async def exercise():
        called, responses = [], []

        async def app(*args):
            called.append(True)

        async def receive():
            await asyncio.sleep(0.1)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            responses.append(message)

        await policy(app, http_body_timeout_seconds=0.01)(scope(), receive, send)
        assert responses[0]["status"] == 408
        assert not called

    asyncio.run(exercise())


def test_final_body_frame_cannot_start_business_after_deadline():
    async def exercise():
        output = []

        async def app(request, receive, send):
            await Response(status_code=200)(request, receive, send)

        async def receive():
            # A non-cooperative ASGI adapter may return after the timer expired.
            time.sleep(0.03)
            return {"type": "http.request", "body": b"complete", "more_body": False}

        async def send(message):
            output.append(message)

        await policy(app, http_body_timeout_seconds=0.005)(scope(), receive, send)
        assert output[0]["status"] == 408

    asyncio.run(exercise())


def test_inflight_rejection_and_slot_release_after_completion():
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def app(request, receive, send):
            body = await receive()
            assert body["body"] == b"original"
            entered.set()
            await release.wait()
            await Response(status_code=200)(request, receive, send)

        gate = policy(app, http_max_inflight=1)

        async def call():
            output = []

            async def receive():
                return {"type": "http.request", "body": b"original", "more_body": False}

            async def send(message):
                output.append(message)

            await gate(scope(), receive, send)
            return output[0]["status"]

        first = asyncio.create_task(call())
        await entered.wait()
        assert await asyncio.wait_for(call(), timeout=2) == 429
        release.set()
        assert await first == 200
        assert await call() == 200

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "values",
    [
        {
            "socket_timeout": None,
            "socket_connect_timeout": 3,
            "retry": SimpleNamespace(get_retries=lambda: 0),
        },
        {
            "socket_timeout": 3,
            "socket_connect_timeout": 0,
            "retry": SimpleNamespace(get_retries=lambda: 0),
        },
        {
            "socket_timeout": 3,
            "socket_connect_timeout": 3,
            "retry": SimpleNamespace(get_retries=lambda: -1),
        },
        {
            "socket_timeout": 3,
            "socket_connect_timeout": 3,
            "retry": SimpleNamespace(get_retries=lambda: 3),
        },
    ],
)
def test_unbounded_or_retrying_redis_clients_are_refused(values):
    client = SimpleNamespace(connection_pool=SimpleNamespace(connection_kwargs=values))
    with pytest.raises(ValueError, match="timeout"):
        RedisHttpLimiter(client, namespace="test-http:")


@pytest.mark.parametrize("blocking_pool", [True, False])
def test_redis_pool_or_single_connection_cannot_wait_without_bound(blocking_pool):
    pool = SimpleNamespace(
        connection_kwargs={
            "socket_timeout": 3,
            "socket_connect_timeout": 3,
            "retry": SimpleNamespace(get_retries=lambda: 0),
        }
    )
    if blocking_pool:
        pool.timeout = None
    client = SimpleNamespace(connection_pool=pool, single_connection_client=not blocking_pool)
    with pytest.raises(ValueError, match="timeout"):
        RedisHttpLimiter(client, namespace="test-pool:")
