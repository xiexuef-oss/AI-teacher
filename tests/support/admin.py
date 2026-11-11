"""内容审核相关测试的共用工具：造草稿、做决策、读审计、把详情还原成一次"修改"请求。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from support.seeds import qid
from tutor_api.models import AuditLog, Question, Solution

AUTHOR = str(uuid.uuid4())  # 一个"别的人"：既不是审核员，也不是学生
KEY = "math-mono-quadratic"  # 单选题，带地区测试标签
FAST_KEY = "phys-incline-accel"  # 填空题，标准解法与快速解法都有
OTHER_FAST_KEY = "chem-conservation-co2"  # 同样两种解法都有


def make_draft(db, key: str = KEY, *, created_by: str | None = AUTHOR) -> str:
    """把一道已发布的样题改回待审状态，模拟一份刚提交的草稿。"""
    question = db.get(Question, qid(key))
    question.status = "draft"
    question.published_at = None
    question.created_by = created_by
    question.reviewed_by = None
    for solution in db.scalars(select(Solution).where(Solution.question_id == question.id)):
        solution.reviewed = False
        solution.reviewed_by = None
    db.commit()
    return question.id


def decide(who, question_id: str, decision: str, *, version: int = 1, expect: int = 200, **extra):
    body = {"decision": decision, "expected_version": version, **extra}
    path = f"/admin/questions/{question_id}/review"
    if expect == 200:
        return who.data("POST", path, json=body)
    return who.error("POST", path, expect=expect, json=body)


def audit_rows(db, question_id: str) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.target_type == "question", AuditLog.target_id == question_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )


def edit_body(detail: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """把题目详情原样还原成一次"修改"请求；再用 overrides 改想改的地方。"""
    body: dict[str, Any] = {
        "expected_version": detail["version"],
        "title": detail["title"],
        "difficulty": detail["difficulty"],
        "grade": detail["grade"],
        "content": detail["content"],
        "answer": detail["answer"],
        "teaching": detail["teaching"],
        "solutions": [
            {
                key: solution[key]
                for key in ("kind", "steps", "final_answer", "key_points", "conditions", "boundary")
            }
            for solution in detail["solutions"]
        ],
        "knowledge": [node["code"] for node in detail["knowledge"]],
        "rubric": detail["rubric"],
    }
    body.update(overrides)
    return body


def edit(who, question_id: str, body: dict[str, Any], *, expect: int = 201, **kwargs: Any):
    path = f"/admin/questions/{question_id}/versions"
    if expect == 201:
        return who.data("POST", path, expect=201, json=body, **kwargs)
    return who.error("POST", path, expect=expect, json=body, **kwargs)
