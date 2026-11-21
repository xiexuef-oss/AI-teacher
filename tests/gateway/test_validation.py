"""模型输出校验：不合 Schema、带标记或泄题的输出一律不下发（docs/10 质量门禁）。"""

from __future__ import annotations

import pytest

from ai_gateway import Constraints, ProviderResult, TaskType, VisualRegistry, VisualTemplateError
from support.gateway_fakes import (
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    visual_ok,
)

HINT_MISSING_TEXT = {
    "event_type": "hint",
    "payload": {"level": 1, "total_levels": 3, "style": "rephrase", "concept": None},
}
OCR_OK = {
    "stem_text": "已知函数 f(x)=x^2-2x-3，求单调递增区间。",
    "expressions": [{"span_id": "s1", "latex": "f(x)=x^2-2x-3", "confidence": 0.9}],
}


def _two(make_gateway, first, second=None):
    a = ScriptedProvider(first)
    m = ScriptedProvider(second if second is not None else hint_ok("M"))
    h = make_gateway(
        {"a": external_provider(), "m": local_provider()}, ["a", "m"], {"a": a, "m": m}
    )
    return h, a, m


def test_schema_invalid_output_is_not_returned_and_next_candidate_is_used(make_gateway):
    h, a, m = _two(make_gateway, HINT_MISSING_TEXT)

    response = h.gateway.invoke(make_request())

    assert len(a.calls) == 1, "结构不对不重试同一个供应商"
    assert response.status == "ok" and response.provider == "m"
    assert response.validated_output == hint_ok("M")


def test_all_candidates_invalid_degrades_with_schema_invalid(make_gateway):
    h, _, _ = _two(make_gateway, HINT_MISSING_TEXT, {"event_type": "hint", "payload": {"oops": 1}})

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "SCHEMA_INVALID"
    assert response.validated_output is None


def test_output_of_wrong_event_type_for_the_task_is_rejected(make_gateway):
    h, _, _ = _two(make_gateway, visual_ok())

    response = h.gateway.invoke(make_request(TaskType.TUTOR_EXPLAIN))

    assert response.provider == "m"


def test_non_object_output_is_rejected(make_gateway):
    a = ScriptedProvider(ProviderResult(output=["not", "an", "object"]))  # type: ignore[arg-type]
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded" and response.error_code == "SCHEMA_INVALID"


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        "看这里 <iframe src='x'></iframe>",
        "点这个 javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
        "<SVG onload=alert(1)>",
    ],
)
def test_markup_in_model_output_is_blocked(make_gateway, text):
    a = ScriptedProvider(hint_ok(text))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.status == "degraded"
    assert response.error_code == "CONTENT_BLOCKED"
    assert response.validated_output is None


def test_inequalities_are_not_mistaken_for_markup(make_gateway):
    text = "当 x<a 且 b>0 时，f(x)<0；又因为 a<b，所以 x<b。"
    a = ScriptedProvider(hint_ok(text))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request())

    assert response.status == "ok"
    assert response.validated_output["payload"]["text"] == text


def test_output_leaking_a_forbidden_answer_is_blocked(make_gateway):
    """独立作答阶段不能提前泄题：编排器把不能出现的答案表述交给网关把关。"""
    h, a, _ = _two(make_gateway, hint_ok("所以这题选 B。"))
    request = make_request(constraints=Constraints(forbidden_substrings=["选 B", "答案是 B"]))

    response = h.gateway.invoke(request)

    assert len(a.calls) == 1
    assert response.provider == "m", "泄题输出被丢弃，改用下一个候选"


def test_leak_check_ignores_spacing_and_case(make_gateway):
    a = ScriptedProvider(hint_ok("综上，选b 。"))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})
    request = make_request(constraints=Constraints(forbidden_substrings=["选 B"]))

    response = h.gateway.invoke(request)

    assert response.status == "degraded" and response.error_code == "CONTENT_BLOCKED"


# ---------------------------------------------------------------- 图解白名单


def test_visual_spec_passes_with_registered_template_and_fills_defaults(make_gateway):
    a = ScriptedProvider(visual_ok(params={"a": 2}))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request(TaskType.VISUAL_SPEC))

    assert response.status == "ok"
    assert response.validated_output["payload"]["params"] == {"a": 2, "b": 0, "c": 0}


@pytest.mark.parametrize(
    "overrides",
    [
        {"template_id": "free_canvas"},
        {"params": {"a": 99}},
        {"params": {"a": 1, "zoom": 3}},
        {"template_id": "chemical_flow", "params": {"coef_a": 1.5}},
        {"params": {"a": float("inf")}},
        {"params": {"a": float("nan")}},
        {"params": {"a": True}},
        {"params": {"a": "1"}},
    ],
    ids=[
        "unregistered",
        "out-of-range",
        "unknown-param",
        "non-integer",
        "inf",
        "nan",
        "bool",
        "string",
    ],
)
def test_visual_spec_outside_whitelist_is_rejected(make_gateway, overrides):
    a = ScriptedProvider(visual_ok(**overrides))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    response = h.gateway.invoke(make_request(TaskType.VISUAL_SPEC))

    assert response.status == "degraded"
    assert response.error_code == "SCHEMA_INVALID"
    assert response.validated_output is None


def test_registry_normalize_fills_defaults_and_keeps_order():
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    assert registry.normalize("motion_chart", {"a": -2}) == {"v0": 0, "a": -2, "t_max": 5}
    assert list(registry.normalize("number_line", {})) == [
        "min",
        "max",
        "left",
        "right",
        "left_closed",
        "right_closed",
        "left_unbounded",
        "right_unbounded",
    ]


def test_registry_accepts_boundary_values():
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    assert registry.normalize("force_diagram", {"angle_deg": 60, "mu": 0})["angle_deg"] == 60


def test_registry_rejects_unknown_template():
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    with pytest.raises(VisualTemplateError):
        registry.normalize("free_canvas", {})
    assert registry.template_ids() == {
        "chemical_process",
        "triangle_schematic",
        "circle_schematic",
        "quadratic_graph",
        "rectangle_area",
        "number_line",
        "force_diagram",
        "motion_chart",
        "chemical_flow",
    }


# ---------------------------------------------------------------- 置信度


def _ocr_gateway(make_gateway, result):
    a = ScriptedProvider(result)
    candidates = [{"provider": "a", "model_env": "X_MODEL"}]
    return make_gateway(
        {"a": external_provider()},
        ["a"],
        {"a": a},
        routes={"ocr_extract": {"candidates": candidates, "min_confidence": 0.8}},
    )


def test_low_confidence_output_requires_review(make_gateway):
    h = _ocr_gateway(make_gateway, ProviderResult(output=OCR_OK, confidence=0.42))

    response = h.gateway.invoke(make_request(TaskType.OCR_EXTRACT))

    assert response.status == "ok"
    assert response.confidence == 0.42
    assert response.review_required is True


def test_ocr_cannot_return_a_teacher_score_or_marks(make_gateway):
    h = _ocr_gateway(
        make_gateway,
        ProviderResult(output={**OCR_OK, "teacher_marks": "Check", "teacher_score": 3}),
    )
    response = h.gateway.invoke(make_request(TaskType.OCR_EXTRACT))
    assert response.validated_output is None


def test_confident_output_does_not_require_review(make_gateway):
    h = _ocr_gateway(make_gateway, ProviderResult(output=OCR_OK, confidence=0.97))

    response = h.gateway.invoke(make_request(TaskType.OCR_EXTRACT))

    assert response.review_required is False


def test_unknown_confidence_requires_review_when_route_sets_a_threshold(make_gateway):
    h = _ocr_gateway(make_gateway, ProviderResult(output=OCR_OK, confidence=None))

    response = h.gateway.invoke(make_request(TaskType.OCR_EXTRACT))

    assert response.review_required is True
