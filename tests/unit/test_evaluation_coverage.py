import csv
import json
import subprocess
import sys
from hashlib import sha256

import check_evaluation_coverage as coverage_tool
import pytest
from check_evaluation_coverage import check_coverage
from validate_evaluation_manifest import FIELDS


def files(tmp_path, results):
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for item in ("one", "two"):
            record = dict.fromkeys(FIELDS, "")
            record.update(
                item_id=item,
                subject="math",
                question_type="fill",
                answer_mode="fill",
                modality="text",
                difficulty="2",
                source_type="self_authored",
                source_name="private-source",
                source_license="engineering-only",
                license_evidence="private-license",
                reviewer="private-reviewer",
                reviewed_at="2026-11-17T00:00:00Z",
                answer_key_ref="private-answer",
            )
            writer.writerow(record)
    path = tmp_path / "results.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "request_id": f"r-{index}",
                    "item_id": item,
                    "task_type": "ocr_extract",
                    "answer_mode": "fill",
                    "provider": "fixture",
                    "model": model,
                    "status": "ok",
                    "verdict": "uncertain",
                    "review_required": True,
                    "latency_ms": 1,
                }
            )
            for index, (item, model) in enumerate(results)
        ),
        encoding="utf-8",
    )
    return manifest, path


def test_distinct_items_not_requests_and_models_are_separate(tmp_path):
    for rows, ready, missing in [
        ([("one", "m"), ("two", "m")], True, [0]),
        ([("one", "m")] * 20, False, [1]),
        ([("one", "a"), ("two", "b")], False, [1, 1]),
    ]:
        manifest, results = files(tmp_path, rows)
        report = check_coverage(manifest, results, minimum=2)
        assert report["ready"] is ready
        assert [g["missing_items"] for g in report["groups"]] == missing
        assert "private" not in json.dumps(report)
    assert not check_coverage(manifest, results)["ready"]  # Default remains 300.


def test_coverage_records_input_digests_without_disclosing_metadata(tmp_path):
    manifest, results = files(tmp_path, [("one", "m"), ("two", "m")])
    report = check_coverage(manifest, results, minimum=2)
    assert report["manifest_sha256"] == sha256(manifest.read_bytes()).hexdigest()
    assert report["results_sha256"] == sha256(results.read_bytes()).hexdigest()
    assert "private" not in json.dumps(report)
    with results.open("a", encoding="utf-8") as output:
        output.write("\n")
    updated = check_coverage(manifest, results, minimum=2)
    assert updated["ready"] and updated["manifest_sha256"] == report["manifest_sha256"]
    assert updated["results_sha256"] != report["results_sha256"]


def test_coverage_rejects_results_updated_during_validation(tmp_path, monkeypatch):
    manifest, results = files(tmp_path, [("one", "m"), ("two", "m")])
    read_results = coverage_tool.read_results

    def read_then_append(path):
        rows = read_results(path)
        with path.open("a", encoding="utf-8") as output:
            output.write("\n")
        return rows

    monkeypatch.setattr(coverage_tool, "read_results", read_then_append)
    report = check_coverage(manifest, results, minimum=2)
    assert not report["ready"]
    assert report["code"] == "metadata_changed_during_check"


@pytest.mark.parametrize(
    "change", [{"item_id": "private-unknown"}, {"answer_mode": "single_choice"}, {"model": None}]
)
def test_unregistered_mismatched_or_unidentified_results_cannot_pass(tmp_path, change):
    manifest, results = files(tmp_path, [("one", "m"), ("two", "m")])
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    rows[0].update(change)
    if change == {"model": None}:
        rows[1].update(change)
    results.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    report = check_coverage(manifest, results, minimum=2)
    assert not report["ready"]
    assert "private" not in json.dumps(report)


def test_cli_defaults_and_failures(tmp_path):
    manifest, results = files(tmp_path, [("one", "m"), ("two", "m")])
    command = [sys.executable, "tools/check_evaluation_coverage.py", str(manifest), str(results)]
    for options, expected in [
        ([], 1),
        (["--minimum", "2"], 0),
        (["--minimum", "2", "--require-group", "ocr_extract", "fixture", "m"], 0),
        (["--minimum", "2", "--require-group", "ocr_extract", "fixture", "absent"], 1),
    ]:
        result = subprocess.run(command + options, capture_output=True, text=True, check=False)
        assert result.returncode == expected
        assert json.loads(result.stdout)["ready"] is (expected == 0)
    results.write_text('{"private":"malformed"}', encoding="utf-8")
    assert not check_coverage(manifest, results, minimum=2)["ready"]


def test_expected_but_absent_model_counts_as_missing(tmp_path):
    manifest, results = files(tmp_path, [("one", "m"), ("two", "m")])
    report = check_coverage(
        manifest,
        results,
        minimum=2,
        required_groups=[("ocr_extract", "fixture", "absent")],
    )
    assert not report["ready"]
    assert [(group["model"], group["missing_items"]) for group in report["groups"]] == [
        ("absent", 2),
        ("m", 0),
    ]
