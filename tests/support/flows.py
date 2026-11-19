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
    "chem-process-reading": choice("B"),
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
    "chem-process-reading": choice("A"),
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


def parts(texts: dict[str, str]) -> dict[str, Any]:
    """解答题的作答：{小问键: 文字}。"""
    return {"parts": [{"key": key, "text": text} for key, text in texts.items()]}


# 每道解答题样题的一份作答（内容对不对不重要：解答题不自动评分）
WRITTEN: dict[str, dict[str, Any]] = {
    "math-quadratic-param-written": parts(
        {
            "1": "f(x)=(x-a)^2+3-a^2，对称轴 x=a，开口向上，所以 a≤1。",
            "2": "a=2 时 f(x)=(x-2)^2-1，最小值 -1，f(0)=3，f(3)=0，最大值 3。",
        }
    ),
    "phys-pull-friction-written": parts(
        {
            "1": "竖直方向 N+Fsin37°=mg，N=14 N。",
            "2": "f=μN=7 N，Fcos37°-f=ma，a=0.5 m/s²。",
        }
    ),
    "chem-ion-equation-written": parts(
        {
            "1": "CaCO3+2H+=Ca2++H2O+CO2↑",
            "2": "Ba2++2OH-+2H++SO42-=BaSO4↓+2H2O",
        }
    ),
}


def cells(*items: tuple[str, str, str, str]) -> dict[str, Any]:
    """实验题的作答：数据表里学生填的格子 (表键, 行键, 列键, 值)。"""
    return {
        "cells": [
            {"table": table, "row": row, "col": col, "value": value}
            for table, row, col, value in items
        ]
    }


# 每道实验题样题的一份作答：数据表里的数和文字（内容对不对不重要：实验题不自动评分）
EXPERIMENT: dict[str, dict[str, Any]] = {
    "phys-tape-experiment": {
        **cells(
            ("t1", "r1", "v", "0.400"),
            ("t1", "r2", "v", "0.600"),
            ("t1", "r3", "v", "0.800"),
            ("t1", "r4", "v", "1.00"),
            ("t2", "r1", "val", "2.00"),
        ),
        **parts({"1": "T 等于 0.10 秒", "2": "逐差法", "3": "摩擦；读数误差"}),
    },
    "phys-ohm-experiment": {
        **cells(
            ("t1", "r1", "r", "50.0"),
            ("t1", "r2", "r", "49.8"),
            ("t1", "r3", "r", "50.2"),
            ("t1", "r4", "r", "49.8"),
            ("t1", "r5", "r", "50.2"),
            ("t2", "r1", "val", "50.0"),
        ),
        **parts({"1": "内接", "2": "偏大，因为电压表测到了电流表两端的电压"}),
    },
    "chem-titration-experiment": {
        **cells(
            ("t1", "r1", "dv", "20.05"),
            ("t1", "r2", "dv", "20.10"),
            ("t1", "r3", "dv", "20.09"),
            ("t2", "r1", "val", "20.08"),
            ("t2", "r2", "val", "0.1004"),
        ),
        **parts({"1": "无色变浅红色，半分钟不褪色", "2": "偏高"}),
    },
}


def steps(*items: tuple[str, str]) -> dict[str, Any]:
    """证明题的作答：一步一项 (这一步写了什么, 依据)，列表的顺序就是证明的顺序。"""
    return {"steps": [{"text": text, "reason": reason} for text, reason in items]}


# 每道证明题样题的一份作答（内容对不对不重要：证明题不自动评分）
PROOF: dict[str, dict[str, Any]] = {
    "math-circle-radius-proof": steps(("我按给定圆方程比较了两条线段。", "两点间距离公式")),
    "math-triangle-coordinate-proof": {
        "steps": [{"text": "我按给定坐标比较了各条线段。", "reason": "两点间距离公式"}]
    },
    "math-ineq-diff-proof": steps(
        ("因为 a>0，b>0，所以 ab>0。", "已知"),
        ("a/b+b/a-2=(a-b)^2/(ab)", "通分，完全平方公式"),
        ("(a-b)^2≥0，ab>0，所以差≥0，即 a/b+b/a≥2；等号当且仅当 a=b。", "平方非负"),
    ),
    "math-mono-def-proof": steps(
        ("任取 x1<x2，都在 [1,+∞) 内。", "单调性的定义"),
        ("f(x1)-f(x2)=(x1-x2)(x1x2-1)/(x1x2)", "作差，通分"),
        ("x1-x2<0，x1x2>1，所以 f(x1)<f(x2)，f 在 [1,+∞) 上递增。", "符号法则"),
    ),
    "math-ineq-mul-proof": steps(
        ("b>0，c>0。", "已知"),
        ("ac>bc", "同乘正数 c"),
        ("bc>bd", "同乘正数 b"),
        ("所以 ac>bd。", "传递性"),
    ),
    "phys-work-energy-proof": steps(
        ("合力就是 F。", "受力分析，水平面光滑"),
        ("a=F/m，匀加速。", "牛顿第二定律"),
        ("v2²-v1²=2as，代入得 Fs=½mv2²-½mv1²。", "匀变速直线运动的速度位移公式"),
    ),
}

# 一页、一笔的最小手写稿
INK: dict[str, Any] = {
    "version": 1,
    "pages": [
        {
            "width": 800,
            "height": 600,
            "strokes": [
                {
                    "color": "#1A1A1A",
                    "width": 3.0,
                    "points": [10, 10, 0, 0.5, 20, 25, 16, 0.6, 40, 30, 33, 0.5],
                }
            ],
        }
    ],
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
