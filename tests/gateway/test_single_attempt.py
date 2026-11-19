from concurrent.futures import ThreadPoolExecutor

import pytest

from support.gateway_fakes import ScriptedProvider, hint_ok, local_provider, make_request, timeout


def test_single_attempt_never_retries_or_falls_back(make_gateway):
    first = ScriptedProvider(timeout(), hint_ok())
    fallback = ScriptedProvider(hint_ok())
    h = make_gateway(
        {"a": local_provider(), "b": local_provider()}, ["a", "b"], {"a": first, "b": fallback}
    )
    plan = h.gateway.prepare_single_attempt(make_request())
    result = h.gateway.invoke_single_attempt(plan)
    assert result.error_code == "TIMEOUT"
    assert result.provider_calls == 1
    assert len(first.calls) == 1
    assert fallback.calls == []
    assert h.gateway.invoke_single_attempt(plan).provider_calls == 0
    assert len(first.calls) == 1
    assert h.audit.records == []
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 0


def test_single_attempt_has_immutable_request_snapshot(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"a": local_provider()}, ["a"], {"a": adapter})
    request = make_request()
    plan = h.gateway.prepare_single_attempt(request)
    request.constraints.max_output_tokens = 1
    assert h.gateway.invoke_single_attempt(plan).status == "ok"
    assert adapter.calls[0]["request"].constraints.max_output_tokens != 1


def test_disabled_candidate_cannot_prepare_single_attempt(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"a": local_provider(enabled=False)}, ["a"], {"a": adapter})
    with pytest.raises(ValueError):
        h.gateway.prepare_single_attempt(make_request())
    assert adapter.calls == []


def test_same_plan_eight_way_concurrency_sends_once(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"a": local_provider()}, ["a"], {"a": adapter})
    plan = h.gateway.prepare_single_attempt(make_request())
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: h.gateway.invoke_single_attempt(plan), range(8)))
    assert sum(result.status == "ok" for result in responses) == 1
    assert len(adapter.calls) == 1
    assert sum(result.error_code == "ATTEMPT_ALREADY_USED" for result in responses) == 7
