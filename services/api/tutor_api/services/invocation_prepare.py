"""Pre-receipt preparation only; no dispatch or model call occurs here."""

import hashlib
import hmac
from datetime import UTC

from sqlalchemy import select

from tutor_api.errors import conflict
from tutor_api.idempotency import key_digest, read_key, request_fingerprint
from tutor_api.services.invocation_context import capture_context
from tutor_api.services.invocation_finalize import actor_binding, session_binding
from tutor_api.services.invocation_store import intents


def invocation_id_for(ctx, secret: str) -> str:
    digest = key_digest(ctx.actor_id, read_key(ctx))
    return hmac.new(
        secret.encode(), f"model-invocation:v1:{digest}".encode(), hashlib.sha256
    ).hexdigest()[:32]


def prepare_rephrase(ctx, store, session_id: str, body, *, pseudonym: str, secret: str) -> dict:
    if not secret or body.action != "mark_confused":
        raise ValueError("Rephrase preparation requires server configuration and action")
    if "receipt_commit_allowed" in ctx.db.info:
        raise RuntimeError("Invocation must prepare before the formal receipt transaction")
    if ctx.db.new or ctx.db.dirty or ctx.db.deleted:
        raise RuntimeError("Invocation preparation cannot commit unrelated changes")
    invocation_id = invocation_id_for(ctx, secret)
    fingerprint = request_fingerprint(ctx, body)
    actor = actor_binding(pseudonym)
    existing = store.read(invocation_id, actor)
    if existing is not None:
        if (
            existing["fingerprint"] != fingerprint
            or existing["budget_key"] != pseudonym
            or existing["session_digest"] != session_binding(pseudonym, session_id)
        ):
            raise conflict("idempotency_key_conflict", "同一个幂等键对应另一份调用请求")
        return existing
    snapshot = capture_context(ctx.db, ctx.student_id, session_id)
    active = (
        ctx.db.execute(
            select(intents)
            .where(
                intents.c.active_session_digest == session_binding(pseudonym, session_id),
                intents.c.actor_digest == actor,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if active is not None:
        old = active["metadata_json"]
        if old["context_digest"] == snapshot.digest:
            raise conflict("invalid_state", "当前会话已有调用，请恢复原请求")
        store.applied_in_transaction(
            ctx.db,
            old["invocation_id"],
            actor,
            expected_fence=old["fence"],
            context_digest=snapshot.digest,
            retire_stale=True,
        )
    record = dict(
        schema_version=1,
        invocation_id=invocation_id,
        actor_digest=actor,
        budget_key=pseudonym,
        session_digest=session_binding(pseudonym, session_id),
        question_version=snapshot.question_version,
        context_generation=snapshot.event_sequence,
        context_digest=snapshot.digest,
        fingerprint=fingerprint,
        quota_day=ctx.now().astimezone(UTC).date().isoformat(),
        fence=1,
        state="prepared",
        attempts=[],
    )
    ctx.db.commit()
    return store.prepare(record)
