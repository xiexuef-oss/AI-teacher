"""Fresh-context authorization for one durable dispatch; performs no network IO."""

from uuid import uuid4

from tutor_api.errors import conflict
from tutor_api.services.invocation_context import require_context
from tutor_api.services.invocation_finalize import actor_binding, session_binding


def dispatch_rephrase(
    ctx,
    store,
    record: dict,
    session_id: str,
    *,
    pseudonym: str,
    estimated_cost_micros: int,
    request_cost_cap: int,
    student_limit: int,
    platform_limit: int,
    student_cost_limit: int | None = None,
    platform_cost_limit: int | None = None,
    recover_after=None,
) -> dict:
    if "receipt_commit_allowed" in ctx.db.info or ctx.db.new or ctx.db.dirty or ctx.db.deleted:
        raise RuntimeError("Dispatch must precede the formal business transaction")
    if (
        record["actor_digest"] != actor_binding(pseudonym)
        or record["budget_key"] != pseudonym
        or record["session_digest"] != session_binding(pseudonym, session_id)
    ):
        raise conflict("invalid_state", "调用身份或会话不匹配")
    # End auth/preparation reads before the independent short dispatch transaction.
    ctx.db.rollback()
    return store.dispatch(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=record["fence"],
        attempt_id=uuid4().hex,
        estimated_cost_micros=estimated_cost_micros,
        request_cost_cap=request_cost_cap,
        student_limit=student_limit,
        platform_limit=platform_limit,
        student_cost_limit=student_cost_limit,
        platform_cost_limit=platform_cost_limit,
        recover_after=recover_after,
        context_guard=lambda db: require_context(
            db, ctx.student_id, session_id, record["context_digest"]
        ),
    )
