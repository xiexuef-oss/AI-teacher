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
from sqlalchemy.engine import URL, Dialect, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator, TypeEngine

from tutor_api.settings import REPO_ROOT, Settings


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


def make_engine(database_url: str | URL, *, settings: Settings | None = None) -> Engine:
    settings = settings or Settings()
    try:
        url = make_url(database_url)
    except Exception:
        raise ValueError("数据库URL格式无效") from None
    if url.drivername == "mysql+pymysql":
        try:
            engine = create_engine(
                url,
                connect_args={
                    "charset": "utf8mb4",
                    "connect_timeout": settings.database_connect_timeout_seconds,
                    "read_timeout": settings.database_read_timeout_seconds,
                    "write_timeout": settings.database_write_timeout_seconds,
                },
                pool_timeout=settings.database_pool_timeout_seconds,
                pool_pre_ping=True,
                hide_parameters=True,
            )
        except ModuleNotFoundError as error:
            if error.name == "pymysql":
                raise RuntimeError("MySQL需要可选驱动，请运行 uv sync --group mysql") from None
            raise

        @event.listens_for(engine, "checkout")
        def _configure_mysql(dbapi_connection: Any, _record: Any, _proxy: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SET SESSION time_zone = '+00:00'")
                cursor.execute(
                    f"SET SESSION innodb_lock_wait_timeout = {settings.database_lock_timeout_seconds}"
                )
                cursor.execute(
                    f"SET SESSION lock_wait_timeout = {settings.database_lock_timeout_seconds}"
                )
            except Exception:
                # Never return a connection whose session protection could not be restored.
                _record.invalidate()
                raise
            finally:
                cursor.close()

        return engine
    if url.get_backend_name() != "sqlite":
        raise NotImplementedError("仅支持SQLite原型与显式mysql+pymysql运行引擎；不自动迁移或建表")
    if url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=path.as_posix())
    pool_options = (
        {"pool_timeout": settings.database_pool_timeout_seconds}
        if url.database and url.database != ":memory:"
        else {}
    )
    engine = create_engine(
        url,
        connect_args={
            "check_same_thread": False,
            "timeout": settings.database_sqlite_busy_timeout_seconds,
        },
        hide_parameters=True,
        **pool_options,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
