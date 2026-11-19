"""带契约校验的 API 测试客户端。

每一个响应都按 contracts/openapi.yaml 校验：状态码未在契约声明、响应体不符合 schema、
或教学事件不过 tutor_event.schema.json，测试直接失败。
"""

from __future__ import annotations

import uuid
from typing import Any

from starlette.testclient import TestClient

from support.contract import API_PREFIX, validate_response

LOOPBACK = ("127.0.0.1", 50000)


class ApiClient:
    def __init__(
        self, client: TestClient, token: str | None = None, user_id: str | None = None
    ) -> None:
        self._client = client
        self.token = token
        self.user_id = user_id

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        key: str | bool | None = None,
        auth: bool = True,
        content: bytes | None = None,
    ) -> Any:
        """key：None 表示自动生成幂等键（仅 POST/PUT），False 表示不带，字符串表示指定。"""
        url = API_PREFIX + path
        merged: dict[str, str] = {}
        if auth and self.token:
            merged["Authorization"] = f"Bearer {self.token}"
        if key is None and method.upper() in {"POST", "PUT"}:
            key = f"test-{uuid.uuid4()}"
        if isinstance(key, str):
            merged["Idempotency-Key"] = key
        merged.update(headers or {})

        kwargs: dict[str, Any] = {"params": params, "headers": merged}
        if content is not None:
            kwargs["content"] = content
            merged.setdefault("Content-Type", "application/json")
        elif json is not None:
            kwargs["json"] = json
        response = self._client.request(method, url, **kwargs)

        assert response.headers.get("x-request-id"), "每个响应都必须回显 X-Request-Id"
        body = response.json() if response.content else None
        validate_response(method, url, response.status_code, body)
        return response

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def data(self, method: str, path: str, *, expect: int = 200, **kwargs: Any) -> Any:
        """发请求、断言状态码并取出 data。"""
        response = self.request(method, path, **kwargs)
        assert response.status_code == expect, response.text
        return response.json()["data"]

    def error(self, method: str, path: str, *, expect: int, **kwargs: Any) -> dict[str, Any]:
        """发请求、断言状态码并取出 error。"""
        response = self.request(method, path, **kwargs)
        assert response.status_code == expect, response.text
        return response.json()["error"]

    def save_profile(self, *, json: dict[str, Any], **kwargs: Any) -> Any:
        """Explicit convenience for tests unrelated to profile CAS/replay behavior."""
        current = self.data("GET", "/profile")
        return self.data(
            "PUT", "/profile", json={**json, "expected_revision": current["revision"]}, **kwargs
        )
