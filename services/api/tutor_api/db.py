"""数据库基础设施。

本阶段（ADR-006）开发态用 SQLite 文件隔离演示状态，表由 ORM 直接创建；生产结构以
migrations/*.sql 为准，两者的列由 tests/migrations 对照。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator, TypeEngine

from tutor_api.settings import REPO_ROOT


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """库里存不带时区的 UTC（MySQL 为 DATETIME(3)），进出应用层一律是带 UTC 时区的 datetime。"""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=3))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("拒绝写入不带时区的时间；请使用 UTC 的 aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


def new_id() -> str:
    return str(uuid.uuid4())


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise NotImplementedError(
            "本阶段只支持 SQLite 原型库（ADR-006）。MySQL 的结构见 migrations/，"
            "接入前还需要替换本地身份 Mock 与幂等存储。"
        )
    if url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=path.as_posix())

    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
