import pytest

from support.gateway_fakes import ScriptedProvider, hint_ok, local_provider, make_request, timeout


@pytest.mark.parametrize("entry", ["legacy", "single"])
@pytest.mark.parametrize("unavailable", [False, True])
def test_pause_and_storage_failure_block_adapter_without_spending_initial_quota(
    make_gateway, entry, unavailable, caplog
):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"m": local_provider()}, ["m"], {"m": adapter})

    def guard():
        if unavailable:
            raise RuntimeError("DO-NOT-LOG-CONNECTION-DETAILS")
        return False

    h.gateway.bind_dispatch_guard(guard)
    request = make_request()
    if entry == "single":
        plan = h.gateway.prepare_single_attempt(request)
        response = h.gateway.invoke_single_attempt(plan)
        h.gateway.bind_dispatch_guard(None)
        assert h.gateway.invoke_single_attempt(plan).error_code == "ATTEMPT_ALREADY_USED"
    else:
        response = h.gateway.invoke(request)
    assert response.error_code == ("BUDGET_UNAVAILABLE" if unavailable else "BUDGET_EXCEEDED")
    assert response.provider_calls == 0 and adapter.calls == []
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 0
    assert "DO-NOT-LOG-CONNECTION-DETAILS" not in caplog.text


def test_pause_during_retry_backoff_stops_retry_and_fallback(make_gateway):
    first, fallback = ScriptedProvider(timeout()), ScriptedProvider(hint_ok())
    h = make_gateway(
        {"a": local_provider(), "b": local_provider()}, ["a", "b"], {"a": first, "b": fallback}
    )
    paused = [False]
    h.gateway.bind_dispatch_guard(lambda: not paused[0])

    def backoff(seconds):
        paused[0] = True

    h.gateway._sleep = backoff
    response = h.gateway.invoke(make_request())
    assert response.error_code == "BUDGET_EXCEEDED"
    assert response.provider_calls == 1 and len(first.calls) == 1
    assert fallback.calls == []


def test_pause_after_failure_stops_cross_candidate_fallback(make_gateway):
    paused = [False]

    class First(ScriptedProvider):
        def invoke(self, **kwargs):
            paused[0] = True
            return super().invoke(**kwargs)

    first, fallback = First(timeout()), ScriptedProvider(hint_ok())
    h = make_gateway(
        {"a": local_provider(), "b": local_provider()},
        ["a", "b"],
        {"a": first, "b": fallback},
        defaults={"max_retries": 0},
    )
    h.gateway.bind_dispatch_guard(lambda: not paused[0])
    response = h.gateway.invoke(make_request())
    assert response.provider_calls == 1 and response.error_code == "BUDGET_EXCEEDED"
    assert fallback.calls == []
