import csv

from validate_evaluation_manifest import validate_manifest


def test_empty_template_is_not_a_release_ready_dataset():
    report = validate_manifest("evaluation/golden_dataset_manifest.csv", minimum=300)
    assert not report["ready"] and report["valid_items"] == 0
    assert any("300" in error for error in report["errors"])


def test_missing_authorization_and_duplicate_ids_are_rejected(tmp_path):
    with open("evaluation/golden_dataset_manifest.csv", encoding="utf-8-sig") as source:
        fields = next(csv.reader(source))
    path = tmp_path / "manifest.csv"
    row = dict.fromkeys(fields, "")
    row.update(
        item_id="self-test", subject="math", answer_mode="fill", modality="text", difficulty="2"
    )
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows([row, row])
    report = validate_manifest(path, minimum=1)
    assert not report["ready"] and report["valid_items"] == 0
    assert any("license_evidence" in error for error in report["errors"])
    assert any("重复" in error for error in report["errors"])


def test_complete_registration_is_valid_but_does_not_verify_license_contents(tmp_path):
    with open("evaluation/golden_dataset_manifest.csv", encoding="utf-8-sig") as source:
        fields = next(csv.reader(source))
    row = dict.fromkeys(fields, "")
    row.update(
        item_id="engineering-example",
        subject="math",
        question_type="fill",
        answer_mode="fill",
        modality="text",
        difficulty="2",
        source_type="self_authored",
        source_name="自编测试登记",
        source_license="internal-engineering-sample",
        license_evidence="private/authorization-reference",
        reviewer="test-reviewer",
        reviewed_at="2026-11-15T10:00:00+08:00",
        answer_key_ref="private/answer-reference",
    )
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    report = validate_manifest(path, minimum=1)
    assert report["ready"] and report["valid_items"] == 1
    assert report["subjects"] == {"math": 1}
    row.update(answer_mode="proof")
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    assert not validate_manifest(path, minimum=1)["ready"]
