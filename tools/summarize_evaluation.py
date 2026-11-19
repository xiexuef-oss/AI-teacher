"""Offline evaluation metadata summary. Never calls providers or reads item content."""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
for package in ("api", "ai_gateway"):
    sys.path.insert(0, str(ROOT / "services" / package))

from ai_gateway.dto import TaskType  # noqa: E402
from tutor_api.schemas import AnswerMode  # noqa: E402
from tutor_api.services.grading import SUBJECTIVE_MODES  # noqa: E402

Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_./:-]+$")]
Count = Annotated[int, Field(ge=0, le=2**63 - 1)]
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
USAGE_FIELDS = ("input_tokens", "output_tokens", "image_units", "estimated_cost_micros")


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: Label
    item_id: Label
    task_type: str
    answer_mode: AnswerMode
    provider: Label | None
    model: Label | None
    status: Literal["ok", "degraded", "error"]
    verdict: Literal["correct", "incorrect", "uncertain", "pending"]
    review_required: bool
    latency_ms: Count
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    image_units: Count | None = None
    estimated_cost_micros: Count | None = None

    @field_validator("task_type")
    @classmethod
    def supported_task(cls, value):
        if value not in {task.value for task in TaskType}:
            raise ValueError("unsupported task")
        return value

    @model_validator(mode="after")
    def verdict_boundary(self):
        if self.answer_mode in SUBJECTIVE_MODES and self.verdict != "pending":
            raise ValueError("subjective results must remain pending")
        if self.status != "ok" and self.verdict in {"correct", "incorrect"}:
            raise ValueError("failed/degraded calls cannot have a decisive verdict")
        return self


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _metrics(records):
    count = len(records)
    correct = sum(row.verdict == "correct" for row in records)
    decidable = sum(row.verdict in {"correct", "incorrect"} for row in records)
    latency = sorted(row.latency_ms for row in records)
    result = {
        "requests": count,
        "success_count": sum(row.status == "ok" for row in records),
        "success_rate": sum(row.status == "ok" for row in records) / count,
        "correct_count": correct,
        "decidable_count": decidable,
        "accuracy": correct / decidable if decidable else None,
        "uncertain_count": sum(row.verdict == "uncertain" for row in records),
        "pending_count": sum(row.verdict == "pending" for row in records),
        "review_rate": sum(row.review_required for row in records) / count,
        "latency_ms": {
            "average": sum(latency) / count,
            "p95": latency[math.ceil(0.95 * count) - 1],
        },
    }
    for field in USAGE_FIELDS:
        known = [getattr(row, field) for row in records if getattr(row, field) is not None]
        unknown = count - len(known)
        result[field] = {
            "total": None if unknown else sum(known),
            "known_total": sum(known),
            "unknown_count": unknown,
        }
    return result


def read_results(path):
    rows, errors, identifiers = [], [], set()
    try:
        with Path(path).open("rb") as source:
            number = 0
            while raw := source.readline(MAX_LINE_BYTES + 1):
                number += 1
                if len(raw) > MAX_LINE_BYTES or number > MAX_RECORDS:
                    errors.append({"line": number, "code": "resource_limit"})
                    break
                try:
                    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object)
                    row = EvaluationResult.model_validate(data)
                    if row.request_id in identifiers:
                        errors.append({"line": number, "code": "duplicate_request_id"})
                    identifiers.add(row.request_id)
                    rows.append(row)
                except (ValueError, UnicodeError, ValidationError, RecursionError):
                    errors.append({"line": number, "code": "invalid_record"})
    except OSError:
        errors.append({"line": None, "code": "unreadable_file"})
    if not rows and not errors:
        errors.append({"line": None, "code": "empty_results"})
    return rows, errors


def summarize(path):
    rows, errors = read_results(path)
    if errors:
        return {"valid": False, "errors": errors, "overall": None, "groups": []}
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.task_type, row.provider, row.model)].append(row)
    return {
        "valid": True,
        "errors": [],
        "overall": _metrics(rows),
        "groups": [
            {"task_type": key[0], "provider": key[1], "model": key[2], **_metrics(grouped[key])}
            for key in sorted(grouped, key=lambda key: tuple(value or "" for value in key))
        ],
        "cost_disclaimer": "Estimates only; not invoices. Missing usage remains unknown.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="Authorized evaluation metadata JSONL")
    args = parser.parse_args()
    report = summarize(args.results)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
