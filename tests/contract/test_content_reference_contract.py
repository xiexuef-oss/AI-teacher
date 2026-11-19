"""固定版本内容引用的公开形状与教学事件保持同一约束。"""

import copy

import pytest
from jsonschema import Draft202012Validator

from support.contract import load_event_schema, load_openapi


def test_reference_shapes_match_event_contract():
    schemas = load_openapi()["components"]["schemas"]
    event = load_event_schema()
    for name in ("ContentSpanRef", "ResolvedContentSpan"):
        assert schemas[name] == event["$defs"][name]
    assert "references" not in schemas["TutorEvent"]["required"]
    assert "reference_links" not in schemas["AdminTeaching"]["required"]


@pytest.mark.parametrize(
    "block_id",
    [
        "stem",
        "subquestion:2:stem",
        "reference_cell:1:2:3",
        "reference_step:1:reason",
        "solution:fast:step:2",
    ],
)
def test_reference_ordinal_block_names(block_id):
    schema = load_openapi()["components"]["schemas"]["ContentSpanRef"]
    Draft202012Validator(schema).validate(
        {"block_id": block_id, "block_sha256": "a" * 64, "start": 0, "end": 1}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"block_id": "https://example.test"},
        {"block_id": "hint:01"},
        {"block_id": "reference_step:1:html"},
        {"block_sha256": "A" * 64},
        {"start": True},
        {"start": 0.5},
        {"start": -1},
        {"end": 4001},
        {"url": "https://example.test"},
    ],
)
def test_reference_shape_rejects_unknown_or_ambiguous_fields(change):
    schema = load_openapi()["components"]["schemas"]["ContentSpanRef"]
    value = {"block_id": "stem", "block_sha256": "a" * 64, "start": 0, "end": 1}
    value.update(copy.deepcopy(change))
    assert list(Draft202012Validator(schema).iter_errors(value))
