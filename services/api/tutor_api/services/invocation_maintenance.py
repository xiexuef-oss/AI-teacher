"""Operator-only targeted retirement. No HTTP route or automatic retention policy."""

import hashlib
import re

from sqlalchemy import select

from tutor_api.gateway_io import pseudonym
from tutor_api.models import StudySession, User
from tutor_api.services.invocation_finalize import actor_binding, session_binding
from tutor_api.services.invocation_store import intents


def report_invocations(store, *, limit=50, after=None):
    """Operator-only keyset scan; UUID-like IDs do not imply time ordering."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Invalid invocation report limit")
    if after is not None and (
        not isinstance(after, str) or not re.fullmatch(r"[a-f0-9]{32}", after)
    ):
        raise ValueError("Invalid invocation report cursor")
    query = select(intents).order_by(intents.c.id).limit(limit + 1)
    if after is not None:
        query = query.where(intents.c.id > after)
    with store.factory() as db:
        rows = list(db.execute(query).mappings())
    items = []
    for row in rows[:limit]:
        value = store.transitions._checked(row["metadata_json"], row["fence"], row["state"])
        if value["invocation_id"] != row["id"]:
            raise ValueError("Invocation report identity mismatch")
        items.append(
            dict(
                invocation_id=value["invocation_id"],
                context_kind="tutor_session"
                if value["schema_version"] == 1
                else value["context_kind"],
                state=value["state"],
                fence=value["fence"],
                quota_day=value["quota_day"],
                attempts=[
                    {
                        key: attempt[key]
                        for key in ("attempt_id", "state", "estimated_cost_micros", "recover_after")
                        if key in attempt
                    }
                    for attempt in value["attempts"]
                ],
            )
        )
    return dict(items=items, next_cursor=rows[limit - 1]["id"] if len(rows) > limit else None)


def retire_terminal_session(
    store, student_id: str, session_id: str, *, secret: str, apply: bool = False
) -> int:
    if not secret:
        raise ValueError("Stable pseudonym secret required")
    pseudo = pseudonym(secret, student_id)
    actor = actor_binding(pseudo)
    with store.factory.begin() as db:
        user = db.scalar(select(User).where(User.id == student_id).with_for_update())
        if user is None or user.role != "student":
            return 0
        session = db.scalar(
            select(StudySession)
            .where(
                StudySession.id == session_id,
                StudySession.student_id == student_id,
            )
            .with_for_update()
        )
        if session is None or (user.status == "active" and session.state != "DONE"):
            return 0
        row = (
            db.execute(
                select(intents)
                .where(
                    intents.c.actor_digest == actor,
                    intents.c.active_session_digest == session_binding(pseudo, session_id),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return 0
        record = row["metadata_json"]
        if record["state"] not in (
            "prepared",
            "dispatch_unknown",
            "outcome_unknown",
            "settled_metadata",
        ):
            raise ValueError("Unexpected active invocation state")
        if apply:
            terminal_digest = hashlib.sha256(
                f"terminal:v1:{user.id}:{user.status}:{session.id}:{session.state}".encode()
            ).hexdigest()
            store.applied_in_transaction(
                db,
                record["invocation_id"],
                actor,
                expected_fence=record["fence"],
                context_digest=terminal_digest,
                retire_stale=True,
            )
        return 1
