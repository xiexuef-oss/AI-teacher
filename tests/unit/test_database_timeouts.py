import time

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, TimeoutError

from tutor_api.db import make_engine
from tutor_api.settings import Settings


@pytest.mark.parametrize(
    "field",
    [
        "database_connect_timeout_seconds",
        "database_read_timeout_seconds",
        "database_write_timeout_seconds",
        "database_pool_timeout_seconds",
        "database_lock_timeout_seconds",
        "database_sqlite_busy_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), 121])
def test_database_timeouts_reject_unbounded_values(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_sqlite_lock_wait_is_configured_and_bounded(tmp_path):
    engine = make_engine(
        "sqlite:///" + str(tmp_path / "locked.sqlite"),
        settings=Settings(database_sqlite_busy_timeout_seconds=0.05),
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE bounded (id INTEGER)")
        with engine.connect() as holder, engine.connect() as waiter:
            assert waiter.exec_driver_sql("PRAGMA busy_timeout").scalar() == 50
            holder.exec_driver_sql("INSERT INTO bounded VALUES (1)")
            started = time.monotonic()
            with pytest.raises(OperationalError, match="locked"):
                waiter.exec_driver_sql("INSERT INTO bounded VALUES (2)")
            assert 0.03 <= time.monotonic() - started < 2
            holder.rollback()
            waiter.rollback()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM bounded").scalar() == 0
    finally:
        engine.dispose()


def test_pool_exhaustion_has_bounded_wait(tmp_path):
    engine = make_engine(
        "sqlite:///" + str(tmp_path / "pool.sqlite"),
        settings=Settings(database_pool_timeout_seconds=0.05),
    )
    connections = []
    try:
        # SQLAlchemy default QueuePool: five persistent plus ten overflow connections.
        connections = [engine.connect() for _ in range(15)]
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            engine.connect()
        assert 0.03 <= time.monotonic() - started < 2
    finally:
        for connection in connections:
            connection.close()
        engine.dispose()


def test_timeout_environment_configuration(monkeypatch):
    monkeypatch.setenv("TUTOR_DATABASE_CONNECT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("TUTOR_DATABASE_READ_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("TUTOR_DATABASE_WRITE_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("TUTOR_DATABASE_LOCK_TIMEOUT_SECONDS", "6")
    settings = Settings()
    assert settings.database_connect_timeout_seconds == 2
    assert settings.database_read_timeout_seconds == 3
    assert settings.database_write_timeout_seconds == 4
    assert settings.database_lock_timeout_seconds == 6


@pytest.mark.parametrize("value", [True, False, 1.5, 2.0])
def test_lock_timeout_rejects_non_integer_settings(value):
    with pytest.raises(ValidationError):
        Settings(database_lock_timeout_seconds=value)


def test_mysql_url_query_cannot_disable_socket_timeouts():
    pytest.importorskip("pymysql")
    from sqlalchemy import event

    engine = make_engine(
        "mysql+pymysql://fixture@127.0.0.1/test_db"
        "?connect_timeout=0&read_timeout=0&write_timeout=0",
        settings=Settings(
            database_connect_timeout_seconds=2,
            database_read_timeout_seconds=3,
            database_write_timeout_seconds=4,
        ),
    )
    seen = {}

    @event.listens_for(engine, "do_connect")
    def capture(_dialect, _record, _args, params):
        seen.update(params)
        raise RuntimeError("stop before network access")

    try:
        with pytest.raises(RuntimeError, match="stop before network access"):
            engine.connect()
        assert seen["connect_timeout"] == 2
        assert seen["read_timeout"] == 3
        assert seen["write_timeout"] == 4
    finally:
        engine.dispose()
