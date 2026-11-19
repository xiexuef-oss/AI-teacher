"""Rebuild the paper review schedule from confirmed, versioned evidence."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from tutor_api.services.learning_pack_evidence import PaperEvidence

INTERVAL_DAYS = (3, 7, 14, 30)


@dataclass(frozen=True)
class PaperReview:
    stage: int
    due_on: date
    estimated_anchor: bool
    source_version: str


def _anchor(item: PaperEvidence) -> date:
    return item.completed_on or (item.confirmed_at + timedelta(hours=8)).date()


def rebuild(evidence: Iterable[PaperEvidence]) -> dict[str, PaperReview]:
    latest = {}
    for item in evidence:
        key = (item.pack_id, item.pack_revision, item.code)
        previous = latest.get(key)
        if previous is None or item.transcript_revision > previous.transcript_revision:
            latest[key] = item

    schedule: dict[str, PaperReview] = {}
    for item in sorted(
        latest.values(),
        key=lambda e: (
            _anchor(e),
            e.confirmed_at,
            e.pack_id,
            e.pack_revision,
            e.code,
        ),
    ):
        # Until solution access is tracked, a corrected transcript cannot prove
        # what the student answered independently before seeing the solution.
        if item.outcome == "unknown" or item.transcript_revision != 0:
            continue
        if item.outcome == "correct" and item.independence == "unknown":
            continue
        for node in set(item.knowledge_ids):
            previous = schedule.get(node)
            anchor = _anchor(item)
            independent_pass = item.outcome == "correct" and item.independence == "independent"
            if previous and independent_pass and anchor < previous.due_on:
                continue
            stage = (
                min(previous.stage + 1, len(INTERVAL_DAYS) - 1)
                if previous and independent_pass
                else 0
            )
            schedule[node] = PaperReview(
                stage,
                anchor + timedelta(days=INTERVAL_DAYS[stage]),
                item.completed_on is None,
                item.question_version_id,
            )
    return schedule
