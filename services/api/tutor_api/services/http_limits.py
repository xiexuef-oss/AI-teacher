"""HTTP quotas and bounded body admission; no request content is retained."""

import asyncio
import math
import time
from threading import Lock
from types import SimpleNamespace

import anyio
import yaml
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from tutor_api import API_PREFIX
from tutor_api.errors import ApiError
from tutor_api.services.parent_invite_rate_limit import (
    InMemoryInviteRedeemLimiter,
    RedisInviteRedeemLimiter,
)
from tutor_api.settings import OPENAPI_PATH


def denied(settings):
    return ApiError(
        429,
        "rate_limited",
        "请求过于频繁或暂不可用，请稍后重试",
        headers={"Retry-After": str(settings.http_limit_window_seconds)},
    )


def validate_route_configuration(settings):
    if not settings.http_route_requests:
        return
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    allowed = {
        f"{method.upper()} {path}"
        for path, operations in contract["paths"].items()
        for method, operation in operations.items()
        if method in {"get", "put", "post", "delete", "patch"}
        and operation.get("security", contract.get("security"))
    }
    if not set(settings.http_route_requests) <= allowed:
        raise ValueError("HTTP路由额度须使用需要认证的已声明 METHOD /path 模板")


class _HttpLimiter:
    def _check(self, backend, actor, settings, now, limit):
        # Reuse the already validated atomic window mechanism in separate namespaces.
        configuration = SimpleNamespace(
            parent_invite_redeem_window_mode=settings.http_limit_window_mode,
            parent_invite_redeem_window_seconds=settings.http_limit_window_seconds,
            parent_invite_redeem_limit=limit,
            parent_invite_redeem_global_limit=settings.http_limit_global,
        )
        try:
            backend.check(actor, configuration, now)
        except Exception:
            raise denied(settings) from None

    def check_peer(self, peer, settings, now):
        self._check(self.peers, peer, settings, now, settings.http_limit_per_peer)

    def check_actor(self, actor, settings, now):
        self._check(self.actors, actor, settings, now, settings.http_limit_per_actor)

    def check_route(self, actor, method, route, settings, now):
        template = getattr(route, "path_format", "").removeprefix(API_PREFIX)
        key = method + " " + template
        limit = settings.http_route_requests.get(key)
        if limit is not None:
            self._check(self.routes, key + ":" + actor, settings, now, limit)


class InMemoryHttpLimiter(_HttpLimiter):
    def __init__(self):
        self.peers = InMemoryInviteRedeemLimiter()
        self.actors = InMemoryInviteRedeemLimiter()
        self.routes = InMemoryInviteRedeemLimiter()


class RedisHttpLimiter(_HttpLimiter):
    def __init__(self, client, *, namespace):
        if not namespace:
            raise ValueError("Explicit isolated Redis namespace required")
        try:
            pool = client.connection_pool
            configuration = pool.connection_kwargs
            timeout = configuration.get("socket_timeout")
            connect = configuration.get("socket_connect_timeout")
            connect = timeout if connect is None else connect
            retries = configuration["retry"].get_retries()
            bounded = (
                all(
                    type(value) in (int, float) and math.isfinite(value) and 0 < value <= 10
                    for value in (timeout, connect)
                )
                and type(retries) is int
                and retries == 0
                and not getattr(client, "single_connection_client", False)
            )
            if hasattr(pool, "timeout"):
                queue_timeout = pool.timeout
                bounded = (
                    bounded
                    and type(queue_timeout) in (int, float)
                    and math.isfinite(queue_timeout)
                    and 0 < queue_timeout <= 10
                )
        except Exception:
            bounded = False
        if not bounded:
            raise ValueError(
                "HTTP Redis需有限socket/connect/pool timeout（不超过10秒）、非single连接且禁用SDK重试"
            )
        self.client = client
        self.peers = RedisInviteRedeemLimiter(client, namespace=namespace + "peer:")
        self.actors = RedisInviteRedeemLimiter(client, namespace=namespace + "actor:")
        self.routes = RedisInviteRedeemLimiter(client, namespace=namespace + "route:")


class HttpLimitsMiddleware:
    def __init__(self, app, *, settings, limiter, clock):
        self.app, self.settings, self.limiter, self.clock = app, settings, limiter, clock
        self._active = 0
        self._lock = Lock()

    async def _error(self, scope, receive, send, error):
        response = JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": {},
                    "request_id": scope.get("state", {}).get("request_id", ""),
                }
            },
            headers=error.headers,
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (
            scope.get("method") == "GET" and scope.get("path") == "/api/v1/health"
        ):
            await self.app(scope, receive, send)
            return
        with self._lock:
            admitted = self._active < self.settings.http_max_inflight
            if admitted:
                self._active += 1
        if not admitted:
            await self._error(scope, receive, send, denied(self.settings))
            return
        try:
            try:
                peer = (scope.get("client") or ("unknown", 0))[0]
                # No forwarded-header parsing here; server/proxy peer trust
                # must be explicit (the local launcher disables proxy headers).
                await anyio.to_thread.run_sync(
                    self.limiter.check_peer, peer, self.settings, self.clock()
                )
            except Exception:
                await self._error(scope, receive, send, denied(self.settings))
                return
            try:
                declared = int(Headers(scope=scope).get("content-length", "0"))
            except ValueError:
                declared = 0  # The actual byte count below is authoritative.
            if declared > self.settings.http_max_body_bytes:
                await self._error(
                    scope, receive, send, ApiError(413, "payload_too_large", "请求体超过上限")
                )
                return
            buffered, total = bytearray(), 0
            deadline = time.monotonic() + self.settings.http_body_timeout_seconds
            while True:
                try:
                    message = await asyncio.wait_for(
                        receive(), timeout=max(0.001, deadline - time.monotonic())
                    )
                except TimeoutError:
                    await self._error(
                        scope,
                        receive,
                        send,
                        ApiError(408, "request_timeout", "接收请求体超时，请保留本机内容后重试"),
                    )
                    return
                if message["type"] == "http.disconnect":
                    return
                if time.monotonic() >= deadline:
                    await self._error(
                        scope,
                        receive,
                        send,
                        ApiError(408, "request_timeout", "接收请求体超时，请重试"),
                    )
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.settings.http_max_body_bytes:
                    await self._error(
                        scope, receive, send, ApiError(413, "payload_too_large", "请求体超过上限")
                    )
                    return
                if chunk:
                    buffered.extend(chunk)
                if not message.get("more_body", False):
                    break
            body = bytes(buffered)
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            with self._lock:
                self._active -= 1
