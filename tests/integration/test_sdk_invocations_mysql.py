"""Standalone SDK persistence on explicit isolated MySQL, with scripted providers."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from migration_runner import apply_migrations
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_mysql_migrations import mysql_engine  # noqa: F401
from unit.test_sdk_attempt_chain import (
    test_next_attempt_cap_includes_prior_observed_overrun as verify_cap,
)
from unit.test_sdk_attempt_chain import (
    test_next_attempt_commits_fence_and_cost_but_not_second_request as verify_chain,
)
from unit.test_sdk_attempt_chain import (
    test_only_one_concurrent_continuation_wins as verify_concurrency,
)
from unit.test_sdk_attempt_chain import (
    test_sdk_retry_uses_separate_durable_attempts_and_audits as verify_sdk,
)
from unit.test_sdk_durable_invocations import NOW, gateway, request
from unit.test_sdk_resume import (
    test_known_failed_request_resumes_after_restart_without_resending_first_attempt as verify_resume,
)
from unit.test_sdk_resume import (
    test_two_restart_workers_only_dispatch_one_next_attempt as verify_resume_race,
)

from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_maintenance import report_invocations
from tutor_api.services.invocation_store import InvocationStore, intents


@pytest.fixture
def store(request):
    engine = request.getfixturevalue("mysql_engine")
    apply_migrations(engine, sorted(Path("migrations").glob("*.sql")))
    return InvocationStore(
        sessionmaker(engine),
        InvocationTransitions(Path("contracts/model_invocation.schema.json")),
        now=lambda: NOW,
    )


def test_real_sdk_same_key_concurrency_and_restart_are_single_send(store):
    sdk, adapter = gateway(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sdk.invoke(request()), range(2)))
    assert sum(result.status == "ok" for result in results) == 1
    restarted, _ = gateway(store, adapter)
    assert restarted.invoke(request()).error_code == "INVOCATION_ALREADY_SETTLED"
    assert len(adapter.calls) == 1
    with store.factory() as db:
        assert len(list(db.execute(select(intents)))) == 1
        assert len(db.scalars(select(ModelCallAudit)).all()) == 1
        buckets = db.scalars(select(ModelBudgetUsage)).all()
        assert len(buckets) == 2
        assert all(b.request_count == 1 and b.estimated_cost_micros > 0 for b in buckets)
    assert report_invocations(store)["items"][0]["context_kind"] == "sdk_request"


def test_real_sdk_same_transport_key_different_pseudonyms_have_distinct_intents(store):
    sdk, adapter = gateway(store)
    assert sdk.invoke(request()).status == "ok"
    assert (
        sdk.invoke(request().model_copy(update={"student_pseudonym": "stu_" + "b" * 32})).status
        == "ok"
    )
    assert len(adapter.calls) == 2
    with store.factory() as db:
        assert len(list(db.execute(select(intents)))) == 2
        assert len(db.scalars(select(ModelCallAudit)).all()) == 2
        rows = db.scalars(select(ModelBudgetUsage)).all()
        assert sorted(b.request_count for b in rows) == [1, 1, 2]


def test_real_sdk_attempt_chain(store):
    verify_chain(store)


def test_real_sdk_continuation_concurrency(store):
    verify_concurrency(store)


def test_real_sdk_cumulative_cap(store):
    verify_cap(store)


def test_real_sdk_retry_audits(store):
    verify_sdk(store)


def test_real_sdk_resumes_confirmed_failure(store):
    verify_resume(store)


def test_real_sdk_restart_workers_only_send_once(store):
    verify_resume_race(store)
