"""离线检查评测登记完整性；不读取试卷、不联网，也不代替版权或学科审查。"""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

FIELDS = [
    "item_id",
    "subject",
    "question_type",
    "answer_mode",
    "modality",
    "region_code",
    "exam_year",
    "knowledge_codes",
    "difficulty",
    "source_type",
    "source_name",
    "source_year",
    "source_license",
    "license_evidence",
    "reviewer",
    "reviewed_at",
    "answer_key_ref",
    "rubric_ref",
    "notes",
]
REQUIRED = [
    "item_id",
    "subject",
    "question_type",
    "answer_mode",
    "modality",
    "difficulty",
    "source_type",
    "source_name",
    "source_license",
    "license_evidence",
    "reviewer",
    "reviewed_at",
    "answer_key_ref",
]


def validate_manifest(path, *, minimum=300):
    errors, valid, counts = [], 0, Counter()
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            return {
                "ready": False,
                "valid_items": 0,
                "subjects": {},
                "errors": ["登记表列名或顺序与模板不一致"],
            }
        rows = list(reader)
    identifiers = Counter(row.get("item_id", "").strip() for row in rows)
    for index, row in enumerate(rows, start=2):
        problems = []
        if None in row or any(value is None for value in row.values()):
            errors.append(f"第{index}行：CSV列数错误")
            continue
        row = {key: value.strip() for key, value in row.items()}
        problems.extend(f"缺少 {field}" for field in REQUIRED if not row[field])
        if identifiers[row["item_id"]] > 1:
            problems.append("item_id 重复")
        for field, allowed in {
            "subject": {"math", "physics", "chemistry"},
            "answer_mode": {
                "single_choice",
                "multiple_choice",
                "fill",
                "written",
                "experiment",
                "proof",
            },
            "modality": {"text", "image", "handwriting", "chart"},
            "difficulty": {"1", "2", "3", "4", "5"},
        }.items():
            if row[field] not in allowed:
                problems.append(f"{field} 无效")
        if row["answer_mode"] in {"written", "experiment", "proof"} and not row["rubric_ref"]:
            problems.append("主观题缺少 rubric_ref 自查/人工评测依据")
        for field in ("exam_year", "source_year"):
            if row[field] and (not row[field].isdigit() or not 1900 <= int(row[field]) <= 2100):
                problems.append(f"{field} 无效")
        try:
            reviewed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            if reviewed.tzinfo is None:
                problems.append("reviewed_at 必须含时区")
        except ValueError:
            problems.append("reviewed_at 无效")
        if problems:
            errors.extend(f"第{index}行：{problem}" for problem in problems)
        else:
            valid += 1
            counts[row["subject"]] += 1
    if valid < minimum:
        errors.append(f"有效登记 {valid} 道，未达到要求的 {minimum} 道")
    return {"ready": not errors, "valid_items": valid, "subjects": dict(counts), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", default="evaluation/golden_dataset_manifest.csv")
    parser.add_argument("--minimum", type=int, default=300)
    args = parser.parse_args()
    if args.minimum < 1:
        parser.error("minimum 必须为正数")
    report = validate_manifest(args.manifest, minimum=args.minimum)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
