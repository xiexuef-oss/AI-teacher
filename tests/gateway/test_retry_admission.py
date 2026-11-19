"""Backoff is a real gap: authorization and prices may change before retry."""

import pytest

from ai_gateway.budget import estimate_request_cost_micros
from support.gateway_fakes import (
    ScriptedProvider,
    external_provider,
    hint_ok,
    make_request,
    timeout,
)


@pytest.mark.parametrize("change", ["disabled", "approval", "model", "route", "price", "cap"])
def test_retry_rechecks_current_candidate_and_amount(make_gateway, monkeypatch, change):
    adapter = ScriptedProvider(timeout(), hint_ok())
    h = make_gateway({"x": external_provider()}, ["x"], {"x": adapter})
    estimate = estimate_request_cost_micros(
        h.gateway._config.providers["x"].pricing, make_request()
    )

    def backoff(seconds):
        provider = h.gateway._config.providers["x"]
        if change == "disabled":
            provider.enabled = False
        elif change == "approval":
            provider.compliance_approved = False
        elif change == "model":
            monkeypatch.setitem(h.gateway._env, "X_MODEL", "different-model")
        elif change == "route":
            h.gateway._config.routes[make_request().task_type].candidates.clear()
        elif change == "price":
            provider.pricing.input_per_1k_tokens_micros = 1_000_000
        else:
            h.gateway._config.budgets.per_request_max_cost_micros = 0

    h.gateway._sleep = backoff
    response = h.gateway.invoke(make_request())
    assert response.status == "degraded"
    assert response.error_code == (
        "BUDGET_EXCEEDED" if change in {"price", "cap"} else "MODEL_UNAVAILABLE"
    )
    assert response.provider_calls == 1
    assert len(adapter.calls) == 1
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 1
    assert h.budget.get_cost_micros("platform", "platform", h.clock.now().date()) == estimate
