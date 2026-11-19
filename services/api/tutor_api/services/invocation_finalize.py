"""Finalize a live rephrase in the caller's event/receipt transaction.

This service performs no model call and never commits. It is not wired to an
HTTP route until durable dispatch orchestration is integrated.
"""

import hashlib
import json
from functools import lru_cache

from sqlalchemy import select

from ai_gateway.dto import Constraints, TaskType
from ai_gateway.errors import OutputRejected
from ai_gateway.prompts import PROMPT_VERSION
from ai_gateway.validation import OutputValidator
from ai_gateway.visual_templates import VisualRegistry
from tutor_api.errors import conflict
from tutor_api.models import ModelCallAudit
from tutor_api.schemas import TutorActionIn, TutorStep
from tutor_api.services import content_references, question_service, session_service
from tutor_api.services.invocation_context import capture_context
from tutor_api.services.invocation_store import intents
from tutor_api.services.orchestrator import _block_in_retest, _Turn
from tutor_api.settings import EVENT_SCHEMA_PATH, VISUAL_REGISTRY_PATH


def actor_binding(pseudonym: str) -> str:
    return hashlib.sha256(f"actor:{pseudonym}".encode()).hexdigest()


def session_binding(pseudonym: str, session_id: str) -> str:
    return hashlib.sha256(f"session:{pseudonym}:{session_id}".encode()).hexdigest()


@lru_cache(maxsize=1)
def _validator():
    return OutputValidator(
        json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8")),
        VisualRegistry.load(VISUAL_REGISTRY_PATH),
    )


def finalize_rephrase(
    tc,
    store,
    invocation_id: str,
    session_id: str,
    *,
    expected_fence: int,
    expected_fingerprint: str,
    output: dict,
    offered_catalog: list,
) -> TutorStep:
    current = capture_context(tc.db, tc.student_id, session_id)
    actor = actor_binding(tc.pseudonym)
    row = (
        tc.db.execute(
            select(intents)
            .where(
                intents.c.id == invocation_id,
                intents.c.actor_digest == actor,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise conflict("invalid_state", "调用记录不可用")
    record = row["metadata_json"]
    if (
        record["budget_key"] != tc.pseudonym
        or record["fingerprint"] != expected_fingerprint
        or record["session_digest"] != session_binding(tc.pseudonym, session_id)
        or record["question_version"] != current.question_version
        or record["context_generation"] != current.event_sequence
        or record["context_digest"] != current.digest
        or record["state"] != "settled_metadata"
    ):
        raise conflict("invalid_state", "学习上下文或调用状态已变化")
    if len(record["attempts"]) != 1:
        raise conflict("invalid_state", "调用尝试不可用")
    attempt = record["attempts"][0]
    audit = tc.db.get(ModelCallAudit, attempt["attempt_id"])
    if (
        audit is None
        or audit.student_pseudonym != tc.pseudonym
        or audit.status != "ok"
        or audit.task_type != "tutor_explain"
        or audit.schema_valid is not True
        or (audit.estimated_cost_micros or 0) > attempt["estimated_cost_micros"]
    ):
        raise conflict("invalid_state", "调用审计或成本需要检查")
    session = session_service.get_owned_session(tc.db, tc.student_id, session_id)
    version = question_service.get_version(tc.db, session.question_id, session.question_version)
    from tutor_api.models import Question

    turn = _Turn(
        tc,
        session,
        tc.db.get(Question, session.question_id),
        version,
        version.teaching_json or {},
        session_service.submitted_count(tc.db, session.id),
        TutorActionIn(action="mark_confused"),
    )
    _block_in_retest(turn)
    catalog = content_references.catalog(turn, ["rephrase"])
    try:
        checked = _validator().validate(
            TaskType.TUTOR_EXPLAIN,
            output,
            Constraints(
                forbidden_substrings=list(turn.teaching.get("leak_markers") or []),
                reference_catalog=catalog,
            ),
        )
        if checked["payload"]["style"] not in ("rephrase", "example"):
            raise ValueError("Unexpected teaching style")
        references = content_references.resolve_proposals(
            checked.get("references", []), offered_catalog, catalog
        )
    except (OutputRejected, ValueError, TypeError, KeyError) as error:
        raise conflict("invalid_state", "旧讲解未通过当前内容检查") from error
    store.applied_in_transaction(
        tc.db, invocation_id, actor, expected_fence=expected_fence, context_digest=current.digest
    )
    session.confused_streak = 1
    session.assisted = True
    event = turn.emit(
        "hint",
        checked["payload"],
        state_after="HINTED",
        source="model",
        references=references,
        provider=audit.provider,
        model_id=audit.model_id,
        prompt_version=PROMPT_VERSION,
        trace_id=audit.trace_id,
    )
    return TutorStep(session=session_service.serialize_session(tc.db, session), events=[event])
