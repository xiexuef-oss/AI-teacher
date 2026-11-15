"""超时重试、熔断与错误隔离（docs/10：单一供应商失败先在平台内重试限次）。"""

from __future__ import annotations

from ai_gateway import ProviderError, TaskType
from support.gateway_fakes import (
    ScriptedProvider,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    timeout,
    unavailable,
)


def _pair(make_gateway, *script, **overrides):
    a, m = ScriptedProvider(*script), ScriptedProvider(hint_ok("M"))
    h = make_gateway(
        {"a": external_provider(), "m": local_provider()}, ["a", "m"], {"a": a, "m": m}, **overrides
    )
    return h, a, m


def _only(make_gateway, *script, **overrides):
    a = ScriptedProvider(*script)
    return make_gateway({"a": external_provider()}, ["a"], {"a": a}, **overrides), a


def test_timeout_is_retried_on_the_same_provider(make_gateway):
    h, a, m = _pair(make_gateway, timeout(), hint_ok("A"))

    response = h.gateway.invoke(make_request())

    assert response.status == "ok" and response.provider == "a"
    assert len(a.calls) == 2 and not m.calls
    assert response.provider_calls == 2
    assert len(h.clock.slept) == 1, "两次调用之间应有一次退避"


def test_retries_are_limited_then_next_candidate_is_used(make_gateway):
    h, a, m = _pair(make_gateway, timeout())

    response = h.gateway.invoke(make_request())

    assert len(a.calls) == 2, "首次 + max_retries(1)"
    assert response.provider == "m"
    assert response.provider_calls == 3


def test_rate_limit_is_not_retried(make_gateway):
    h, a, _ = _pair(make_gateway, ProviderError("rate_limited", "HTTP 429"))

    response = h.gateway.invoke(make_request())

    assert len(a.calls) == 1
    assert response.provider == "m"


def test_configured_timeout_is_passed_to_the_adapter(make_gateway):
    h, a = _only(make_gateway, hint_ok())
    h.gateway.invoke(make_request())
    assert a.calls[0]["timeout_s"] == 8.0

    candidates = [{"provider": "a", "model_env": "X_MODEL"}]
    h, a = _only(
        make_gateway,
        hint_ok(),
        routes={"tutor_explain": {"candidates": candidates, "timeout_ms": 30000}},
    )
    h.gateway.invoke(make_request())
    assert a.calls[0]["timeout_s"] == 30.0


def test_circuit_opens_after_consecutive_failures(make_gateway):
    h, a, m = _pair(make_gateway, unavailable())

    h.gateway.invoke(make_request(request_id="r1"))  # 2 次失败
    h.gateway.invoke(make_request(request_id="r2"))  # 第 3 次失败，熔断
    assert len(a.calls) == 3, "达到阈值后立刻停止重试"

    response = h.gateway.invoke(make_request(request_id="r3"))

    assert len(a.calls) == 3, "熔断期间不再调用该供应商"
    assert response.provider == "m"
    status = h.gateway.describe_route(TaskType.TUTOR_EXPLAIN)[0]
    assert status.usable is False and status.reason == "circuit_open"


def test_circuit_half_opens_after_cooldown_and_closes_on_success(make_gateway):
    h, a, _ = _pair(make_gateway, unavailable(), unavailable(), unavailable(), hint_ok("A"))
    h.gateway.invoke(make_request(request_id="r1"))
    h.gateway.invoke(make_request(request_id="r2"))

    h.clock.advance(61)
    probe = h.gateway.invoke(make_request(request_id="r3"))

    assert probe.provider == "a" and len(a.calls) == 4
    again = h.gateway.invoke(make_request(request_id="r4"))
    assert again.provider == "a", "探测成功后熔断关闭"


def test_failed_probe_reopens_the_circuit_without_retrying(make_gateway):
    h, a, _ = _pair(make_gateway, unavailable())
    h.gateway.invoke(make_request(request_id="r1"))
    h.gateway.invoke(make_request(request_id="r2"))
    assert len(a.calls) == 3

    h.clock.advance(61)
    h.gateway.invoke(make_request(request_id="r3"))
    assert len(a.calls) == 4, "半开状态只放行一次探测"

    h.gateway.invoke(make_request(request_id="r4"))
    assert len(a.calls) == 4, "探测失败后重新熔断"


def test_success_resets_the_failure_count(make_gateway):
    h, a, _ = _pair(
        make_gateway,
        unavailable(),
        hint_ok("A"),
        unavailable(),
        hint_ok("A"),
        unavailable(),
        hint_ok("A"),
    )

    for i in range(3):
        response = h.gateway.invoke(make_request(request_id=f"r{i}"))
        assert response.provider == "a"

    assert len(a.calls) == 6, "失败从未连续达到 3 次，不应熔断"


def test_unexpected_adapter_exception_is_contained(make_gateway):
    h, a, _ = _pair(make_gateway, RuntimeError("boom: secret-internal-detail"))

    response = h.gateway.invoke(make_request())

    assert response.status == "ok" and response.provider == "m"
    assert a.calls


def test_degraded_response_does_not_leak_internal_error_text(make_gateway):
    h, _ = _only(make_gateway, unavailable())

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "MODEL_UNAVAILABLE"
    dumped = response.model_dump_json()
    assert "internal detail" not in dumped and "503" not in dumped


def test_all_timeouts_are_reported_as_timeout(make_gateway):
    h, _ = _only(make_gateway, timeout())

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "TIMEOUT"
