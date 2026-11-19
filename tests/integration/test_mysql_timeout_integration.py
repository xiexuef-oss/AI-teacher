"""Only explicitly authorized local fixture data; never use real student data."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL
from sqlalchemy.exc import OperationalError

from tutor_api.db import make_engine
from tutor_api.settings import Settings


@pytest.fixture
def timeout_engine():
    path = os.environ.get("TUTOR_MYSQL_TEST_CONFIG")
    if not path:
        pytest.skip("需要显式配置独立MySQL测试库")
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if (
        config.get("allow_test_writes") is not True
        or config.get("host") != "127.0.0.1"
        or not config.get("database", "").startswith("tutor_migration_")
    ):
        pytest.fail("仅允许显式授权的本机独立迁移测试库")
    engine = make_engine(
        URL.create(
            "mysql+pymysql",
            username=config["user"],
            password=config["password"],
            host=config["host"],
            port=config["port"],
            database=config["database"],
        ),
        settings=Settings(database_lock_timeout_seconds=1, database_read_timeout_seconds=3),
    )
    try:
        yield engine
    finally:
        engine.dispose()


def test_mysql_lock_wait_bounds_and_checkout_reset(timeout_engine):
    engine = timeout_engine
    table = "timeout_fixture_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {table} (id INT PRIMARY KEY, value INT) ENGINE=InnoDB"
        )
        connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1, 0)")
    try:
        with engine.connect() as holder, engine.connect() as waiter:
            for variable in ("innodb_lock_wait_timeout", "lock_wait_timeout"):
                assert waiter.exec_driver_sql(f"SELECT @@session.{variable}").scalar() == 1
            holder.exec_driver_sql(f"UPDATE {table} SET value=1 WHERE id=1")
            started = time.monotonic()
            with pytest.raises(OperationalError) as error:
                waiter.exec_driver_sql(f"UPDATE {table} SET value=2 WHERE id=1")
            assert error.value.orig.args[0] == 1205
            assert 0.5 <= time.monotonic() - started < 5
            holder.rollback()
            waiter.rollback()
            waiter.exec_driver_sql("SET SESSION innodb_lock_wait_timeout=60")
            waiter.exec_driver_sql("SET SESSION lock_wait_timeout=60")
        # All pooled connections must restore settings even after a caller changes them.
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert (
                    connection.exec_driver_sql("SELECT @@session.innodb_lock_wait_timeout").scalar()
                    == 1
                )
                assert (
                    connection.exec_driver_sql("SELECT @@session.lock_wait_timeout").scalar() == 1
                )
            assert first.exec_driver_sql(f"SELECT value FROM {table}").scalar() == 0
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE {table}")


def test_mysql_socket_read_timeout_interrupts_wait(timeout_engine):
    # A read timeout disconnects the socket; it does not cancel work on the server.
    with timeout_engine.connect() as connection:
        started = time.monotonic()
        with pytest.raises(OperationalError) as error:
            connection.exec_driver_sql("SELECT SLEEP(5)")
        assert error.value.connection_invalidated
        assert 2 <= time.monotonic() - started < 6
