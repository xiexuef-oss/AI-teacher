"""Legacy calls must retain conservative estimates even if the worker never finishes."""

import pytest

from ai_gateway import ProviderResult
from ai_gateway.budget import estimate_request_cost_micros
from support.gateway_fakes import (
    ScriptedProvider,
    external_provider,
    hint_ok,
    make_request,
    timeout,
)


class WorkerExit(BaseException):
    pass


def test_worker_exit_before_finish_still_keeps_estimate(make_gateway):
    class Exit:
        def invoke(self, **kwargs):
            raise WorkerExit()

    h = make_gateway({"x": external_provider()}, ["x"], {"x": Exit()})
    request = make_request()
    estimate = estimate_request_cost_micros(h.gateway._config.providers["x"].pricing, request)
    with pytest.raises(WorkerExit):
        h.gateway.invoke(request)
    for scope, key in (("student", request.student_pseudonym), ("platform", "platform")):
        assert h.budget.get_cost_micros(scope, key, h.clock.now().date()) == estimate


def test_cost_write_failure_blocks_send_without_exposing_storage_exception(make_gateway, caplog):
    provider = ScriptedProvider(hint_ok())
    h = make_gateway({"x": external_provider()}, ["x"], {"x": provider})

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE-DB-CONNECTION")

    h.budget.record_cost = fail
    response = h.gateway.invoke(make_request())
    assert response.status == "degraded" and response.error_code == "BUDGET_UNAVAILABLE"
    assert response.provider_calls == 0 and provider.calls == []
    assert "PRIVATE" not in caplog.text


def test_retry_after_utc_day_change_keeps_precharges_on_admission_day(make_gateway):
    class CrossDay(ScriptedProvider):
        def invoke(self, **kwargs):
            if not self.calls:
                h.clock.advance(24 * 3600)
            return super().invoke(**kwargs)

    provider = CrossDay(timeout(), hint_ok())
    h = make_gateway({"x": external_provider()}, ["x"], {"x": provider})
    request = make_request()
    day = h.clock.now().date()
    estimate = estimate_request_cost_micros(h.gateway._config.providers["x"].pricing, request)
    assert h.gateway.invoke(request).status == "ok"
    for scope, key in (("student", request.student_pseudonym), ("platform", "platform")):
        assert h.budget.get_cost_micros(scope, key, day) == 2 * estimate
        assert h.budget.get_cost_micros(scope, key, h.clock.now().date()) == 0


@pytest.mark.parametrize("attempts", [1, 2])
@pytest.mark.parametrize("reported_tokens", [None, 100_000])
def test_each_attempt_is_charged_before_send_and_finish_only_adds_difference(
    make_gateway, attempts, reported_tokens
):
    snapshots = []
    request = make_request()

    class Observe(ScriptedProvider):
        def invoke(self, **kwargs):
            snapshots.append(h.budget.get_cost_micros("platform", "platform", h.clock.now().date()))
            return super().invoke(**kwargs)

    result = ProviderResult(
        output=hint_ok(), input_tokens=reported_tokens, output_tokens=reported_tokens
    )
    provider = Observe(*([timeout()] * (attempts - 1)), result)
    h = make_gateway({"x": external_provider()}, ["x"], {"x": provider})
    estimate = estimate_request_cost_micros(h.gateway._config.providers["x"].pricing, request)
    response = h.gateway.invoke(request)
    assert response.status == "ok" and response.provider_calls == attempts
    assert snapshots == [estimate * i for i in range(1, attempts + 1)]
    for scope, key in (("student", request.student_pseudonym), ("platform", "platform")):
        assert h.budget.get_cost_micros(scope, key, h.clock.now().date()) == max(
            estimate * attempts, response.usage.estimated_cost_micros
        )


@pytest.mark.parametrize("change", ["pause", "disabled", "price", "cap", "daily_cap"])
def test_configuration_change_during_cost_commit_stops_send(make_gateway, change):
    provider = ScriptedProvider(hint_ok())
    h = make_gateway({"x": external_provider()}, ["x"], {"x": provider})
    original = h.budget.record_cost

    def charge(*args, **kwargs):
        original(*args, **kwargs)
        if change == "pause":
            h.gateway.bind_dispatch_guard(lambda: False)
        elif change == "disabled":
            h.gateway._config.providers["x"].enabled = False
        elif change == "price":
            h.gateway._config.providers["x"].pricing.input_per_1k_tokens_micros *= 2
        elif change == "cap":
            h.gateway._config.budgets.per_request_max_cost_micros = 0
        else:
            h.gateway._config.budgets.student_daily_max_cost_micros = 1

    h.budget.record_cost = charge
    request = make_request()
    estimate = estimate_request_cost_micros(h.gateway._config.providers["x"].pricing, request)
    response = h.gateway.invoke(request)
    assert response.status == "degraded" and response.provider_calls == 0
    assert provider.calls == []
    assert response.error_code == (
        "MODEL_UNAVAILABLE"
        if change == "disabled"
        else "BUDGET_UNAVAILABLE"
        if change == "daily_cap"
        else "BUDGET_EXCEEDED"
    )
    assert h.budget.get_cost_micros("platform", "platform", h.clock.now().date()) == estimate
