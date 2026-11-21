"""Local learning-pack preparation worker using the database as its queue."""

import logging
import re
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from sqlalchemy import and_, or_, select, update

from tutor_api.models import (
    AuditLog,
    LearningJob,
    LearningPackCommand,
    LearningPackPublication,
    LearningPackReturn,
    Question,
    QuestionKnowledge,
    QuestionVersion,
    Solution,
    User,
)
from tutor_api.services.content_seed import ENGINEERING_SAMPLE_NAME, seed_uuid
from tutor_api.services.learning_budget import remaining_minutes
from tutor_api.services.learning_jobs import claim, finish, has_active_lease
from tutor_api.services.learning_pack_evidence import paper_evidence
from tutor_api.services.learning_pack_outbox import RedisPaperQueue, deliver_one
from tutor_api.services.learning_pack_photo_worker import (
    process_photo_ocr,
    purge_expired_candidates,
)
from tutor_api.services.learning_pack_publication import PrintedQuestion, publish
from tutor_api.services.paper_review_schedule import rebuild
from tutor_api.services.question_service import is_engineering_sample
from tutor_api.services.school_material_worker import process_one, purge_expired_results
from tutor_api.services.weekly_snapshots import generate_due_snapshots

logger = logging.getLogger(__name__)
SAMPLE_MINUTES = 5
PAPER_SAMPLES = (
    ("chemistry", "chem-process-reading"),
    ("physics", "phys-force-analysis"),
    ("physics", "phys-incline-accel"),
    ("math", "math-mono-quadratic-v1"),
    ("math", "math-mono-quadratic"),
    ("math", "math-ineq-product-v1"),
    ("math", "math-ineq-rect"),
    ("chemistry", "chem-conservation-co2"),
    ("chemistry", "chem-conservation-h2"),
)
DUE_ONLY_SAMPLES = {
    "phys-incline-accel",
    "math-mono-quadratic",
    "math-ineq-rect",
    "chem-conservation-h2",
}


def _sample_question(db, key):
    question = db.get(Question, seed_uuid("question", key))
    if question is None or (
        question.status != "published"
        or question.version != 1
        or question.source_name != ENGINEERING_SAMPLE_NAME
        or not is_engineering_sample(question)
    ):
        return None
    version = db.get(QuestionVersion, seed_uuid("question_version", f"{key}:1"))
    solution = db.get(Solution, seed_uuid("solution", f"{key}:1:standard"))
    if version is None or solution is None:
        return None
    content = version.content_json
    options = [f"{item['key']}. {item['text']}" for item in content.get("options", [])]
    stem = "\n".join(["自编工程样题", content["stem"], *options])
    explanation = "\n".join(
        [*solution.content_json["steps"], solution.content_json["final_answer"]]
    )
    if key == "phys-force-analysis":
        # This fixed sample only uses Greek theta and inline trigonometric expressions.
        stem = stem.replace(r"$\theta$", "θ")
        explanation = (
            explanation.replace(r"\sin\theta", " sin θ")
            .replace(r"\cos\theta", " cos θ")
            .replace("$", "")
        )
    elif key == "phys-incline-accel":
        for source, target in (
            (r"\ \text{m/s}^2", " m/s²"),
            (r"\ \text{kg}", " kg"),
            (r"^\circ", "°"),
            (r"\sin", " sin "),
            (r"\times", " × "),
            ("$", ""),
        ):
            stem = stem.replace(source, target)
            explanation = explanation.replace(source, target)
    elif key in {"math-mono-quadratic", "math-mono-quadratic-v1"}:
        stem = stem.replace(r"\infty", "∞").replace("$", "")
        explanation = explanation.replace(r"\infty", "∞").replace("$", "")
    elif key in {"math-ineq-product-v1", "math-ineq-rect"}:
        for source, target in (
            (r"\ \text{m}^2", " m^2"),
            (r"\ \text{m}", " m"),
            (r"\sqrt{xy}", "sqrt(xy)"),
            (r"\dfrac{x+y}{2}", "(x+y)/2"),
            (r"\left(", "("),
            (r"\right)", ")"),
            (r"\le", "≤"),
            ("$", ""),
        ):
            stem = stem.replace(source, target)
            explanation = explanation.replace(source, target)
    elif key in {"chem-conservation-co2", "chem-conservation-h2"}:

        def chemistry_text(text):
            text = re.sub(r"\\text\{([^{}]+)\}", r"\1", text)
            text = re.sub(r"\\dfrac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
            text = re.sub(r"_(?=\d)", "", text)
            return (
                text.replace(r"\times", " × ")
                .replace(r"\uparrow", "↑")
                .replace(r"\ ", " ")
                .replace("$", "")
            )

        stem, explanation = chemistry_text(stem), chemistry_text(explanation)
    return PrintedQuestion(
        version.id,
        stem,
        explanation,
        answer_mode=question.answer_mode,
        incline_sketch=key in {"phys-force-analysis", "phys-incline-accel"},
        knowledge_ids=tuple(
            db.scalars(
                select(QuestionKnowledge.knowledge_id)
                .where(QuestionKnowledge.question_id == question.id)
                .order_by(QuestionKnowledge.knowledge_id)
            )
        ),
    )


def _awaiting_returns(db, student_id: str) -> tuple[set[str], set[str]]:
    abandoned = (
        select(AuditLog.id)
        .where(
            AuditLog.actor_id == student_id,
            AuditLog.target_type == "learning_pack",
            AuditLog.target_id == LearningJob.id,
            AuditLog.action == "learning_pack.abandoned",
        )
        .exists()
    )
    owner_filter = and_(LearningJob.student_id == student_id, ~abandoned)
    receipts = set(
        db.execute(
            select(
                LearningPackReturn.job_id,
                LearningPackReturn.code,
                LearningPackReturn.revision,
                LearningPackReturn.question_version_id,
            )
            .join(LearningJob, LearningJob.id == LearningPackReturn.job_id)
            .where(owner_filter)
        )
    )
    packs = db.execute(
        select(LearningPackPublication.job_id, LearningPackPublication.manifest_json)
        .join(LearningJob, LearningJob.id == LearningPackPublication.job_id)
        .where(owner_filter)
    )
    versions = set()
    nodes = set()
    for pack_id, manifest in packs:
        for item in manifest["items"]:
            version_id = item["question_version_id"]
            if (pack_id, item["code"], manifest["revision"], version_id) not in receipts:
                versions.add(version_id)
                nodes.update(item.get("knowledge_ids", ()))
    return versions, nodes


def _review_plan(schedule, inputs, minutes, item, waiting_nodes, today, capped_nodes):
    weekdays = set(inputs["settings"]["weekdays"])
    reviews = []
    for node, review in sorted(schedule.items(), key=lambda entry: (entry[1].due_on, entry[0])):
        start = max(today, review.due_on)
        suggested = next(
            (
                day
                for offset in range(7)
                if (day := start + timedelta(days=offset)).isoweekday() in weekdays
            ),
            None,
        )
        reason = (
            "no_learning_day"
            if suggested is None
            else "insufficient_budget"
            if minutes < SAMPLE_MINUTES
            else "overdue_budget_cap"
            if node in capped_nodes
            else "awaiting_return"
            if node in waiting_nodes and (item is None or node not in item.knowledge_ids)
            else "no_printable_item"
            if item is None or node not in item.knowledge_ids
            else None
        )
        reviews.append(
            {
                "knowledge_id": node,
                "original_due_on": review.due_on.isoformat(),
                "suggested_on": suggested.isoformat() if suggested else None,
                "deferred_reason": reason,
            }
        )
    return reviews


def _plan_pack(db, student_id, inputs, sample_font, now):
    minutes = remaining_minutes(inputs["settings"]["weekly_minutes"], inputs["school_minutes"])
    schedule = rebuild(paper_evidence(db, student_id))
    today = (now + timedelta(hours=8)).date()
    candidates = []
    capped_nodes = set()
    waiting_nodes = set()
    waiting = False
    if sample_font is not None and minutes >= SAMPLE_MINUTES and inputs["settings"]["weekdays"]:
        waiting_versions, printed_nodes = _awaiting_returns(db, student_id)
        for subject, key in PAPER_SAMPLES:
            if subject not in inputs["subjects"]:
                continue
            candidate = _sample_question(db, key)
            if candidate is None:
                continue
            known = {node for node in candidate.knowledge_ids if node in schedule}
            if minutes * 3 < SAMPLE_MINUTES * 5:
                capped_nodes.update(node for node in known if schedule[node].due_on < today)
            if known and known <= capped_nodes:
                continue
            due = min(
                (
                    schedule[node].due_on
                    for node in known - capped_nodes
                    if schedule[node].due_on <= today
                ),
                default=date.max,
            )
            if key in DUE_ONLY_SAMPLES and due == date.max:
                continue
            if candidate.question_version_id in waiting_versions or (
                due != date.max and not printed_nodes.isdisjoint(candidate.knowledge_ids)
            ):
                waiting = True
                waiting_nodes.update(candidate.knowledge_ids)
                continue
            repeated = any(
                schedule[node].due_on == due
                and schedule[node].source_version == candidate.question_version_id
                for node in known - capped_nodes
            )
            candidates.append((due, repeated, candidate))
    selected = min(candidates, key=lambda pair: pair[:2], default=None)
    item = selected[2] if selected else None
    deferred = waiting and item is None
    reviews = _review_plan(schedule, inputs, minutes, item, waiting_nodes, today, capped_nodes)
    if item is not None:
        matched = [review for review in reviews if review["knowledge_id"] in item.knowledge_ids]
        dates = [review["suggested_on"] for review in matched if review["deferred_reason"] is None]
        if matched and not dates:
            item = None
        elif dates:
            item = replace(item, suggested_on=min(dates))
    return item, minutes, deferred, reviews


def prepare_one(
    factory, clock, sample_font: Path | None = None, *, queued_id=None, pdf_store=None
) -> bool:
    now = clock()
    with factory() as db:
        query = (
            select(LearningJob.id, LearningJob.student_id)
            .join(LearningPackCommand, LearningPackCommand.job_id == LearningJob.id)
            .where(
                or_(
                    and_(
                        LearningJob.status.in_(("queued", "retry_wait")),
                        LearningJob.available_at <= now,
                    ),
                    and_(LearningJob.status == "running", LearningJob.lease_until <= now),
                )
            )
            .order_by(LearningJob.available_at, LearningJob.id)
            .limit(1)
        )
        if queued_id is not None:
            query = query.where(LearningJob.id == queued_id)
        job = db.execute(query).one_or_none()
        if job is None:
            return False
        job_id, student_id = job
        token = claim(db, job_id, now)
        db.commit()
    if token is None:
        return False

    try:
        with factory() as db:

            def lock_student():
                if sample_font is not None:
                    # Serialize planning and publication for the same student.
                    if db.get_bind().dialect.name == "sqlite":
                        db.execute(
                            update(User)
                            .where(User.id == student_id)
                            .values(updated_at=User.updated_at)
                        )
                    else:
                        db.scalar(select(User.id).where(User.id == student_id).with_for_update())

            lock_student()
            command = db.get_one(LearningPackCommand, job_id)
            inputs = command.input_json
            plan_at = clock()
            plan = _plan_pack(db, student_id, inputs, sample_font, plan_at)

            def save_checkpoint(checkpoint):
                nonlocal plan
                if not has_active_lease(db, job_id, token, clock(), lock=True):
                    return False
                db.merge(checkpoint)
                db.commit()
                lock_student()
                if not has_active_lease(db, job_id, token, clock()):
                    return False
                refreshed = _plan_pack(db, student_id, inputs, sample_font, plan_at)
                same_item = refreshed[0] == plan[0]
                plan = refreshed
                return same_item

            while True:
                item, minutes, deferred, reviews = plan
                done = (
                    publish(
                        db, job_id, token, [item], sample_font, clock, save_checkpoint, pdf_store
                    )
                    if item is not None and sample_font is not None
                    else finish(
                        db,
                        job_id,
                        token,
                        clock(),
                        success=True,
                        needs_review=(
                            not deferred
                            and minutes >= SAMPLE_MINUTES
                            and bool(inputs["settings"]["weekdays"])
                        ),
                    )
                )
                if done or item == plan[0]:
                    break
            item, minutes, deferred, reviews = plan
            if done:
                command.plan_json = {
                    "remaining_minutes": minutes,
                    **({"published": True} if item is not None else {}),
                    **({"deferred_reason": "awaiting_return"} if deferred else {}),
                    **({"reviews": reviews} if reviews else {}),
                }
                db.commit()
    except Exception:
        with factory() as db:
            finish(db, job_id, token, clock(), success=False)
            db.commit()
        raise
    return True


class LearningPackWorker:
    def __init__(
        self,
        factory,
        clock,
        settings,
        sample_font: Path | None = None,
        media_store=None,
        gateway=None,
        queue: RedisPaperQueue | None = None,
        invocation_store=None,
        pdf_store=None,
    ):
        self._factory = factory
        self._clock = clock
        self._settings = settings
        self._sample_font = sample_font
        self._media_store = media_store
        self._gateway = gateway
        self._queue = queue
        self._invocation_store = invocation_store
        self._pdf_store = pdf_store
        self._scan_database_next = False
        self._stop = Event()
        self._thread = Thread(target=self._run, name="learning-pack-worker", daemon=True)

    def start(self):
        self._thread.start()

    def close(self):
        self._stop.set()
        self._thread.join()

    def process_paper_once(self) -> bool:
        if self._scan_database_next:
            self._scan_database_next = False
            return prepare_one(
                self._factory, self._clock, self._sample_font, pdf_store=self._pdf_store
            )
        queued_id = None
        if self._queue is not None:
            try:
                deliver_one(self._factory, self._clock, self._queue.send)
                queued_id = self._queue.receive()
            except Exception:
                logger.exception("Learning pack Redis delivery failed")
        if queued_id is not None and prepare_one(
            self._factory,
            self._clock,
            self._sample_font,
            queued_id=queued_id,
            pdf_store=self._pdf_store,
        ):
            self._scan_database_next = True
            return True
        return prepare_one(self._factory, self._clock, self._sample_font, pdf_store=self._pdf_store)

    def _run(self):
        next_weekly_check = 0.0
        while not self._stop.is_set():
            try:
                self.process_paper_once()
            except Exception:
                logger.exception("Learning pack preparation failed")
            if self._media_store is not None:
                try:
                    process_photo_ocr(
                        self._factory,
                        self._clock,
                        self._settings,
                        self._media_store,
                        self._gateway,
                        self._invocation_store,
                    )
                except Exception:
                    logger.exception("Paper photo OCR failed")
                try:
                    process_one(
                        self._factory, self._clock, self._settings, self._media_store, self._gateway
                    )
                except Exception:
                    logger.exception("School material extraction failed")
            if monotonic() >= next_weekly_check:
                next_weekly_check = monotonic() + 60
                if self._media_store is not None:
                    try:
                        self._media_store.cleanup(now=self._clock())
                    except Exception:
                        logger.exception("Expired private media cleanup failed")
                try:
                    purge_expired_results(self._factory, self._clock())
                    purge_expired_candidates(self._factory, self._clock())
                    generate_due_snapshots(self._factory, self._settings, self._clock())
                except Exception:
                    logger.exception("Weekly snapshot generation failed")
                if self._pdf_store is not None:
                    try:
                        self._pdf_store.purge_unreferenced(self._factory, self._clock())
                    except Exception:
                        logger.exception("Unreferenced paper PDF cleanup failed")
            self._stop.wait(1)
