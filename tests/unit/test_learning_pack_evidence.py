import pytest

from tutor_api.models import LearningPackReturn, QuestionVersion
from tutor_api.services.learning_pack_evidence import _outcome


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ｃ、Ａ", "correct"),
        ("A, B", "incorrect"),
        ("A", "incorrect"),
        ("A, A", "unknown"),
        ("A or C", "unknown"),
        ("A,C,E", "unknown"),
    ],
)
def test_multiple_choice_paper_evidence_requires_explicit_options(text, expected):
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"options": [{"key": option} for option in "ABCD"]},
        answer_json={"value": ["A", "C"]},
    )
    manifest = {
        "revision": 1,
        "items": [
            {"code": "001", "question_version_id": "version", "answer_mode": "multiple_choice"}
        ],
    }
    assert _outcome(manifest, record, version, text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5 m/s²", "correct"),
        ("4 m/s²", "incorrect"),
        ("5", "incorrect"),
        ("5 ft/s²", "unknown"),
        ("5 或 6", "unknown"),
    ],
)
def test_numeric_single_blank_paper_evidence_reuses_unit_rules(text, expected):
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"blanks": [{"key": "b1"}]},
        answer_json={
            "value": {"b1": "5"},
            "equivalence_rules": {"b1": {"type": "numeric"}},
            "units": {"b1": {"required": True, "accepted": ["m/s²"]}},
        },
    )
    manifest = {
        "revision": 1,
        "items": [{"code": "001", "question_version_id": "version", "answer_mode": "fill"}],
    }
    assert _outcome(manifest, record, version, text) == expected


def test_numeric_paper_evidence_abstains_when_locked_answer_has_legacy_shape():
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"blanks": [{"key": "b1"}]},
        answer_json={"value": ["5"], "equivalence_rules": {"b1": {"type": "numeric"}}},
    )
    manifest = {
        "revision": 1,
        "items": [{"code": "001", "question_version_id": "version", "answer_mode": "fill"}],
    }
    assert _outcome(manifest, record, version, "5") == "unknown"
