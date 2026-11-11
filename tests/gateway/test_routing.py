"""任务路由与供应商可用性（docs/10：路由与降级规则）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_gateway import GatewayConfig, PrivacyPolicy, TaskType, build_gateway, load_config
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    EXAMPLE_ROUTES_PATH,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    unavailable,
)

UNVERIFIED_PRICING = {
    "input_per_1k_tokens_micros": None,
    "output_per_1k_tokens_micros": None,
    "image_unit_micros": None,
}


def test_candidates_are_tried_in_configured_order(make_gateway):
    a, b = ScriptedProvider(hint_ok("来自 A")), ScriptedProvider(hint_ok("来自 B"))
    h = make_gateway(
        {"a": external_provider(), "b": external_provider()}, ["a", "b"], {"a": a, "b": b}
    )

    response = h.gateway.invoke(make_request())

    assert response.status == "ok"
    assert response.provider == "a"
    assert response.model_id == "x-model-1"
    assert response.validated_output == hint_ok("来自 A")
    assert response.error_code is None
    assert response.trace_id == "trace-1"
    assert len(a.calls) == 1 and not b.calls


@pytest.mark.parametrize(
    ("provider", "kwargs", "reason"),
    [
        (external_provider(enabled=False), {}, "disabled"),
        (external_provider(approved=False), {}, "not_compliance_approved"),
        (external_provider(), {"allow_external_calls": False}, "external_calls_not_allowed"),
        (
            external_provider(),
            {"env": {"X_BASE_URL": "https://models.invalid/v1", "X_MODEL": "m"}},
            "missing_env:X_API_KEY",
        ),
        (
            external_provider(),
            {"env": {"X_BASE_URL": "https://models.invalid/v1", "X_API_KEY": "k"}},
            "missing_env:X_MODEL",
        ),
        (external_provider(pricing=UNVERIFIED_PRICING), {}, "pricing_unverified"),
    ],
    ids=["disabled", "not-approved", "global-switch-off", "no-api-key", "no-model", "no-pricing"],
)
def test_unusable_external_provider_is_skipped(make_gateway, provider, kwargs, reason):
    a, m = ScriptedProvider(hint_ok("A")), ScriptedProvider(hint_ok("M"))
    h = make_gateway({"a": provider, "m": local_provider()}, ["a", "m"], {"a": a, "m": m}, **kwargs)

    response = h.gateway.invoke(make_request())

    assert response.status == "ok" and response.provider == "m"
    assert not a.calls
    statuses = {s.provider: s for s in h.gateway.describe_route(TaskType.TUTOR_EXPLAIN)}
    assert statuses["a"].usable is False and statuses["a"].reason == reason
    assert statuses["m"].usable is True and statuses["m"].reason is None


def test_mock_provider_is_refused_outside_local_and_dev(make_gateway):
    m = ScriptedProvider(hint_ok())
    h = make_gateway({"m": local_provider()}, ["m"], {"m": m}, environment="prod")

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded" and response.error_code == "MODEL_UNAVAILABLE"
    assert not m.calls
    assert (
        h.gateway.describe_route(TaskType.TUTOR_EXPLAIN)[0].reason == "not_allowed_in_environment"
    )


def test_no_usable_candidate_degrades_without_output(make_gateway):
    a = ScriptedProvider(hint_ok())
    h = make_gateway({"a": external_provider(enabled=False)}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "MODEL_UNAVAILABLE"
    assert response.validated_output is None
    assert response.provider is None and response.model_id is None
    assert response.provider_calls == 0
    assert response.trace_id == "trace-1"


def test_second_external_provider_is_not_used_without_cross_provider_opt_in(make_gateway):
    """docs/10：不可跨服务商任意传输未成年人的原始数据。默认只把数据交给第一个外部供应商。"""
    a, b, m = (
        ScriptedProvider(unavailable()),
        ScriptedProvider(hint_ok("B")),
        ScriptedProvider(hint_ok("M")),
    )
    providers = {"a": external_provider(), "b": external_provider(), "m": local_provider()}
    h = make_gateway(providers, ["a", "b", "m"], {"a": a, "b": b, "m": m})

    response = h.gateway.invoke(make_request())

    assert a.calls and not b.calls
    assert response.provider == "m"


def test_cross_provider_fallback_when_explicitly_allowed(make_gateway):
    a, b, m = (
        ScriptedProvider(unavailable()),
        ScriptedProvider(hint_ok("B")),
        ScriptedProvider(hint_ok("M")),
    )
    providers = {"a": external_provider(), "b": external_provider(), "m": local_provider()}
    h = make_gateway(providers, ["a", "b", "m"], {"a": a, "b": b, "m": m})

    request = make_request(privacy_policy=PrivacyPolicy(allow_cross_provider_fallback=True))
    response = h.gateway.invoke(request)

    assert response.provider == "b"
    assert not m.calls


def _example_gateway(**kwargs):
    return build_gateway(
        load_config(EXAMPLE_ROUTES_PATH),
        environment="local",
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        **kwargs,
    )


def test_example_config_only_ever_reaches_mock():
    gateway = _example_gateway(env={}, allow_external_calls=False)
    for task in TaskType:
        usable = [s.provider for s in gateway.describe_route(task) if s.usable]
        assert usable == ["mock"], task


def test_example_config_stays_mock_only_even_with_switch_and_keys_present():
    """示例配置里外部供应商未启用、未过合规，光有总开关和环境变量不够。"""
    config = load_config(EXAMPLE_ROUTES_PATH)
    env = {}
    for provider in config.providers.values():
        if provider.external:
            env[provider.base_url_env] = "https://models.invalid/v1"
            env[provider.api_key_env] = "k"
    for route in config.routes.values():
        for candidate in route.candidates:
            if candidate.model_env:
                env[candidate.model_env] = "some-model"

    gateway = _example_gateway(env=env, allow_external_calls=True)

    for task in TaskType:
        usable = [s.provider for s in gateway.describe_route(task) if s.usable]
        assert usable == ["mock"], task


def test_unsupported_response_schema_version_is_an_error_without_calling_providers(make_gateway):
    m = ScriptedProvider(hint_ok())
    h = make_gateway({"m": local_provider()}, ["m"], {"m": m})

    response = h.gateway.invoke(make_request(response_schema_version="9.9"))

    assert response.status == "error"
    assert response.error_code == "UNSUPPORTED_SCHEMA_VERSION"
    assert response.validated_output is None
    assert not m.calls


def test_external_calls_possible_reflects_real_usability(make_gateway):
    a, m = ScriptedProvider(hint_ok()), ScriptedProvider(hint_ok())
    providers = {"a": external_provider(), "m": local_provider()}

    usable = make_gateway(providers, ["a", "m"], {"a": a, "m": m})
    switched_off = make_gateway(providers, ["a", "m"], {"a": a, "m": m}, allow_external_calls=False)

    assert usable.gateway.external_calls_possible is True
    assert switched_off.gateway.external_calls_possible is False
    assert _example_gateway(env={}, allow_external_calls=False).external_calls_possible is False


def test_config_rejects_route_to_unknown_provider():
    config = config_dict({"m": local_provider()}, ["m"])
    config["routes"]["tutor_hint"]["candidates"].append({"provider": "ghost", "model": "x"})
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(config)


def test_config_requires_exactly_one_model_reference_per_candidate():
    config = config_dict({"m": local_provider()}, ["m"])
    config["routes"]["tutor_hint"]["candidates"] = [
        {"provider": "m", "model": "x", "model_env": "X_MODEL"}
    ]
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(config)


def test_config_must_route_every_task_type():
    config = config_dict({"m": local_provider()}, ["m"])
    del config["routes"]["visual_spec"]
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(config)
