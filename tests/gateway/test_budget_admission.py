from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ai_gateway import GatewayConfig, InMemoryBudgetStore, build_gateway
from ai_gateway.budget import estimate_request_cost_micros
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    timeout,
)


def test_retry_does_not_exceed_cumulative_request_estimate(make_gateway):
    adapter = ScriptedProvider(timeout(), hint_ok())
    provider = external_provider()
    request = make_request()
    from ai_gateway.config import Pricing

    cap = estimate_request_cost_micros(Pricing.model_validate(provider["pricing"]), request)
    harness = make_gateway(
        {"x": provider},
        ["x"],
        {"x": adapter},
        budgets={"per_request_max_cost_micros": cap},
    )
    result = harness.gateway.invoke(request)
    assert len(adapter.calls) == 1
    assert result.status == "degraded"
    assert result.error_code == "BUDGET_EXCEEDED"
    assert harness.budget.get_cost_micros("platform", "platform", harness.clock.now().date()) == cap


@pytest.mark.parametrize("budget_attempts", [1, 2])
def test_fallback_shares_estimate_and_next_invocation_starts_fresh(make_gateway, budget_attempts):
    from ai_gateway.config import Pricing

    provider = external_provider()
    request = make_request(privacy_policy={"allow_cross_provider_fallback": True})
    cap = estimate_request_cost_micros(Pricing.model_validate(provider["pricing"]), request)
    first = ScriptedProvider(timeout())
    second = ScriptedProvider(hint_ok())
    harness = make_gateway(
        {"x": provider, "y": provider},
        ["x", "y"],
        {"x": first, "y": second},
        defaults={"max_retries": 0},
        budgets={"per_request_max_cost_micros": cap * budget_attempts},
    )
    result = harness.gateway.invoke(request)
    assert len(first.calls) == 1
    assert len(second.calls) == budget_attempts - 1
    assert result.status == ("ok" if budget_attempts == 2 else "degraded")
    first.script = [hint_ok()]
    assert harness.gateway.invoke(request).status == "ok"


def test_retry_allowed_when_two_attempt_estimates_fit(make_gateway):
    from ai_gateway.config import Pricing

    provider = external_provider()
    request = make_request()
    cap = estimate_request_cost_micros(Pricing.model_validate(provider["pricing"]), request)
    adapter = ScriptedProvider(timeout(), hint_ok())
    harness = make_gateway(
        {"x": provider},
        ["x"],
        {"x": adapter},
        budgets={"per_request_max_cost_micros": cap * 2},
    )
    assert harness.gateway.invoke(request).status == "ok"
    assert len(adapter.calls) == 2


@pytest.mark.parametrize("succeeds", [False, True])
def test_daily_estimate_retains_unknown_first_attempt(make_gateway, succeeds):
    from ai_gateway.config import Pricing

    provider = external_provider()
    request = make_request()
    estimate = estimate_request_cost_micros(Pricing.model_validate(provider["pricing"]), request)
    adapter = ScriptedProvider(timeout(), hint_ok() if succeeds else timeout())
    harness = make_gateway({"x": provider}, ["x"], {"x": adapter})
    response = harness.gateway.invoke(request)
    assert len(adapter.calls) == 2
    day = harness.clock.now().date()
    assert harness.budget.get_cost_micros("student", request.student_pseudonym, day) >= 2 * estimate
    assert harness.budget.get_cost_micros("platform", "platform", day) >= 2 * estimate
    if not succeeds:
        assert response.usage.input_tokens is None
        assert response.usage.output_tokens is None


class StaleReads(InMemoryBudgetStore):
    """Force all old read-then-call operations to observe the same remaining slot."""

    def __init__(self, parties):
        super().__init__()
        self.barrier = Barrier(parties)

    def get_requests(self, scope, key, day):
        result = super().get_requests(scope, key, day)
        self.barrier.wait(timeout=5)
        return result


@pytest.mark.parametrize("limited", ["student", "platform"])
def test_only_one_of_eight_concurrent_calls_can_take_last_daily_slot(make_gateway, limited):
    adapter = ScriptedProvider(hint_ok())
    harness = make_gateway(
        {"m": local_provider()},
        ["m"],
        {"m": adapter},
        budgets={
            "student_daily_requests": 1 if limited == "student" else 100,
            "platform_daily_requests": 1 if limited == "platform" else 100,
        },
    )
    harness.gateway._budget_store = StaleReads(8)

    def invoke(index):
        return harness.gateway.invoke(
            make_request(
                request_id=f"parallel-{index}",
                student_pseudonym="same-student" if limited == "student" else f"student-{index}",
            )
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invoke, range(8)))
    assert len(adapter.calls) == 1
    assert sum(result.status == "ok" for result in results) == 1
    assert sum(result.error_code == "BUDGET_EXCEEDED" for result in results) == 7


def test_admission_store_failure_never_calls_provider(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    harness = make_gateway({"m": local_provider()}, ["m"], {"m": adapter})

    class Unavailable(InMemoryBudgetStore):
        def try_consume_request(self, *args, **kwargs):
            raise RuntimeError("private storage detail")

    harness.gateway._budget_store = Unavailable()
    result = harness.gateway.invoke(make_request())
    assert result.error_code == "BUDGET_UNAVAILABLE"
    assert adapter.calls == []
    assert "private storage detail" not in result.model_dump_json()


def test_explicit_falsey_budget_store_is_not_replaced_by_in_memory_default():
    class Denied(InMemoryBudgetStore):
        def __bool__(self):
            return False

        def try_consume_request(self, *args, **kwargs):
            return False

    adapter = ScriptedProvider(hint_ok())
    gateway = build_gateway(
        GatewayConfig.model_validate(config_dict({"m": local_provider()}, ["m"])),
        env={},
        environment="local",
        allow_external_calls=False,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        budget_store=Denied(),
        adapter_overrides={"m": adapter},
    )
    assert gateway.invoke(make_request()).error_code == "BUDGET_EXCEEDED"
    assert adapter.calls == []


def test_quota_is_kept_on_admission_utc_day_when_call_crosses_midnight(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    harness = make_gateway({"m": local_provider()}, ["m"], {"m": adapter})
    day = harness.clock.now().date()
    original = adapter.invoke

    def invoke(**kwargs):
        harness.clock.advance(24 * 3600)
        return original(**kwargs)

    adapter.invoke = invoke
    request = make_request()
    assert harness.gateway.invoke(request).status == "ok"
    assert harness.budget.get_requests("student", request.student_pseudonym, day) == 1
    assert (
        harness.budget.get_requests(
            "student", request.student_pseudonym, harness.clock.now().date()
        )
        == 0
    )
