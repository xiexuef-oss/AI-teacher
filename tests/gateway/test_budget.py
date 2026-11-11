"""成本预算：单请求上限、学生日额度、平台日额度（docs/10：成本控制）。"""

from __future__ import annotations

from ai_gateway import CostBudget, ProviderResult
from support.gateway_fakes import (
    ScriptedProvider,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
)

EXPENSIVE = {
    "input_per_1k_tokens_micros": 50_000_000,
    "output_per_1k_tokens_micros": 50_000_000,
    "image_unit_micros": 50_000_000,
}


def _mock_only(make_gateway, **budgets):
    m = ScriptedProvider(hint_ok())
    return make_gateway({"m": local_provider()}, ["m"], {"m": m}, budgets=budgets), m


def test_student_daily_quota_degrades_without_calling_any_provider(make_gateway):
    h, m = _mock_only(make_gateway, student_daily_requests=2)

    responses = [h.gateway.invoke(make_request(request_id=f"r{i}")) for i in range(3)]

    assert [r.status for r in responses] == ["ok", "ok", "degraded"]
    assert responses[2].error_code == "BUDGET_EXCEEDED"
    assert responses[2].validated_output is None
    assert len(m.calls) == 2


def test_student_quota_is_tracked_per_student(make_gateway):
    h, _ = _mock_only(make_gateway, student_daily_requests=1)
    h.gateway.invoke(make_request(request_id="r1", student_pseudonym="stu_a"))

    exhausted = h.gateway.invoke(make_request(request_id="r2", student_pseudonym="stu_a"))
    other = h.gateway.invoke(make_request(request_id="r3", student_pseudonym="stu_b"))

    assert exhausted.error_code == "BUDGET_EXCEEDED"
    assert other.status == "ok"


def test_platform_daily_quota_applies_across_students(make_gateway):
    h, m = _mock_only(make_gateway, platform_daily_requests=2)

    responses = [
        h.gateway.invoke(make_request(request_id=f"r{i}", student_pseudonym=f"stu_{i}"))
        for i in range(3)
    ]

    assert [r.status for r in responses] == ["ok", "ok", "degraded"]
    assert responses[2].error_code == "BUDGET_EXCEEDED"
    assert len(m.calls) == 2


def test_daily_quota_resets_on_the_next_utc_day(make_gateway):
    h, _ = _mock_only(make_gateway, student_daily_requests=1)
    h.gateway.invoke(make_request(request_id="r1"))
    assert h.gateway.invoke(make_request(request_id="r2")).error_code == "BUDGET_EXCEEDED"

    h.clock.advance(24 * 3600)

    assert h.gateway.invoke(make_request(request_id="r3")).status == "ok"


def test_degraded_requests_do_not_consume_quota(make_gateway):
    a = ScriptedProvider(hint_ok())
    h = make_gateway(
        {"a": external_provider(enabled=False)},
        ["a"],
        {"a": a},
        budgets={"student_daily_requests": 1},
    )

    first = h.gateway.invoke(make_request(request_id="r1"))
    second = h.gateway.invoke(make_request(request_id="r2"))

    assert first.error_code == "MODEL_UNAVAILABLE"
    assert second.error_code == "MODEL_UNAVAILABLE", "没有真正调用模型就不占额度"


def test_candidate_over_the_per_request_cost_cap_is_skipped(make_gateway):
    a, m = ScriptedProvider(hint_ok("A")), ScriptedProvider(hint_ok("M"))
    providers = {"a": external_provider(pricing=EXPENSIVE), "m": local_provider()}
    h = make_gateway(providers, ["a", "m"], {"a": a, "m": m})

    response = h.gateway.invoke(make_request())

    assert not a.calls
    assert response.provider == "m"


def test_request_level_budget_can_tighten_the_cap(make_gateway):
    a, m = ScriptedProvider(hint_ok("A")), ScriptedProvider(hint_ok("M"))
    h = make_gateway(
        {"a": external_provider(), "m": local_provider()}, ["a", "m"], {"a": a, "m": m}
    )

    response = h.gateway.invoke(make_request(cost_budget=CostBudget(max_estimated_cost_micros=1)))

    assert not a.calls
    assert response.provider == "m"


def test_request_level_budget_cannot_exceed_the_configured_cap(make_gateway):
    a, m = ScriptedProvider(hint_ok("A")), ScriptedProvider(hint_ok("M"))
    providers = {"a": external_provider(pricing=EXPENSIVE), "m": local_provider()}
    h = make_gateway(providers, ["a", "m"], {"a": a, "m": m})

    generous = CostBudget(max_estimated_cost_micros=10**12)
    response = h.gateway.invoke(make_request(cost_budget=generous))

    assert not a.calls
    assert response.provider == "m"


def test_only_over_budget_candidates_degrade_with_budget_exceeded(make_gateway):
    a = ScriptedProvider(hint_ok("A"))
    h = make_gateway({"a": external_provider(pricing=EXPENSIVE)}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "BUDGET_EXCEEDED"


def test_usage_reports_estimated_cost_from_reported_tokens(make_gateway):
    result = ProviderResult(output=hint_ok(), input_tokens=1000, output_tokens=500)
    a = ScriptedProvider(result)
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 500
    # 1000/1k * 1000 + 500/1k * 2000
    assert response.usage.estimated_cost_micros == 2000


def test_local_provider_costs_nothing(make_gateway):
    h, _ = _mock_only(make_gateway)

    response = h.gateway.invoke(make_request())

    assert response.usage.estimated_cost_micros == 0
