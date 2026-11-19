"""Render and store a whole pack under the worker's current lease."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_hex

from sqlalchemy.orm import Session

from tutor_api.models import LearningPackPublication
from tutor_api.services.learning_jobs import finish, has_active_lease
from tutor_api.services.learning_pack_pdf import (
    PaperItem,
    SolutionItem,
    render_solutions,
    render_student,
)


@dataclass(frozen=True)
class PrintedQuestion:
    question_version_id: str
    stem: str
    solution: str
    answer_mode: str | None = None
    knowledge_ids: tuple[str, ...] = ()
    suggested_on: str | None = None


def publish(
    db: Session, job_id: str, lease: str, questions: list[PrintedQuestion], font: Path, clock
) -> bool:
    """Stage both PDFs and the status update in the caller's transaction."""
    if not questions or any(not q.stem.strip() or not q.solution.strip() for q in questions):
        raise ValueError("Every printed question needs a stem and a solution")
    if not has_active_lease(db, job_id, lease, clock()):
        return False
    student_items, solution_items, manifest = [], [], []
    for index, question in enumerate(questions, start=1):
        code = f"{index:03d}"
        token = token_hex(16)
        stem = question.stem
        if question.suggested_on:
            stem = f"建议作答日 {question.suggested_on}\n{stem}"
        student_items.append(PaperItem(code, token, stem))
        solution_items.append(SolutionItem(code, question.solution))
        manifest.append(
            {
                "code": code,
                "page_token": token,
                "question_version_id": question.question_version_id,
                "answer_mode": question.answer_mode,
                "knowledge_ids": list(question.knowledge_ids),
                "suggested_on": question.suggested_on,
            }
        )
    label = f"{job_id.split('-')[0]}  v1"
    continuation_tokens: dict[str, list[str]] = {}
    student = render_student(
        student_items, font, label=label, continuation_tokens=continuation_tokens
    )
    if not has_active_lease(db, job_id, lease, clock()):
        return False
    for row in manifest:
        row["continuation_tokens"] = continuation_tokens.get(row["code"], [])
    solutions = render_solutions(solution_items, font, label=label)
    if max(len(student), len(solutions)) >= 2**24:
        raise ValueError("Learning pack PDF is too large")
    if not finish(db, job_id, lease, clock(), success=True):
        return False
    db.add(
        LearningPackPublication(
            job_id=job_id,
            student_pdf=student,
            solution_pdf=solutions,
            manifest_json={
                "revision": 1,
                "items": manifest,
                "student_sha256": sha256(student).hexdigest(),
                "solution_sha256": sha256(solutions).hexdigest(),
            },
        )
    )
    db.flush()
    return True
