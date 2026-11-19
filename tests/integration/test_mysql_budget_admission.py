from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from migration_runner import apply_migrations
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.gateway_io import DbBudgetStore
from tutor_api.models import ModelBudgetUsage


def test_mysql_cost_pair_concurrency_and_rollback(mysql_engine, monkeypatch):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine)
    store = DbBudgetStore(factory, lambda: datetime.now(UTC))
    day = datetime.now(UTC).date()
    barrier = Barrier(8)

    def record(index):
        barrier.wait(timeout=10)
        store.record_cost(f"student-{index}", day, cost_micros=3)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record, range(8)))
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 9
        assert sum(row.estimated_cost_micros for row in rows if row.scope == "student") == 24
        assert next(row for row in rows if row.scope == "platform").estimated_cost_micros == 24
        assert all(row.request_count == 0 for row in rows)
    original = factory.class_.execute
    calls = 0

    def fail_second(db, statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second cost write unavailable")
        return original(db, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(factory.class_, "execute", fail_second)
        with pytest.raises(RuntimeError, match="second cost write unavailable"):
            store.record_cost("rollback-student", day, cost_micros=99)
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 9
        assert next(row for row in rows if row.scope == "platform").estimated_cost_micros == 24


@pytest.mark.parametrize("limited", ["student", "platform"])
def test_mysql_eight_way_last_slot_and_no_partial_consumption(mysql_engine, limited):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    store = DbBudgetStore(sessionmaker(mysql_engine), lambda: datetime.now(UTC))
    day = datetime.now(UTC).date()
    barrier = Barrier(8)

    def consume(index):
        barrier.wait(timeout=5)
        return store.try_consume_request(
            "shared" if limited == "student" else f"student-{index}",
            day,
            student_limit=1 if limited == "student" else 100,
            platform_limit=1 if limited == "platform" else 100,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(8))) == 1
    assert store.get_requests("platform", "platform", day) == 1
    if limited == "platform":
        assert sum(store.get_requests("student", f"student-{i}", day) for i in range(8)) == 1
    else:
        assert not store.try_consume_request("shared", day, student_limit=1, platform_limit=100)
        assert store.get_requests("platform", "platform", day) == 1
