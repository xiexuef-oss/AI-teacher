from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from migration_runner import apply_migrations
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_mysql_migrations import mysql_engine  # noqa: F401

from ai_gateway.invocation_state import InvocationTransitions
from support.cost_cases import audit, record
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_store import InvocationBudgetExceeded, InvocationStore, intents


def test_mysql_concurrent_overrun_settlement_and_shared_pause(mysql_engine):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine)
    rules = InvocationTransitions(Path("contracts/model_invocation.schema.json"))

    def make(policy):
        return InvocationStore(
            factory, rules, now=lambda: datetime(2026, 11, 17, tzinfo=UTC), overrun_policy=policy
        )

    store = make("pause_platform")
    value = record()
    store.prepare(value)
    options = dict(
        expected_fence=1,
        attempt_id="c" * 32,
        estimated_cost_micros=3,
        request_cost_cap=10,
        student_limit=100,
        platform_limit=100,
    )
    store.dispatch(value["invocation_id"], value["actor_digest"], **options)
    barrier = Barrier(8)
    observed = audit()

    def settle(_):
        barrier.wait(timeout=10)
        return make("pause_platform").settle_metadata(
            value["invocation_id"],
            value["actor_digest"],
            expected_fence=1,
            attempt_id="c" * 32,
            audit=observed,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(r["state"] == "settled_metadata" for r in pool.map(settle, range(8)))
    assert len(store.cost_gate.report()["incidents"]) == 1
    barrier = Barrier(8)

    def dispatch(index):
        next_store = make("record_only")
        item = record(str(index))
        next_store.prepare(item)
        barrier.wait(timeout=10)
        try:
            next_store.dispatch(
                item["invocation_id"],
                item["actor_digest"],
                **dict(options, attempt_id=f"{index:032x}"),
            )
            return True
        except InvocationBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(dispatch, range(8))) == [False] * 8
    with factory() as db:
        assert len(list(db.scalars(select(ModelCallAudit)))) == 1
        assert all(
            b.request_count == 1 and b.estimated_cost_micros == 5
            for b in db.scalars(select(ModelBudgetUsage))
        )
    store.cost_gate.resume("c" * 32, reason="provider_usage_verified")
    barrier = Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(dispatch, range(8))) == [True] * 8
    with factory() as db:
        assert all(
            b.request_count == 9 and b.estimated_cost_micros == 29
            for b in db.scalars(select(ModelBudgetUsage))
        )


@pytest.mark.parametrize("scope", ["student", "platform"])
def test_mysql_concurrent_daily_amount_has_only_one_admission(mysql_engine, scope):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine)
    store = InvocationStore(
        factory,
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
        now=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )
    ready = Barrier(8)

    def attempt(index):
        value = record(str(index))
        store.prepare(value)
        ready.wait(timeout=10)
        try:
            store.dispatch(
                value["invocation_id"],
                value["actor_digest"],
                expected_fence=1,
                attempt_id=value["invocation_id"],
                estimated_cost_micros=3,
                request_cost_cap=10,
                student_limit=100,
                platform_limit=100,
                **{f"{scope}_cost_limit": 3},
            )
            return True
        except InvocationBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert all(row.request_count == 1 and row.estimated_cost_micros == 3 for row in rows)
        assert list(db.scalars(select(intents.c.state))).count("dispatch_unknown") == 1
        assert list(db.scalars(select(intents.c.state))).count("prepared") == 7
        assert list(db.scalars(select(ModelCallAudit))) == []
