"""请求上下文中间件：请求 ID 回显，以及本地身份 Mock 开启时的回环地址限制。"""

from __future__ import annotations

import ipaddress
import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tutor_api.errors import REQUEST_ID_HEADER

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def is_loopback(client: tuple[str, int] | None) -> bool:
    if not client:
        return False
    host = client[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, loopback_only: bool) -> None:
        self.app = app
        self.loopback_only = loopback_only

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = supplied if supplied and _REQUEST_ID.match(supplied) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        if self.loopback_only and not is_loopback(scope.get("client")):
            # 原型期的本地身份 Mock 只为本机服务（ADR-006 Q-03）
            response = JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "loopback_only",
                        "message": "本地身份 Mock 已开启，服务只接受本机回环地址的请求",
                        "details": {},
                        "request_id": request_id,
                    }
                },
            )
            await response(scope, receive, send_with_request_id)
            return

        await self.app(scope, receive, send_with_request_id)
