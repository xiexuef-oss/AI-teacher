"""Opt-in ORM runtime checks on a new isolated database created by migration tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from migration_runner import apply_migrations
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from test_mysql_migrations import mysql_engine  # noqa: F401, F811

from tutor_api.db import create_session_factory, make_engine, new_id
from tutor_api.models import StudentProfile, User


@pytest.fixture
def runtime(mysql_engine):  # noqa: F811
    engine = make_engine(mysql_engine.url)
    try:
        assert inspect(engine).get_table_names() == []  # make_engine never creates tables.
        apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
        yield engine, create_session_factory(engine)
    finally:
        engine.dispose()


def user(identifier=None, **changes):
    now = datetime(2026, 11, 15, 8, 1, 2, 123000, tzinfo=UTC)
    return User(
        id=identifier or new_id(),
        role="student",
        status="active",
        created_at=now,
        updated_at=now,
        **changes,
    )


def test_mysql_session_utc_charset_and_pool_checkout_reset(runtime):
    engine, _ = runtime
    assert engine.pool._pre_ping is True and engine.hide_parameters is True
    with engine.connect() as connection:
        assert connection.execute(text("SELECT @@session.time_zone")).scalar() == "+00:00"
        assert (
            connection.execute(text("SELECT @@session.character_set_connection")).scalar()
            == "utf8mb4"
        )
        connection.execute(text("SET SESSION time_zone='+08:00'"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT @@session.time_zone")).scalar() == "+00:00"
    assert not any(name.startswith("proto_") for name in inspect(engine).get_table_names())


def test_mysql_user_utc_millisecond_and_json_round_trip(runtime):
    _, factory = runtime
    moment = datetime(
        2026, 11, 15, 15, 30, 0, 123000, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    student = user(display_name="自编🔬")
    student.created_at = moment
    with factory() as db:
        db.add(student)
        db.flush()
        db.add(
            StudentProfile(
                user_id=student.id,
                subjects_json=["math", "自编🔬"],
                created_at=moment,
                updated_at=moment,
            )
        )
        db.commit()
    with factory() as db:
        result = db.get(User, student.id)
        assert result.display_name == "自编🔬"
        assert result.created_at == moment.astimezone(UTC)
        assert result.created_at.tzinfo == UTC
        assert db.get(StudentProfile, student.id).subjects_json == ["math", "自编🔬"]


def test_mysql_foreign_key_unique_and_transaction_rollback(runtime):
    _, factory = runtime
    student = user(email_hash="a" * 64)
    with factory() as db:
        db.add(student)
        db.commit()
    rejected = user(email_hash="a" * 64)
    with factory() as db:
        db.add(rejected)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.get(User, rejected.id) is None
        moment = datetime.now(UTC)
        db.add(StudentProfile(user_id=new_id(), created_at=moment, updated_at=moment))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        existing = db.get(User, student.id)
        existing.display_name = "rolled back"
        db.flush()
        db.rollback()
    with factory() as db:
        assert db.get(User, student.id).display_name is None


def test_mysql_for_update_serializes_concurrent_read_modify_write(runtime):
    _, factory = runtime
    student = user(display_name="0")
    with factory() as db:
        db.add(student)
        db.commit()
    for _ in range(2):
        barrier = Barrier(4)

        def increment(_, barrier=barrier):
            barrier.wait(timeout=5)
            with factory() as db:
                current = db.scalar(select(User).where(User.id == student.id).with_for_update())
                current.display_name = str(int(current.display_name) + 1)
                db.commit()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increment, range(4)))
    with factory() as db:
        assert db.get(User, student.id).display_name == "8"
