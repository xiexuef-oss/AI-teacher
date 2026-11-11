"""内置 Mock 供应商（Q-04A：原型期用网关 Mock 与规则降级）。"""

from __future__ import annotations

import pytest

from ai_gateway import InputPart, TaskType, build_gateway, load_config
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    EXAMPLE_ROUTES_PATH,
    VISUAL_REGISTRY_PATH,
    make_request,
)


@pytest.fixture
def gateway():
    return build_gateway(
        load_config(EXAMPLE_ROUTES_PATH),
        env={},
        environment="local",
        allow_external_calls=False,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
    )


@pytest.mark.parametrize("task", list(TaskType), ids=lambda t: t.value)
def test_mock_output_passes_gateway_validation_for_every_task(gateway, task):
    response = gateway.invoke(make_request(task))

    assert response.status == "ok", response.error_code
    assert response.provider == "mock"
    assert response.model_id.startswith("mock-")
    assert response.validated_output is not None


def test_mock_explain_talks_about_the_supplied_concept(gateway):
    parts = [
        InputPart(kind="json", data={"concept": "基本不等式", "key_idea": "和为定值时积有最大值"})
    ]

    response = gateway.invoke(make_request(TaskType.TUTOR_EXPLAIN, input_parts=parts))

    payload = response.validated_output["payload"]
    assert payload["style"] in {"rephrase", "example"}
    assert payload["concept"] == "基本不等式"
    assert "和为定值时积有最大值" in payload["text"]


def test_mock_is_deterministic(gateway):
    first = gateway.invoke(make_request(request_id="r1"))
    second = gateway.invoke(make_request(request_id="r2"))

    assert first.validated_output == second.validated_output


def test_mock_visual_uses_requested_template(gateway):
    parts = [InputPart(kind="json", data={"template_id": "motion_chart", "params": {"a": -2}})]

    response = gateway.invoke(make_request(TaskType.VISUAL_SPEC, input_parts=parts))

    payload = response.validated_output["payload"]
    assert payload["template_id"] == "motion_chart"
    assert payload["params"] == {"v0": 0, "a": -2, "t_max": 5}


def test_mock_ocr_admits_it_cannot_read_images(gateway):
    """Mock 不做真实识别：置信度为 0，必须由学生确认或手动录入。"""
    response = gateway.invoke(make_request(TaskType.OCR_EXTRACT))

    assert response.confidence == 0.0
    assert response.review_required is True
