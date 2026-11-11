"""做题流程的测试辅助：开会话、建作答、提交、教学下一步。"""

from __future__ import annotations

from typing import Any

from support.api import ApiClient
from support.seeds import qid


def choice(*keys: str) -> dict[str, Any]:
    return {"selected_options": list(keys)}


def blank(value: str, key: str = "b1") -> dict[str, Any]:
    return {"blanks": [{"key": key, "value": value}]}


# 每道样题的一个正确答案与一个确定错误的答案
CORRECT: dict[str, dict[str, Any]] = {
    "math-mono-quadratic": choice("B"),
    "math-mono-quadratic-v1": blank("(-∞,2]"),
    "math-mono-judge": choice("A", "C"),
    "math-ineq-min": blank("4"),
    "math-ineq-rect": choice("C"),
    "math-ineq-product-v1": blank("16"),
    "phys-incline-accel": blank("5 m/s²"),
    "phys-incline-accel-v1": blank("g sinθ"),
    "phys-newton2-force": choice("B"),
    "phys-force-analysis": choice("A", "B"),
    "phys-vt-displacement": blank("32"),
    "phys-tape-accel": choice("B"),
    "chem-conservation-co2": blank("4.4"),
    "chem-conservation-h2": choice("B"),
    "chem-charge-conservation": choice("C"),
    "chem-ion-inference": choice("B", "C"),
    "chem-lab-operation": choice("C"),
}
WRONG: dict[str, dict[str, Any]] = {
    "math-mono-quadratic": choice("A"),
    "math-mono-quadratic-v1": blank("[2,+∞)"),
    "math-mono-judge": choice("A", "B"),
    "math-ineq-min": blank("5"),
    "math-ineq-rect": choice("B"),
    "math-ineq-product-v1": blank("15"),
    "phys-incline-accel": blank("10 m/s²"),
    "phys-incline-accel-v1": blank("g cosθ"),
    "phys-newton2-force": choice("D"),
    "phys-force-analysis": choice("C", "D"),
    "phys-vt-displacement": blank("20"),
    "phys-tape-accel": choice("A"),
    "chem-conservation-co2": blank("44"),
    "chem-conservation-h2": choice("C"),
    "chem-charge-conservation": choice("B"),
    "chem-ion-inference": choice("A", "D"),
    "chem-lab-operation": choice("B"),
}


def start(student: ApiClient, key: str, origin: str = "practice", **extra: Any) -> dict[str, Any]:
    body = {"question_id": qid(key), "origin": origin, **extra}
    return student.data("POST", "/sessions", expect=201, json=body)


def new_attempt(student: ApiClient, session_id: str) -> dict[str, Any]:
    return student.data("POST", "/attempts", expect=201, json={"session_id": session_id})


def submit(
    student: ApiClient, attempt_id: str, answer: dict[str, Any], **kwargs: Any
) -> dict[str, Any]:
    return student.data("POST", f"/attempts/{attempt_id}/submit", json={"answer": answer}, **kwargs)


def begin(
    student: ApiClient, key: str, origin: str = "practice", **extra: Any
) -> tuple[dict, dict]:
    """开会话并建好第一份作答。"""
    session = start(student, key, origin, **extra)
    return session, new_attempt(student, session["id"])


def solve(
    student: ApiClient,
    key: str,
    answer: dict[str, Any] | None = None,
    origin: str = "practice",
    **extra: Any,
) -> tuple[dict, dict, dict]:
    """开会话、建作答、提交。默认提交正确答案。返回 (会话, 作答, 提交结果)。"""
    session, attempt = begin(student, key, origin, **extra)
    result = submit(student, attempt["id"], CORRECT[key] if answer is None else answer)
    return session, attempt, result


def tutor(student: ApiClient, session_id: str, action: str, **body: Any) -> dict[str, Any]:
    return student.data(
        "POST", f"/tutor/sessions/{session_id}/next", json={"action": action, **body}
    )


def tutor_error(
    student: ApiClient, session_id: str, action: str, *, expect: int, **body: Any
) -> dict[str, Any]:
    return student.error(
        "POST", f"/tutor/sessions/{session_id}/next", expect=expect, json={"action": action, **body}
    )


def events(student: ApiClient, session_id: str, **params: Any) -> list[dict[str, Any]]:
    return student.data("GET", f"/sessions/{session_id}/events", params=params or None)["items"]


def session_of(student: ApiClient, session_id: str) -> dict[str, Any]:
    return student.data("GET", f"/sessions/{session_id}")
