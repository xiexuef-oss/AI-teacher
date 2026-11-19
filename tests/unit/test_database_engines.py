from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

import tutor_api.db as database


def test_mysql_engine_options_and_checkout_force_utc(monkeypatch):
    seen, callbacks = {}, {}
    engine = SimpleNamespace()

    def construct(url, **kwargs):
        seen.update(kwargs)
        seen["driver"] = url.drivername
        return engine

    def listener(target, event_name):
        def register(callback):
            callbacks[event_name] = callback
            return callback

        return register

    monkeypatch.setattr(database, "create_engine", construct)
    monkeypatch.setattr(database.event, "listens_for", listener)
    assert (
        database.make_engine(
            "mysql+pymysql://fixture:private-password@127.0.0.1/test_db?charset=latin1"
        )
        is engine
    )
    assert seen["driver"] == "mysql+pymysql"
    assert seen["connect_args"]["charset"] == "utf8mb4"
    assert "check_same_thread" not in seen["connect_args"]
    assert seen["pool_pre_ping"] is True and seen["hide_parameters"] is True
    executed = []
    cursor = SimpleNamespace(execute=executed.append, close=lambda: executed.append("closed"))
    connection = SimpleNamespace(cursor=lambda: cursor)
    callbacks["checkout"](connection, None, None)
    assert executed == [
        "SET SESSION time_zone = '+00:00'",
        "SET SESSION innodb_lock_wait_timeout = 5",
        "SET SESSION lock_wait_timeout = 5",
        "closed",
    ]
    assert seen["connect_args"]["connect_timeout"] == 5
    assert seen["connect_args"]["read_timeout"] == 10
    assert seen["connect_args"]["write_timeout"] == 10
    assert seen["pool_timeout"] == 10
    invalidated = []

    def broken_execute(_sql):
        raise RuntimeError("session configuration failed")

    broken_cursor = SimpleNamespace(execute=broken_execute, close=lambda: None)
    with pytest.raises(RuntimeError, match="session configuration failed"):
        callbacks["checkout"](
            SimpleNamespace(cursor=lambda: broken_cursor),
            SimpleNamespace(invalidate=lambda: invalidated.append(True)),
            None,
        )
    assert invalidated == [True]


def test_missing_pymysql_has_actionable_redacted_error(monkeypatch):
    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named pymysql", name="pymysql")

    monkeypatch.setattr(database, "create_engine", missing)
    with pytest.raises(RuntimeError, match="uv sync --group mysql") as error:
        database.make_engine("mysql+pymysql://fixture:private-password@127.0.0.1/db")
    assert "private-password" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:private-password@localhost/db",
        "mysql://user:private-password@localhost/db",
    ],
)
def test_other_database_drivers_are_explicitly_rejected_without_secret(url):
    with pytest.raises(NotImplementedError) as error:
        database.make_engine(url)
    assert "private-password" not in str(error.value)


def test_sqlite_keeps_foreign_keys_and_does_not_implicitly_create_tables():
    engine = database.make_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert inspect(engine).get_table_names() == []
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
