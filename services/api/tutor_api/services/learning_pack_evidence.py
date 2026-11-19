"""Current paper evidence, with conservative objective practice assessment."""

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from tutor_api.models import (
    LearningJob,
    LearningPackCorrection,
    LearningPackPublication,
    LearningPackReturn,
    LearningPackReturnDetails,
    QuestionVersion,
)
from tutor_api.services import grading

Outcome = Literal["unknown", "correct", "incorrect"]


@dataclass(frozen=True)
class PaperEvidence:
    pack_id: str
    code: str
    pack_revision: int
    question_version_id: str
    transcript: str
    transcript_revision: int
    confirmed_at: datetime
    completed_on: date | None
    independence: str
    outcome: Outcome = "unknown"
    knowledge_ids: tuple[str, ...] = ()


def _printed_item(manifest: dict, record: LearningPackReturn) -> dict:
    if manifest["revision"] != record.revision:
        return {}
    return next(
        (
            item
            for item in manifest["items"]
            if item["code"] == record.code
            and item["question_version_id"] == record.question_version_id
        ),
        {},
    )


def _numeric_fill_outcome(version: QuestionVersion, text: str) -> Outcome:
    blanks = version.content_json.get("blanks") or []
    if len(blanks) != 1 or not text.strip():
        return "unknown"
    key = blanks[0]["key"]
    answer = version.answer_json
    rule = (answer.get("equivalence_rules") or {}).get(key) or {}
    values = answer.get("value")
    if not isinstance(values, dict):
        return "unknown"
    expected = values.get(key)
    if rule.get("type") != "numeric" or not isinstance(expected, str):
        return "unknown"
    try:
        outcome = grading.check_blank(rule, expected, (answer.get("units") or {}).get(key), text)
    except (ValueError, ArithmeticError):
        return "unknown"
    if outcome.status == "correct":
        return "correct"
    return "incorrect" if outcome.status == "incorrect" else "unknown"


def _outcome(
    manifest: dict, record: LearningPackReturn, version: QuestionVersion, text: str
) -> Outcome:
    mode = _printed_item(manifest, record).get("answer_mode")
    if mode == "fill":
        return _numeric_fill_outcome(version, text)
    if mode not in ("single_choice", "multiple_choice"):
        return "unknown"
    # Accept only explicit keys. Prose and ambiguous separators require review.
    normalized = unicodedata.normalize("NFKC", text).strip().upper()
    selected = (
        [part.strip() for part in normalized.replace("、", ",").split(",")]
        if mode == "multiple_choice"
        else [normalized]
    )
    options = {option["key"] for option in version.content_json.get("options", [])}
    answer = version.answer_json.get("value")
    if (
        any(key not in options for key in selected)
        or len(set(selected)) != len(selected)
        or not isinstance(answer, list)
        or not answer
        or (mode == "single_choice" and len(answer) != 1)
        or any(not isinstance(key, str) or key not in options for key in answer)
        or len(set(answer)) != len(answer)
    ):
        return "unknown"
    result = grading.grade(
        answer_mode=mode,
        content=version.content_json,
        answer_key=version.answer_json,
        rubric={},
        teaching={},
        answer={"selected_options": selected},
    )
    if result.state != "verified" or result.is_correct is None:
        return "unknown"
    return "correct" if result.is_correct else "incorrect"


def paper_evidence(
    db: Session,
    student_id: str,
    *,
    pack_id: str | None = None,
    code: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[PaperEvidence]:
    original = LearningPackReturn
    correction = LearningPackCorrection
    details = LearningPackReturnDetails
    candidate = aliased(correction)
    latest = (
        select(func.max(candidate.revision))
        .where(candidate.job_id == original.job_id, candidate.code == original.code)
        .correlate(original)
        .scalar_subquery()
    )
    query = (
        select(
            original, correction, details, LearningPackPublication.manifest_json, QuestionVersion
        )
        .join(LearningJob, LearningJob.id == original.job_id)
        .join(LearningPackPublication, LearningPackPublication.job_id == original.job_id)
        .join(QuestionVersion, QuestionVersion.id == original.question_version_id)
        .outerjoin(
            correction,
            and_(
                correction.job_id == original.job_id,
                correction.code == original.code,
                correction.revision == latest,
            ),
        )
        .outerjoin(details, and_(details.job_id == original.job_id, details.code == original.code))
        .where(LearningJob.student_id == student_id, LearningJob.status == "succeeded")
        .order_by(original.confirmed_at, original.job_id, original.code)
    )
    if pack_id is not None:
        query = query.where(original.job_id == pack_id)
    if code is not None:
        query = query.where(original.code == code)
    if since is not None:
        query = query.where(original.confirmed_at >= since)
    if until is not None:
        query = query.where(original.confirmed_at < until)
    return [
        PaperEvidence(
            record.job_id,
            record.code,
            record.revision,
            record.question_version_id,
            change.transcript if change else record.transcript,
            change.revision if change else 0,
            record.confirmed_at,
            metadata.completed_on if metadata else None,
            metadata.independence if metadata else "unknown",
            _outcome(manifest, record, version, change.transcript if change else record.transcript),
            tuple(_printed_item(manifest, record).get("knowledge_ids", ())),
        )
        for record, change, metadata, manifest, version in db.execute(query)
    ]
