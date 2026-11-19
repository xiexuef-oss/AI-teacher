"""Check sample teaching registration against docs/07; never inspect source materials."""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
for directory in ("services/api", "services/ai_gateway"):
    sys.path.insert(0, str(ROOT / directory))

from tutor_api.schemas import AdminImportSourceIn  # noqa: E402
from tutor_api.services.content_seed import ENGINEERING_SAMPLE_LICENSE  # noqa: E402

TOPICS = {
    "math.function_monotonicity": "函数与单调性",
    "math.basic_inequality": "基本不等式",
    "math.proof": "证明",
    "physics.force_motion": "受力与运动",
    "physics.circuit": "电路",
    "physics.experiment": "物理实验",
    "chemistry.conservation": "守恒计算",
    "chemistry.inference": "物质推断",
    "chemistry.experiment": "化学实验",
}
FIELDS = [
    "question_id",
    "question_version",
    "topic_codes",
    "source_type",
    "source_name",
    "source_license",
    "license_evidence",
    "author_id",
    "reviewer_id",
    "reviewed_at",
    "review_evidence",
    "standard_solution_ref",
    "variant_1_ref",
    "variant_1_review_evidence",
    "variant_2_ref",
    "variant_2_review_evidence",
    "is_engineering_sample",
]


def _question_id(reference):
    identifier, separator, version = reference.partition("@")
    if (
        not separator
        or str(UUID(identifier)) != identifier
        or not version.isascii()
        or not version.isdigit()
        or version.startswith("0")
    ):
        raise ValueError("Expected canonical question UUID and positive version")
    return identifier


def _report(counts, excluded, errors, *, valid_samples=0):
    topics = [
        {
            "topic_code": code,
            "label": label,
            "valid_samples": counts[code],
            "minimum_samples": 5,
            "missing_samples": max(0, 5 - counts[code]),
        }
        for code, label in TOPICS.items()
    ]
    return {
        "registration_complete": not errors
        and all(topic["missing_samples"] == 0 for topic in topics),
        "scope": "registration_metadata_only",
        "valid_samples": valid_samples,
        "excluded_engineering_samples": excluded,
        "topics": topics,
        "errors": errors,
    }


def check_coverage(path):
    counts, excluded, errors = Counter(), 0, []
    valid_samples = 0
    try:
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            return _report(counts, excluded, [{"code": "metadata_size_limit"}])
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if reader.fieldnames != FIELDS:
                return _report(counts, excluded, [{"code": "invalid_columns"}])
            rows = []
            for row in reader:
                if len(rows) >= 10_000:
                    return _report(counts, excluded, [{"code": "metadata_row_limit"}])
                rows.append(row)
    except (OSError, ValueError, csv.Error):
        return _report(counts, excluded, [{"code": "unreadable_or_invalid_metadata"}])
    identifiers = Counter((row.get("question_id") or "").strip() for row in rows)
    sources = get_args(AdminImportSourceIn.model_fields["source_type"].annotation)
    for number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            errors.append({"row": number, "code": "invalid_column_count"})
            continue
        row = {key: value.strip() for key, value in row.items()}
        if (
            row["is_engineering_sample"] == "true"
            or row["source_license"] == ENGINEERING_SAMPLE_LICENSE
        ):
            excluded += 1
            continue
        try:
            parent = _question_id(row["question_id"] + "@" + row["question_version"])
            variants = {_question_id(row[f"variant_{i}_ref"]) for i in (1, 2)}
            topics = [code.strip() for code in row["topic_codes"].split(";")]
            reviewed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            valid = (
                all(row.values())
                and row["is_engineering_sample"] == "false"
                and row["source_type"] in sources
                and all(code in TOPICS for code in topics)
                and len(topics) == len(set(topics))
                and len({code.split(".")[0] for code in topics}) == 1
                and identifiers[parent] == 1
                and parent not in variants
                and len(variants) == 2
                and row["author_id"] != row["reviewer_id"]
                and reviewed.tzinfo is not None
                and reviewed <= datetime.now(UTC)
            )
        except (ValueError, TypeError, OverflowError):
            valid = False
        if valid:
            counts.update(topics)
            valid_samples += 1
        else:
            errors.append({"row": number, "code": "invalid_sample_metadata"})
    return _report(counts, excluded, errors, valid_samples=valid_samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest", nargs="?", type=Path, default=ROOT / "content/sample_content_manifest.csv"
    )
    args = parser.parse_args()
    report = check_coverage(args.manifest)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report["registration_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
