"""联调里直接调后端的小客户端：给学生造数据用（比在界面上点几十下快，也稳）。

只用标准库。每个会改变状态的请求带一个新的 Idempotency-Key，和真实客户端的规矩一致。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from e2e import data
from e2e.servers import API_URL


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status


class Api:
    def __init__(self, token: str, base: str = API_URL) -> None:
        self._token = token
        self._base = base

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        if method != "GET":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        request = urllib.request.Request(
            self._base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["data"]
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, error.read().decode("utf-8", "replace")) from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body or {})


def seed_attempt(api: Api, key: str, answer: dict[str, Any]) -> dict[str, Any]:
    """开会话、建作答、提交：造一份已提交的作答。返回提交结果。"""
    session = api.post("/sessions", {"question_id": data.question_id(key), "origin": "practice"})
    attempt = api.post("/attempts", {"session_id": session["id"]})
    return api.post(f"/attempts/{attempt['id']}/submit", {"answer": answer})
