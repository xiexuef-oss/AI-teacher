import pytest

from ai_gateway import InputPart
from ai_gateway.budget import estimate_input_tokens
from support.gateway_fakes import (
    ProviderResult,
    ScriptedProvider,
    external_provider,
    hint_ok,
    make_request,
    timeout,
)


def provider(image_price, *, image_tokens=None):
    return external_provider(
        pricing={
            "input_per_1k_tokens_micros": 1000,
            "output_per_1k_tokens_micros": 2000,
            "image_unit_micros": image_price,
            **({"image_input_tokens_max": image_tokens} if image_tokens is not None else {}),
        }
    )


def request(*, image=True):
    return make_request(
        input_parts=[
            InputPart(kind="image_ref", media_ref="data:image/png;base64,AAAA")
            if image
            else InputPart(kind="text", text="self-authored text")
        ]
    )


@pytest.mark.parametrize("entry", ["legacy", "single"])
def test_unknown_image_price_never_sends_or_spends_initial_quota(make_gateway, entry):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"x": provider(None)}, ["x"], {"x": adapter})
    if entry == "single":
        with pytest.raises(ValueError, match="candidate"):
            h.gateway.prepare_single_attempt(request())
    else:
        response = h.gateway.invoke(request())
        assert response.error_code == "MODEL_UNAVAILABLE" and response.provider_calls == 0
    assert adapter.calls == []
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 0


@pytest.mark.parametrize("entry", ["legacy", "single"])
@pytest.mark.parametrize("image,price", [(False, None), (True, 0), (True, 5000)])
def test_text_only_and_explicit_image_quotes_still_work(make_gateway, entry, image, price):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"x": provider(price)}, ["x"], {"x": adapter})
    response = (
        h.gateway.invoke(request(image=image))
        if entry == "legacy"
        else h.gateway.invoke_single_attempt(h.gateway.prepare_single_attempt(request(image=image)))
    )
    assert response.status == "ok" and len(adapter.calls) == 1


def test_image_quote_revoked_after_preparation_blocks_consumed_plan(make_gateway):
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway({"x": provider(5000)}, ["x"], {"x": adapter})
    plan = h.gateway.prepare_single_attempt(request())
    h.gateway._config.providers["x"].pricing.image_unit_micros = None
    response = h.gateway.invoke_single_attempt(plan)
    assert response.error_code == "MODEL_UNAVAILABLE" and response.provider_calls == 0
    h.gateway._config.providers["x"].pricing.image_unit_micros = 5000
    assert h.gateway.invoke_single_attempt(plan).error_code == "ATTEMPT_ALREADY_USED"
    assert adapter.calls == []


def test_image_quote_revoked_during_backoff_stops_retry(make_gateway):
    adapter = ScriptedProvider(timeout())
    h = make_gateway({"x": provider(5000)}, ["x"], {"x": adapter})

    def backoff(seconds):
        h.gateway._config.providers["x"].pricing.image_unit_micros = None

    h.gateway._sleep = backoff
    response = h.gateway.invoke(request())
    assert response.error_code == "MODEL_UNAVAILABLE"
    assert response.provider_calls == 1 and len(adapter.calls) == 1


def test_unpriced_candidate_is_skipped_before_a_quoted_candidate(make_gateway):
    unknown, quoted = ScriptedProvider(hint_ok()), ScriptedProvider(hint_ok())
    h = make_gateway(
        {"unknown": provider(None), "quoted": provider(5000)},
        ["unknown", "quoted"],
        {"unknown": unknown, "quoted": quoted},
    )
    response = h.gateway.invoke(request())
    assert response.status == "ok" and response.provider == "quoted"
    assert unknown.calls == [] and len(quoted.calls) == 1


@pytest.mark.parametrize("entry", ["legacy", "single"])
def test_token_billed_image_reserves_capacity_and_settles_reported_tokens(make_gateway, entry):
    adapter = ScriptedProvider(
        ProviderResult(output=hint_ok(), input_tokens=1100, output_tokens=25)
    )
    h = make_gateway({"x": provider(None, image_tokens=1024)}, ["x"], {"x": adapter})
    req = request()
    assert h.gateway._estimate("x", req) == (
        estimate_input_tokens(req) + 1024 + req.constraints.max_output_tokens * 2
    )
    response = (
        h.gateway.invoke(req)
        if entry == "legacy"
        else h.gateway.invoke_single_attempt(h.gateway.prepare_single_attempt(req))
    )
    assert response.status == "ok"
    assert response.usage.image_units == 1
    assert response.usage.estimated_cost_micros == (
        response.usage.input_tokens + response.usage.output_tokens * 2
    )


@pytest.mark.parametrize("entry", ["legacy", "single"])
def test_token_billed_image_over_budget_does_not_call_provider(make_gateway, entry):
    adapter = ScriptedProvider(hint_ok())
    req = request()
    text_and_output = estimate_input_tokens(req) + req.constraints.max_output_tokens * 2
    h = make_gateway(
        {"x": provider(None, image_tokens=1024)},
        ["x"],
        {"x": adapter},
        budgets={"per_request_max_cost_micros": text_and_output + 1023},
    )
    if entry == "single":
        with pytest.raises(ValueError, match="within budget"):
            h.gateway.prepare_single_attempt(req)
    else:
        assert h.gateway.invoke(req).error_code == "BUDGET_EXCEEDED"
    assert adapter.calls == []
