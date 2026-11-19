from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from test_model_cost_gate import stores as stores

from support.cost_cases import record
from tutor_api.models import ModelBudgetUsage
from tutor_api.services.invocation_store import InvocationBudgetExceeded


def send(store, value, **limits):
    store.prepare(value)
    return store.dispatch(
        value["invocation_id"],
        value["actor_digest"],
        expected_fence=1,
        attempt_id=value["invocation_id"],
        estimated_cost_micros=3,
        request_cost_cap=10,
        student_limit=100,
        platform_limit=100,
        **limits,
    )


@pytest.mark.parametrize("scope", ["student", "platform"])
def test_exact_daily_cap_is_allowed_and_next_attempt_rolls_back(request, scope):
    make, factory = request.getfixturevalue("stores")
    store = make("record_only")
    limits = {f"{scope}_cost_limit": 3}
    assert send(store, record(), **limits)["state"] == "dispatch_unknown"
    with pytest.raises(InvocationBudgetExceeded, match="cost"):
        send(store, record("f"), **limits)
    assert store.read("f" * 32, "b" * 64)["state"] == "prepared"
    with factory() as db:
        rows = list(db.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert all(row.request_count == 1 and row.estimated_cost_micros == 3 for row in rows)


def test_student_cost_denial_rolls_back_platform_increment_too(request):
    make, factory = request.getfixturevalue("stores")
    store = make()
    with pytest.raises(InvocationBudgetExceeded, match="cost"):
        send(store, record(), student_cost_limit=2, platform_cost_limit=100)
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
    assert store.read("a" * 32, "b" * 64)["state"] == "prepared"


def test_unknown_attempt_retains_cost_and_new_utc_day_uses_a_new_bucket(request):
    make, factory = request.getfixturevalue("stores")
    store = make()
    limits = dict(student_cost_limit=3, platform_cost_limit=3)
    send(store, record(), **limits)
    store.mark_unknown("a" * 32, "b" * 64, expected_fence=1)
    with pytest.raises(InvocationBudgetExceeded):
        send(store, record("e"), **limits)
    tomorrow = make()
    tomorrow.now = lambda: datetime(2026, 11, 18, tzinfo=UTC)
    assert send(tomorrow, record("f"), **limits)["quota_day"] == "2026-11-18"
    with factory() as db:
        assert len(list(db.scalars(select(ModelBudgetUsage)))) == 4
        assert all(row.estimated_cost_micros == 3 for row in db.scalars(select(ModelBudgetUsage)))


@pytest.mark.parametrize("bad", [-1, True, 1.5, "3"])
def test_invalid_daily_cap_is_rejected_without_changing_intent(request, bad):
    make, factory = request.getfixturevalue("stores")
    store = make()
    with pytest.raises(ValueError):
        send(store, record(), student_cost_limit=bad)
    assert store.read("a" * 32, "b" * 64)["state"] == "prepared"
    with factory() as db:
        assert list(db.scalars(select(ModelBudgetUsage))) == []
