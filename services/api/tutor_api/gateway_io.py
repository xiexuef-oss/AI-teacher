"""模型网关落库用的审计与预算存储，以及学生去标识化。

两者都用自己的短事务写库，与业务请求的事务分开。因此编排器在调用网关之前必须先结束
自己的数据库事务（见 orchestrator._rephrase）：既避免模型调用期间占着数据库，也避免
SQLite 上两个连接互相等锁。
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_gateway import AuditRecord
from tutor_api.db import new_id
from tutor_api.models import ModelBudgetUsage, ModelCallAudit


def pseudonym(secret: str, student_id: str) -> str:
    """发给模型网关和审计日志的学生标识：带密钥的摘要，反推不出真实用户 ID。"""
    digest = hmac.new(
        secret.encode("utf-8"), student_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"stu_{digest[:32]}"


class DbAuditSink:
    """每次网关调用一行 model_call_audits。记录里只有元数据。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, record: AuditRecord) -> None:
        with self._session_factory() as db:
            db.add(
                ModelCallAudit(
                    id=new_id(),
                    request_id=record.request_id,
                    trace_id=record.trace_id,
                    student_pseudonym=record.student_pseudonym,
                    task_type=record.task_type,
                    provider=record.provider,
                    model_id=record.model_id,
                    status=record.status,
                    error_code=record.error_code,
                    provider_calls=record.provider_calls,
                    latency_ms=record.latency_ms,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    image_units=record.image_units,
                    estimated_cost_micros=record.estimated_cost_micros,
                    schema_valid=record.schema_valid,
                    review_required=record.review_required,
                    created_at=record.created_at,
                )
            )
            db.commit()


class DbBudgetStore:
    """每学生每日、平台每日的模型用量（model_budget_usage）。"""

    def __init__(self, session_factory: sessionmaker[Session], now: Callable[[], datetime]) -> None:
        self._session_factory = session_factory
        self._now = now

    @staticmethod
    def _query(scope: str, key: str, day: date):
        return select(ModelBudgetUsage).where(
            ModelBudgetUsage.scope == scope,
            ModelBudgetUsage.scope_key == key,
            ModelBudgetUsage.usage_date == day,
        )

    def get_requests(self, scope: str, key: str, day: date) -> int:
        with self._session_factory() as db:
            row = db.scalar(self._query(scope, key, day))
            return row.request_count if row else 0

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None:
        with self._session_factory() as db:
            row = db.scalar(self._query(scope, key, day))
            if row is None:
                db.add(
                    ModelBudgetUsage(
                        id=new_id(),
                        scope=scope,
                        scope_key=key,
                        usage_date=day,
                        request_count=requests,
                        estimated_cost_micros=cost_micros,
                        updated_at=self._now(),
                    )
                )
            else:
                row.request_count += requests
                row.estimated_cost_micros += cost_micros
                row.updated_at = self._now()
            db.commit()
