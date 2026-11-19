import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


def validator():
    schema = json.loads(Path("contracts/model_invocation.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def metadata():
    return dict(
        schema_version=1,
        invocation_id="a" * 32,
        actor_digest="b" * 64,
        budget_key="stu_" + "b" * 32,
        session_digest="c" * 64,
        question_version=1,
        context_generation=0,
        fingerprint="d" * 64,
        context_digest="a" * 64,
        quota_day="2026-11-16",
        fence=1,
        state="prepared",
        attempts=[],
    )


def test_valid_prepared_metadata():
    validator().validate(metadata())


def document_metadata():
    value = metadata()
    del value["session_digest"], value["question_version"]
    return dict(
        value,
        schema_version=2,
        context_kind="document_ocr",
        resource_digest="c" * 64,
        file_digest="e" * 64,
        page=1,
    )


def test_document_context_has_no_fabricated_student_session():
    validator().validate(document_metadata())


@pytest.mark.parametrize(
    "field", ["session_digest", "question_version", "prompt", "image", "response"]
)
def test_document_context_rejects_tutoring_identity_and_raw_content(field):
    value = document_metadata()
    value[field] = metadata().get(field, "raw-must-not-persist")
    assert list(validator().iter_errors(value))


@pytest.mark.parametrize("field", ["context_kind", "resource_digest", "file_digest", "page"])
def test_document_binding_fields_are_required_and_not_valid_in_v1(field):
    value = document_metadata()
    del value[field]
    assert list(validator().iter_errors(value))
    old = metadata()
    old[field] = document_metadata()[field]
    assert list(validator().iter_errors(old))


@pytest.mark.parametrize("field", ["prompt", "response", "student_input", "image", "api_key"])
def test_raw_content_cannot_enter_invocation_metadata(field):
    value = metadata()
    value[field] = "must not persist"
    assert list(validator().iter_errors(value))


def test_dispatch_requires_attempt_and_unsent_cancellation_rejects_it():
    value = metadata()
    value["state"] = "dispatch_unknown"
    assert list(validator().iter_errors(value))
    value["attempts"] = [
        dict(attempt_id="e" * 32, fence=1, estimated_cost_micros=1, state="dispatch_unknown")
    ]
    validator().validate(value)
    value["state"] = "cancelled_unsent"
    assert list(validator().iter_errors(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("quota_day", "2026-02-30"),
        ("fence", 0),
        ("question_version", 1.5),
        ("actor_digest", "user-id"),
    ],
)
def test_invalid_identity_and_generation_are_rejected(field, value):
    record = metadata()
    record[field] = value
    assert list(validator().iter_errors(record))
