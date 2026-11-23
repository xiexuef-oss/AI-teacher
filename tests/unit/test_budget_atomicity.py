from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select

from tutor_api.gateway_io import DbBudgetStore
from tutor_api.models import ModelBudgetUsage


def test_research_budget_does_not_share_student_or_platform_buckets(app, client, clock):
    factory = app.state.session_factory
    learning = DbBudgetStore(factory, clock.now)
    research = DbBudgetStore(factory, clock.now, namespace="content_factory")
    day = clock.now().date()
    key = "same-actor"
    caps = {"student_limit": 1, "platform_limit": 1}
    assert research.try_consume_request(key, day, **caps)
    assert not research.try_consume_request("another-actor", day, **caps)
    assert learning.get_requests("platform", "platform", day) == 0
    assert learning.get_requests("student", key, day) == 0
    assert learning.try_consume_request(key, day, **caps)
    research.record_cost(key, day, cost_micros=13)
    research.add("student", key, day, requests=1, cost_micros=7)
    assert learning.get_requests("student", key, day) == 1
    assert research.get_requests("student", key, day) == 2
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage).where(ModelBudgetUsage.usage_date == day)))
        assert sorted(row.estimated_cost_micros for row in rows) == [0, 0, 13, 20]


def test_concurrent_budget_updates_do_not_lose_requests_or_cost(app, client, clock, monkeypatch):
    factory = app.state.session_factory
    store = DbBudgetStore(factory, clock.now)
    day = clock.now().date()
    store.add("student", "atomic-test", day, requests=1, cost_micros=10)
    barrier = Barrier(4)
    original = factory.class_.scalar

    def concurrent_read(db, statement, *args, **kwargs):
        result = original(db, statement, *args, **kwargs)
        if isinstance(result, ModelBudgetUsage):
            barrier.wait(timeout=5)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(factory.class_, "scalar", concurrent_read)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda _: store.add("student", "atomic-test", day, requests=1, cost_micros=10),
                    range(4),
                )
            )
    with factory() as db:
        row = db.scalar(select(ModelBudgetUsage).where(ModelBudgetUsage.scope_key == "atomic-test"))
        assert row.request_count == 5
        assert row.estimated_cost_micros == 50


def test_first_concurrent_budget_usage_creates_one_row(app, client, clock):
    factory = app.state.session_factory
    store = DbBudgetStore(factory, clock.now)
    day = clock.now().date()
    start = Barrier(8)

    def add(_):
        start.wait(timeout=5)
        store.add("student", "first-usage", day, requests=1, cost_micros=3)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(8)))
    with factory() as db:
        rows = list(
            db.scalars(select(ModelBudgetUsage).where(ModelBudgetUsage.scope_key == "first-usage"))
        )
        assert len(rows) == 1
        assert rows[0].request_count == 8
        assert rows[0].estimated_cost_micros == 24
