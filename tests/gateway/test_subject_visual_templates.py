"""Only bounded numeric parameters may select the two fixed diagrams."""

import math

import pytest

from ai_gateway.visual_templates import VisualRegistry, VisualTemplateError
from tutor_api.settings import VISUAL_REGISTRY_PATH


@pytest.mark.parametrize("template", ["chemical_process", "triangle_schematic", "circle_schematic"])
def test_new_diagram_default_and_boundary_values(template):
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    spec = registry.get(template)
    assert len(registry.normalize(template, {})) == 3
    for extreme in ("min", "max"):
        values = {param.name: getattr(param, extreme) for param in spec.params}
        assert registry.normalize(template, values) == values


@pytest.mark.parametrize(
    "template,param",
    [
        ("chemical_process", "focus"),
        ("chemical_process", "branch"),
        ("chemical_process", "recycle"),
        ("triangle_schematic", "focus"),
        ("circle_schematic", "focus"),
    ],
)
@pytest.mark.parametrize("value", [-1, 99, 0.5, True, "1", math.nan, math.inf])
def test_discrete_diagram_controls_reject_non_integer_or_unbounded_values(template, param, value):
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    with pytest.raises(VisualTemplateError):
        registry.normalize(template, {param: value})


@pytest.mark.parametrize("param", ["apex_x", "height"])
@pytest.mark.parametrize("value", [-1, 1, True, "0.5", math.nan, math.inf])
def test_triangle_layout_is_finite_bounded_and_non_degenerate(param, value):
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    with pytest.raises(VisualTemplateError):
        registry.normalize("triangle_schematic", {param: value})


@pytest.mark.parametrize("param", ["a_position", "b_position"])
@pytest.mark.parametrize("value", [-1, 1, True, "0.5", math.nan, math.inf])
def test_circle_drawing_positions_are_finite_bounded_and_distinct(param, value):
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    with pytest.raises(VisualTemplateError):
        registry.normalize("circle_schematic", {param: value})


@pytest.mark.parametrize("template", ["chemical_process", "triangle_schematic", "circle_schematic"])
@pytest.mark.parametrize(
    "extra", [{"labels": "<script/>"}, {"nodes": 1}, {"url": 1}, {"angle": 30}]
)
def test_no_dynamic_labels_graphs_urls_or_derived_angle_params(template, extra):
    registry = VisualRegistry.load(VISUAL_REGISTRY_PATH)
    with pytest.raises(VisualTemplateError):
        registry.normalize(template, extra)
