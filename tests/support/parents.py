"""家长周报测试的共用工具：邀请、绑定、撤销、取周报，以及"做一周的题"。"""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from support.api import ApiClient
from support.flows import CORRECT, WRONG, solve

# 五道不同的客观题：一周里每道做一次，就是五份独立作答（刚好够学情的最小样本数）
FIVE = [
    "math-mono-quadratic",
    "math-mono-judge",
    "math-ineq-min",
    "phys-newton2-force",
    "chem-conservation-co2",
]


def invite(student: ApiClient, **kwargs: Any) -> dict[str, Any]:
    return student.data("POST", "/me/parent-invites", expect=201, **kwargs)


def link(parent: ApiClient, code: str, **kwargs: Any) -> dict[str, Any]:
    return parent.data("POST", "/parents/links", expect=201, json={"code": code}, **kwargs)


def authorize(student: ApiClient, parent: ApiClient) -> dict[str, Any]:
    """学生生成邀请码，家长输入：建立授权，返回家长看到的那条绑定。"""
    return link(parent, invite(student)["code"])


def links_of(student: ApiClient) -> dict[str, Any]:
    return student.data("GET", "/me/parent-links")


def revoke(student: ApiClient, link_id: str, **kwargs: Any) -> dict[str, Any]:
    return student.data("POST", f"/me/parent-links/{link_id}/revoke", **kwargs)


def weekly(parent: ApiClient, student_id: str, **params: Any) -> dict[str, Any]:
    return parent.data("GET", f"/parents/students/{student_id}/weekly", params=params or None)


def do_week(student: ApiClient, correct: int, keys: list[str] | None = None) -> None:
    """按给定的题各做一份独立作答：前 `correct` 道答对，其余答错。"""
    keys = keys or FIVE
    for index, key in enumerate(keys):
        solve(student, key, CORRECT[key] if index < correct else WRONG[key])


def new_identity(raw: TestClient, role: str = "student") -> ApiClient:
    """在某个（可能用自定义设置另起的）应用里创建一个本地身份。"""
    identity = ApiClient(raw).data(
        "POST", "/dev/local-identities", expect=201, auth=False, key=False, params={"role": role}
    )
    return ApiClient(raw, token=identity["access_token"], user_id=identity["user_id"])


def z(moment: Any) -> str:
    """响应里的时间写法：UTC，以 Z 结尾。"""
    return moment.isoformat().replace("+00:00", "Z")
