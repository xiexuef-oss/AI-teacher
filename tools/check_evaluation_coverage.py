"""Offline metadata coverage check; never reads questions or calls a provider."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from summarize_evaluation import read_results
from validate_evaluation_manifest import validate_manifest


def check_coverage(manifest, results, *, minimum=300):
    failure = {"ready": False, "groups": []}
    try:
        registration = validate_manifest(manifest, minimum=minimum)
        if not registration["ready"]:
            return {**failure, "code": "incomplete_registration"}
        rows, errors = read_results(results)
        if errors:
            return {**failure, "code": "invalid_results"}
        with Path(manifest).open(encoding="utf-8-sig", newline="") as source:
            expected = {
                row["item_id"].strip(): row["answer_mode"].strip() for row in csv.DictReader(source)
            }
        groups = defaultdict(set)
        for row in rows:
            if row.provider is None or row.model is None:
                return {**failure, "code": "unidentified_model"}
            if expected.get(row.item_id) != row.answer_mode:
                return {**failure, "code": "unregistered_or_mismatched_item"}
            groups[(row.task_type, row.provider, row.model)].add(row.item_id)
    except (OSError, ValueError, csv.Error, RecursionError):
        return {**failure, "code": "unreadable_or_invalid_metadata"}
    coverage = [
        {
            "task_type": key[0],
            "provider": key[1],
            "model": key[2],
            "evaluated_items": len(items),
            "missing_items": len(expected.keys() - items),
        }
        for key, items in sorted(groups.items(), key=lambda pair: tuple(v or "" for v in pair[0]))
    ]
    return {
        "ready": bool(coverage) and all(group["missing_items"] == 0 for group in coverage),
        "registered_items": len(expected),
        "minimum": minimum,
        "groups": coverage,
        "disclaimer": "Metadata coverage only; does not verify licenses, quality or release approval.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--minimum", type=int, default=300)
    args = parser.parse_args()
    if args.minimum < 1:
        parser.error("minimum must be positive")
    report = check_coverage(args.manifest, args.results, minimum=args.minimum)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
