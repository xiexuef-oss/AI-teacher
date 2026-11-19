"""Approved fixed-version reference proposals, without identity metadata leak false positives."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from ai_gateway.dto import Constraints, TaskType
from ai_gateway.errors import OutputRejected
from ai_gateway.prompts import build_messages
from ai_gateway.providers.mock import MockProvider
from ai_gateway.validation import OutputValidator
from ai_gateway.visual_templates import VisualRegistry
from support.gateway_fakes import EVENT_SCHEMA_PATH, VISUAL_REGISTRY_PATH, hint_ok, make_request


def resolved(text="条件😀e\u0301\n$x=2$，观察变化", **overrides):
    return dict(
        block_id="stem",
        block_sha256=hashlib.sha256(text.encode()).hexdigest(),
        start=2,
        end=3,
        block_text=text,
        label="题面条件",
        **overrides,
    )


def ref(value):
    return {key: value[key] for key in ("block_id", "block_sha256", "start", "end")}


@pytest.fixture
def validator():
    return OutputValidator(
        json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8")),
        VisualRegistry.load(VISUAL_REGISTRY_PATH),
    )


def output(references):
    return {**hint_ok("观察条件。"), "references": references}


def test_approved_exact_span_and_hash_digits_are_not_answer_text(validator):
    value = resolved()
    # A digit from the digest must not be scanned as an answer.
    digit = next(
        character for character in value["block_sha256"] if character.isdigit() and character != "2"
    )
    constraints = Constraints(reference_catalog=[value], forbidden_substrings=[digit])
    assert validator.validate(TaskType.TUTOR_EXPLAIN, output([ref(value)]), constraints)[
        "references"
    ] == [ref(value)]


@pytest.mark.parametrize(
    "mutation",
    [
        {"start": True},
        {"start": 2.0},
        {"end": 4001},
        {"start": 0},
        {"end": 4},
        {"block_sha256": "f" * 64},
        {"block_id": "option:1"},
        {"url": "https://example.com"},
    ],
)
def test_invalid_or_unapproved_proposals_rejected(validator, mutation):
    value = resolved()
    proposal = {**ref(value), **mutation}
    with pytest.raises(OutputRejected):
        validator.validate(
            TaskType.TUTOR_EXPLAIN, output([proposal]), Constraints(reference_catalog=[value])
        )


def test_unknown_duplicate_and_too_many_refs_rejected(validator):
    value = resolved()
    for proposals, catalog in [
        ([ref(value)], []),
        ([ref(value)] * 2, [value]),
        ([ref(value)] * 9, [value]),
    ]:
        with pytest.raises(OutputRejected):
            validator.validate(
                TaskType.TUTOR_HINT, output(proposals), Constraints(reference_catalog=catalog)
            )


@pytest.mark.parametrize(
    "text,forbidden", [("安全😀但答案是42", ["42"]), ("安全😀<script>bad</script>", [])]
)
def test_entire_context_is_checked_even_when_selected_span_is_safe(validator, text, forbidden):
    value = resolved(text)
    with pytest.raises(OutputRejected):
        validator.validate(
            TaskType.TUTOR_EXPLAIN,
            output([ref(value)]),
            Constraints(reference_catalog=[value], forbidden_substrings=forbidden),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"start": True},
        {"end": 2},
        {"end": 999},
        {"block_sha256": "f" * 64},
        {"block_text": "x" * 4001},
    ],
)
def test_invalid_trusted_catalog_fails_closed(mutation):
    with pytest.raises(ValidationError):
        Constraints(reference_catalog=[{**resolved(), **mutation}])


def test_legacy_output_works_and_payload_is_still_scanned(validator):
    assert validator.validate(TaskType.TUTOR_HINT, hint_ok("旧提示"), Constraints()) == hint_ok(
        "旧提示"
    )
    with pytest.raises(OutputRejected):
        validator.validate(
            TaskType.TUTOR_HINT, hint_ok("答案42"), Constraints(forbidden_substrings=["42"])
        )


def test_mock_and_prompt_use_only_approved_whole_annotations(validator):
    value = resolved()
    request = make_request(TaskType.TUTOR_EXPLAIN).model_copy(
        update={"constraints": Constraints(reference_catalog=[value])}
    )
    messages = build_messages(request)
    assert json.loads(messages[1]["content"])["reference_catalog"] == [value]
    assert "references" in messages[0]["content"]
    result = MockProvider().invoke(model="mock", request=request, timeout_s=1)
    assert result.output["references"] == [ref(value)]
    assert validator.validate(request.task_type, result.output, request.constraints)


@pytest.mark.parametrize(
    "task", [TaskType.TUTOR_HINT, TaskType.TUTOR_EXPLAIN, TaskType.VISUAL_SPEC]
)
def test_all_teaching_outputs_accept_only_authorized_reference_shapes(validator, task):
    from support.gateway_fakes import visual_ok

    value = resolved()
    result = visual_ok() if task is TaskType.VISUAL_SPEC else hint_ok("观察条件")
    result["references"] = [ref(value)]
    assert validator.validate(task, result, Constraints(reference_catalog=[value]))[
        "references"
    ] == [ref(value)]
    result["references"][0]["version"] = 2
    with pytest.raises(OutputRejected):
        validator.validate(task, result, Constraints(reference_catalog=[value]))


def test_resolved_codepoints_preserve_combining_marks_newlines_and_formula():
    value = resolved()
    constraints = Constraints(reference_catalog=[value])
    candidate = constraints.reference_catalog[0]
    assert candidate.block_text[candidate.start : candidate.end] == "😀"
    assert "\n$x=2$" in candidate.block_text
    assert "e\u0301" in candidate.block_text
    assert candidate.model_dump() == value
    with pytest.raises(ValidationError):
        Constraints(reference_catalog=[value] * 65)


def test_reference_payload_and_resolved_label_cannot_hide_blocked_text(validator):
    value = resolved()
    value["label"] = "答案42"
    with pytest.raises(OutputRejected):
        validator.validate(
            TaskType.TUTOR_EXPLAIN,
            output([ref(value)]),
            Constraints(reference_catalog=[value], forbidden_substrings=["42"]),
        )
    value["label"] = "条件"
    result = output([ref(value)])
    result["payload"]["text"] = "<script>bad</script>"
    with pytest.raises(OutputRejected):
        validator.validate(TaskType.TUTOR_EXPLAIN, result, Constraints(reference_catalog=[value]))
