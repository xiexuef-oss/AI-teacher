import csv
import json
from uuid import uuid4

import pytest
from check_sample_content_coverage import FIELDS, TOPICS, check_coverage, main

from tutor_api.services.content_seed import ENGINEERING_SAMPLE_LICENSE


def sample(topic):
    return dict(
        question_id=str(uuid4()),
        question_version="1",
        topic_codes=topic,
        source_type="self_authored",
        source_name="Self authored metadata fixture",
        source_license="self-authored-test-license",
        license_evidence="private/license",
        author_id="author-a",
        reviewer_id="reviewer-b",
        reviewed_at="2026-01-01T00:00:00+08:00",
        review_evidence="private/review/version-1",
        standard_solution_ref="private/standard/version-1",
        variant_1_ref=f"{uuid4()}@1",
        variant_1_review_evidence="private/variant-one-review",
        variant_2_ref=f"{uuid4()}@1",
        variant_2_review_evidence="private/variant-two-review",
        is_engineering_sample="false",
    )


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def full_registration():
    return [sample(topic) for topic in TOPICS for _ in range(5)]


def test_current_empty_registration_shows_all_nine_topic_gaps():
    report = check_coverage("content/sample_content_manifest.csv")
    assert report["registration_complete"] is False
    assert report["valid_samples"] == 0
    assert report["errors"] == []
    assert len(report["topics"]) == 9
    assert all(topic["missing_samples"] == 5 for topic in report["topics"])


def test_complete_metadata_has_topic_coverage_but_no_release_approval(tmp_path):
    report = check_coverage(write(tmp_path / "samples.csv", full_registration()))
    assert report["registration_complete"] is True
    assert report["valid_samples"] == 45
    assert all(topic["valid_samples"] == 5 for topic in report["topics"])
    assert report["scope"] == "registration_metadata_only"


@pytest.mark.parametrize(
    "change",
    [
        {"author_id": "reviewer-b"},
        {"source_name": ""},
        {"license_evidence": ""},
        {"review_evidence": ""},
        {"standard_solution_ref": ""},
        {"variant_1_review_evidence": ""},
        {"variant_2_review_evidence": ""},
        {"question_id": "not-a-uuid"},
        {"question_version": "0"},
        {"question_version": "01"},
        {"variant_1_ref": "unversioned-question"},
        {"is_engineering_sample": "unknown"},
        {"reviewed_at": "2026-01-01"},
        {"reviewed_at": "2100-01-01T00:00:00+08:00"},
        {"source_type": "unapproved-source"},
        {"topic_codes": "unknown-topic"},
    ],
)
def test_incomplete_or_unbound_sample_does_not_count(tmp_path, change):
    row = sample(next(iter(TOPICS)))
    row.update(change)
    report = check_coverage(write(tmp_path / "samples.csv", [row]))
    assert report["valid_samples"] == 0
    assert report["errors"]


@pytest.mark.parametrize("duplicate", ["parent", "same_variant", "same_id_new_version"])
def test_variants_must_be_two_distinct_questions_other_than_parent(tmp_path, duplicate):
    row = sample(next(iter(TOPICS)))
    row["variant_2_ref"] = (
        row["variant_1_ref"]
        if duplicate == "same_variant"
        else row["variant_1_ref"].split("@")[0] + "@2"
        if duplicate == "same_id_new_version"
        else row["question_id"] + "@2"
    )
    report = check_coverage(write(tmp_path / "samples.csv", [row]))
    assert report["valid_samples"] == 0


def test_repeated_versions_cannot_multiply_sample_count(tmp_path):
    row = sample(next(iter(TOPICS)))
    rows = [{**row, "question_version": str(i)} for i in range(1, 6)]
    report = check_coverage(write(tmp_path / "samples.csv", rows))
    assert report["valid_samples"] == 0
    assert report["registration_complete"] is False


@pytest.mark.parametrize("flag", ["true", "false"])
def test_known_engineering_license_never_becomes_formal_sample(tmp_path, flag):
    row = sample(next(iter(TOPICS)))
    row.update(source_license=ENGINEERING_SAMPLE_LICENSE, is_engineering_sample=flag)
    report = check_coverage(write(tmp_path / "samples.csv", [row]))
    assert report["valid_samples"] == 0
    assert report["excluded_engineering_samples"] == 1


def test_explicit_sample_flag_excludes_even_other_license(tmp_path):
    row = sample(next(iter(TOPICS)))
    row["is_engineering_sample"] = "true"
    report = check_coverage(write(tmp_path / "samples.csv", [row]))
    assert report["excluded_engineering_samples"] == 1
    assert report["valid_samples"] == 0


def test_many_samples_in_one_topic_do_not_fill_other_topics(tmp_path):
    rows = [sample(next(iter(TOPICS))) for _ in range(45)]
    report = check_coverage(write(tmp_path / "samples.csv", rows))
    assert report["registration_complete"] is False
    assert sum(topic["missing_samples"] for topic in report["topics"]) == 40


def test_one_question_can_cover_two_declared_topics_without_becoming_two_questions(tmp_path):
    row = sample(";".join(list(TOPICS)[:2]))
    report = check_coverage(write(tmp_path / "samples.csv", [row]))
    assert report["valid_samples"] == 1
    assert sum(topic["valid_samples"] for topic in report["topics"]) == 2


@pytest.mark.parametrize("topics", ["math.proof;math.proof", "math.proof;physics.force_motion"])
def test_duplicate_or_cross_subject_topic_declarations_are_invalid(tmp_path, topics):
    report = check_coverage(write(tmp_path / "samples.csv", [sample(topics)]))
    assert report["valid_samples"] == 0
    assert report["errors"]


def test_cli_never_echoes_private_metadata_and_fails_empty_input(tmp_path, monkeypatch, capsys):
    row = sample(next(iter(TOPICS)))
    row.update(
        author_id="PRIVATE-IDENTITY",
        license_evidence="PRIVATE-LICENSE",
        reviewed_at="PRIVATE-INVALID",
    )
    path = write(tmp_path / "private.csv", [row])
    monkeypatch.setattr("sys.argv", ["check_sample_content_coverage", str(path)])
    assert main() == 1
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert json.loads(output)["registration_complete"] is False


@pytest.mark.parametrize(
    "body",
    ["wrong,header\n", ",".join(["question_id"] * len(FIELDS)), ",".join(FIELDS) + "\nshort,row\n"],
)
def test_invalid_csv_is_a_fixed_safe_failure(tmp_path, body):
    path = tmp_path / "bad.csv"
    path.write_text(body, encoding="utf-8")
    report = check_coverage(path)
    assert report["registration_complete"] is False
    assert report["valid_samples"] == 0
    assert report["errors"]


@pytest.mark.parametrize("failure", ["missing", "invalid_utf8", "oversized", "too_many_rows"])
def test_unreadable_or_unbounded_metadata_fails_without_echo(tmp_path, failure):
    path = tmp_path / "PRIVATE-REGISTRATION.csv"
    if failure == "invalid_utf8":
        path.write_bytes(b"\xffPRIVATE")
    elif failure == "oversized":
        path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    elif failure == "too_many_rows":
        write(path, [dict.fromkeys(FIELDS, "")] * 10_001)
    report = check_coverage(path)
    assert report["registration_complete"] is False
    assert report["valid_samples"] == 0
    assert report["errors"]
    assert "PRIVATE" not in json.dumps(report)


def test_cli_success_means_metadata_only(tmp_path, monkeypatch, capsys):
    path = write(tmp_path / "samples.csv", full_registration())
    monkeypatch.setattr("sys.argv", ["check_sample_content_coverage", str(path)])
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["registration_complete"] is True
    assert report["scope"] == "registration_metadata_only"
