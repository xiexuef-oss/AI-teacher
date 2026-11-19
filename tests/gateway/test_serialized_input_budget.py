import hashlib

import pytest

from ai_gateway import InputPart
from ai_gateway.budget import count_image_units, estimate_input_tokens, estimate_request_cost_micros
from ai_gateway.config import Pricing
from ai_gateway.dto import ResolvedContentSpan
from support.gateway_fakes import ScriptedProvider, external_provider, hint_ok, make_request


def with_catalog(request):
    value = request.model_copy(deep=True)
    text = "自编条件与解释。" * 300
    value.constraints.reference_catalog = [
        ResolvedContentSpan(
            block_id="stem",
            block_sha256=hashlib.sha256(text.encode()).hexdigest(),
            start=0,
            end=2,
            block_text=text,
            label="题干",
        )
    ]
    return value


def test_system_instructions_are_included_without_user_input():
    assert estimate_input_tokens(make_request(input_parts=[])) > 0


def test_reference_catalog_changes_input_estimate():
    base = make_request()
    expanded = with_catalog(base)
    assert estimate_input_tokens(expanded) > estimate_input_tokens(base)
    assert estimate_input_tokens(expanded) >= len(
        expanded.constraints.reference_catalog[0].block_text.encode("utf-8")
    )


def test_language_and_unicode_text_are_included():
    base = make_request()
    expanded = base.model_copy(deep=True)
    expanded.constraints.language = "自编语言标记" * 100
    assert estimate_input_tokens(expanded) > estimate_input_tokens(base)
    text = '中文😀e\u0301\n"' * 100
    assert estimate_input_tokens(
        make_request(input_parts=[InputPart(kind="text", text=text)])
    ) >= len(text.encode("utf-8"))


def test_inline_image_payload_is_billed_as_image_not_base64_text():
    first = make_request(
        input_parts=[InputPart(kind="image_ref", media_ref="data:image/png;base64,AAAA")]
    )
    second = make_request(
        input_parts=[InputPart(kind="image_ref", media_ref="data:image/png;base64," + "A" * 4000)]
    )
    assert count_image_units(first) == count_image_units(second) == 1
    assert estimate_input_tokens(first) == estimate_input_tokens(second)


@pytest.mark.parametrize("entry", ["legacy", "single"])
def test_large_catalog_blocks_adapter_before_spending_request_slot(make_gateway, entry):
    provider = external_provider()
    request = make_request()
    cap = estimate_request_cost_micros(Pricing.model_validate(provider["pricing"]), request)
    adapter = ScriptedProvider(hint_ok())
    h = make_gateway(
        {"x": provider}, ["x"], {"x": adapter}, budgets={"per_request_max_cost_micros": cap}
    )
    if entry == "legacy":
        assert h.gateway.invoke(with_catalog(request)).error_code == "BUDGET_EXCEEDED"
    else:
        with pytest.raises(ValueError, match="budget"):
            h.gateway.prepare_single_attempt(with_catalog(request))
    assert adapter.calls == []
    assert h.budget.get_requests("platform", "platform", h.clock.now().date()) == 0
