import pytest
from pydantic import ValidationError

from ai_gateway.config import Budgets
from support.gateway_fakes import ScriptedProvider, hint_ok, local_provider, make_request


@pytest.mark.parametrize(
    "field", ["student_daily_max_cost_micros", "platform_daily_max_cost_micros"]
)
def test_legacy_invoke_cannot_silently_ignore_configured_daily_cost_limits(make_gateway, field):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"m": local_provider()}, ["m"], {"m": adapter}, budgets={field: 0})
    response = h.gateway.invoke(make_request())
    assert response.error_code == "BUDGET_UNAVAILABLE"
    assert response.provider_calls == 0 and adapter.calls == []
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 0


@pytest.mark.parametrize("bad", [-1, True, 1.5, "3"])
def test_daily_cost_configuration_is_an_exact_nonnegative_integer(bad):
    with pytest.raises(ValidationError):
        Budgets(
            per_request_max_cost_micros=1,
            student_daily_requests=1,
            platform_daily_requests=1,
            student_daily_max_cost_micros=bad,
        )
