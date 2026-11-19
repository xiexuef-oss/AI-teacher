"""模型网关落库用的审计与预算存储，以及学生去标识化。

两者都用自己的短事务写库，与业务请求的事务分开。因此编排器在调用网关之前必须先结束
自己的数据库事务（见 orchestrator._rephrase）：既避免模型调用期间占着数据库，也避免
SQLite 上两个连接互相等锁。
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import fields
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_gateway import AuditRecord
from ai_gateway.budget import PLATFORM_KEY, PLATFORM_SCOPE, STUDENT_SCOPE
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
                    **{field.name: getattr(record, field.name) for field in fields(AuditRecord)},
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

    def record_cost(self, student_key: str, day: date, *, cost_micros: int) -> None:
        if cost_micros < 0:
            raise ValueError("Cost must be nonnegative")
        with self._session_factory() as db:
            dialect = db.get_bind().dialect.name
            for scope, key in ((PLATFORM_SCOPE, PLATFORM_KEY), (STUDENT_SCOPE, student_key)):
                values = dict(
                    id=new_id(),
                    scope=scope,
                    scope_key=key,
                    usage_date=day,
                    request_count=0,
                    estimated_cost_micros=cost_micros,
                    updated_at=self._now(),
                )
                updates = dict(
                    estimated_cost_micros=ModelBudgetUsage.estimated_cost_micros + cost_micros,
                    updated_at=self._now(),
                )
                if dialect == "mysql":
                    statement = (
                        mysql_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_duplicate_key_update(**updates)
                    )
                elif dialect == "sqlite":
                    statement = (
                        sqlite_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_conflict_do_update(
                            index_elements=["scope", "scope_key", "usage_date"],
                            set_=updates,
                        )
                    )
                else:
                    raise RuntimeError("Unsupported atomic budget store")
                db.execute(statement)
            db.commit()

    def try_consume_request(
        self, student_key: str, day: date, *, student_limit: int, platform_limit: int
    ) -> bool:
        # All admissions acquire the shared platform row first. Upserts obtain a
        # write lock even for initial buckets; all checks/increments commit together.
        slots = (
            (PLATFORM_SCOPE, PLATFORM_KEY, platform_limit),
            (STUDENT_SCOPE, student_key, student_limit),
        )
        with self._session_factory() as db:
            rows = []
            dialect = db.get_bind().dialect.name
            for scope, key, limit in slots:
                values = dict(
                    id=new_id(),
                    scope=scope,
                    scope_key=key,
                    usage_date=day,
                    request_count=0,
                    estimated_cost_micros=0,
                    updated_at=self._now(),
                )
                if dialect == "mysql":
                    statement = (
                        mysql_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_duplicate_key_update(id=ModelBudgetUsage.id)
                    )
                elif dialect == "sqlite":
                    statement = (
                        sqlite_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["scope", "scope_key", "usage_date"])
                    )
                else:
                    raise RuntimeError("Unsupported atomic budget store")
                db.execute(statement)
                row = db.scalar(self._query(scope, key, day).with_for_update())
                if row.request_count >= limit:
                    db.rollback()
                    return False
                rows.append(row)
            for row in rows:
                row.request_count += 1
                row.updated_at = self._now()
            db.commit()
            return True

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None:
        with self._session_factory() as db:
            if db.get_bind().dialect.name == "mysql":
                statement = (
                    mysql_insert(ModelBudgetUsage)
                    .values(
                        id=new_id(),
                        scope=scope,
                        scope_key=key,
                        usage_date=day,
                        request_count=requests,
                        estimated_cost_micros=cost_micros,
                        updated_at=self._now(),
                    )
                    .on_duplicate_key_update(
                        request_count=ModelBudgetUsage.request_count + requests,
                        estimated_cost_micros=ModelBudgetUsage.estimated_cost_micros + cost_micros,
                        updated_at=self._now(),
                    )
                )
                db.execute(statement)
                db.commit()
                return
            increment = (
                update(ModelBudgetUsage)
                .where(
                    ModelBudgetUsage.scope == scope,
                    ModelBudgetUsage.scope_key == key,
                    ModelBudgetUsage.usage_date == day,
                )
                .values(
                    request_count=ModelBudgetUsage.request_count + requests,
                    estimated_cost_micros=ModelBudgetUsage.estimated_cost_micros + cost_micros,
                    updated_at=self._now(),
                )
            )
            if db.execute(increment).rowcount == 0:
                try:
                    with db.begin_nested():
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
                        db.flush()
                except IntegrityError:
                    # 同一scope/day的首行可能被另一事务抢先建立，回滚保存点后原子递增。
                    if db.execute(increment).rowcount != 1:
                        raise
            db.commit()
