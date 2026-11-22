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


@pytest.mark.parametrize(
    "answer",
    [
        {"value": ["5"], "equivalence_rules": {"b1": {"type": "numeric"}}},
        {"value": {"b1": "5"}, "equivalence_rules": {"b1": "numeric"}},
        {
            "value": {"b1": "5"},
            "equivalence_rules": {"b1": {"type": "numeric"}},
            "units": {"b1": "m"},
        },
    ],
)
def test_numeric_paper_evidence_abstains_when_locked_answer_has_legacy_shape(answer):
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"blanks": [{"key": "b1"}]},
        answer_json=answer,
    )
    manifest = {
        "revision": 1,
        "items": [{"code": "001", "question_version_id": "version", "answer_mode": "fill"}],
    }
    assert _outcome(manifest, record, version, "5") == "unknown"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(-∞,2]", "correct"),
        ("(-∞,3]", "incorrect"),
        ("x ≤ 2", "unknown"),
    ],
)
def test_interval_paper_evidence_requires_a_recognized_interval(text, expected):
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"blanks": [{"key": "b1"}]},
        answer_json={
            "value": {"b1": "(-inf,2]"},
            "equivalence_rules": {"b1": {"type": "interval"}},
        },
    )
    manifest = {
        "revision": 1,
        "items": [{"code": "001", "question_version_id": "version", "answer_mode": "fill"}],
    }
    assert _outcome(manifest, record, version, text) == expected


@pytest.mark.parametrize(
    ("blanks", "values", "rules", "text"),
    [
        (["b1"], {"b1": "x/x"}, {"b1": {"type": "expression", "variables": ["x"]}}, "1"),
        (["b1", "b2"], {"b1": "1", "b2": "2"}, {"b1": {"type": "numeric"}}, "1, 2"),
    ],
)
def test_paper_fill_abstains_when_transcript_does_not_support_reliable_grading(
    blanks, values, rules, text
):
    record = LearningPackReturn(code="001", revision=1, question_version_id="version")
    version = QuestionVersion(
        content_json={"blanks": [{"key": key} for key in blanks]},
        answer_json={"value": values, "equivalence_rules": rules},
    )
    manifest = {
        "revision": 1,
        "items": [{"code": "001", "question_version_id": "version", "answer_mode": "fill"}],
    }
    assert _outcome(manifest, record, version, text) == "unknown"
