from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_gateway import InMemoryBudgetStore
from tutor_api.gateway_io import DbBudgetStore
from tutor_api.models import ModelBudgetUsage


@pytest.fixture(params=["memory", "sqlite"])
def budget(request, tmp_path):
    if request.param == "memory":
        yield InMemoryBudgetStore()
    else:
        engine = create_engine("sqlite:///" + str(tmp_path / "budget.db"))
        ModelBudgetUsage.__table__.create(engine)
        yield DbBudgetStore(sessionmaker(engine), lambda: datetime.now(UTC))
        engine.dispose()


@pytest.mark.parametrize("exhausted", ["student", "platform"])
def test_denied_scope_does_not_consume_other_scope(budget, exhausted):
    day = datetime.now(UTC).date()
    key = "student-key" if exhausted == "student" else "platform"
    budget.add(exhausted, key, day, requests=1, cost_micros=0)
    assert not budget.try_consume_request("student-key", day, student_limit=1, platform_limit=1)
    other_scope, other_key = (
        ("platform", "platform") if exhausted == "student" else ("student", "student-key")
    )
    assert budget.get_requests(other_scope, other_key, day) == 0


@pytest.mark.parametrize("scope", ["student", "platform"])
def test_atomic_eight_way_admission(budget, scope):
    day = datetime.now(UTC).date()
    barrier = Barrier(8)

    def consume(index):
        barrier.wait(timeout=5)
        return budget.try_consume_request(
            "shared" if scope == "student" else f"student-{index}",
            day,
            student_limit=1 if scope == "student" else 100,
            platform_limit=1 if scope == "platform" else 100,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(consume, range(8)))
    assert sum(admitted) == 1
    assert budget.get_requests("platform", "platform", day) == 1


def test_commit_failure_rolls_back_both_buckets(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "rollback.db"))
    ModelBudgetUsage.__table__.create(engine)
    factory = sessionmaker(engine)
    store = DbBudgetStore(factory, lambda: datetime.now(UTC))
    day = datetime.now(UTC).date()

    def fail_commit(db):
        db.flush()
        raise RuntimeError("commit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(factory.class_, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit unavailable"):
            store.try_consume_request("student", day, student_limit=1, platform_limit=1)
    assert store.get_requests("platform", "platform", day) == 0
    assert store.get_requests("student", "student", day) == 0
    engine.dispose()


def test_cost_pair_failure_rolls_back_first_write(tmp_path, monkeypatch):
    from sqlalchemy import select

    engine = create_engine("sqlite:///" + str(tmp_path / "cost.db"))
    ModelBudgetUsage.__table__.create(engine)
    factory = sessionmaker(engine)
    store = DbBudgetStore(factory, lambda: datetime.now(UTC))
    day = datetime.now(UTC).date()
    original = factory.class_.execute
    writes = 0

    def fail_second(db, statement, *args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("second bucket unavailable")
        return original(db, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(factory.class_, "execute", fail_second)
        with pytest.raises(RuntimeError, match="second bucket unavailable"):
            store.record_cost("student", day, cost_micros=12)
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
    store.record_cost("student", day, cost_micros=12)
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert all(row.estimated_cost_micros == 12 and row.request_count == 0 for row in rows)
    engine.dispose()
