"""教学事件的生成与落库。

每个事件在写库之前都按 contracts/tutor_event.schema.json 校验一遍——不管它来自审核内容、
规则还是模型。校验不过说明服务端自己拼错了事件，直接抛错，不会把坏事件发给客户端。
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.models import StudySession, TutorEventRow
from tutor_api.settings import EVENT_SCHEMA_PATH
from tutor_api.timefmt import iso

SCHEMA_VERSION = "1.0"


class EventSchemaError(RuntimeError):
    """服务端生成的事件不符合教学事件 Schema。"""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def last_seq(db: Session, session_id: str, *, current_read=False) -> int:
    if current_read:
        return (
            db.scalar(
                select(TutorEventRow.seq_no)
                .where(TutorEventRow.session_id == session_id)
                .order_by(TutorEventRow.seq_no.desc())
                .limit(1)
                .with_for_update()
            )
            or 0
        )
    return (
        db.scalar(
            select(func.max(TutorEventRow.seq_no)).where(TutorEventRow.session_id == session_id)
        )
        or 0
    )


def suggestion(
    action: str, label: str, *, question_id: str | None = None, knowledge_id: str | None = None
) -> dict[str, Any]:
    return {
        "action": action,
        "label": label,
        "question_id": question_id,
        "knowledge_id": knowledge_id,
    }


def append_event(
    db: Session,
    session: StudySession,
    *,
    event_type: str,
    payload: dict[str, Any],
    state_after: str,
    source: str,
    request_id: str,
    now: datetime,
    degraded: bool = False,
    provider: str | None = None,
    model_id: str | None = None,
    prompt_version: str | None = None,
    trace_id: str | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """追加一个事件并把会话推进到 state_after。返回可直接下发的事件。"""
    event = {
        "id": new_id(),
        "session_id": session.id,
        "seq_no": last_seq(db, session.id, current_read=True) + 1,
        "type": event_type,
        "created_at": iso(now),
        "state_after": state_after,
        "payload": payload,
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "source": source,
            "degraded": degraded,
            "provider": provider,
            "model_id": model_id,
            "prompt_version": prompt_version,
            "question_id": session.question_id,
            "question_version": session.question_version,
            "trace_id": trace_id,
            "request_id": request_id,
        },
    }
    if references:
        from tutor_api.services.content_references import resolve

        try:
            for reference in references:
                resolve(
                    {key: reference[key] for key in ("block_id", "block_sha256", "start", "end")},
                    {reference["block_id"]: reference["block_text"]},
                )
        except (ValueError, TypeError, KeyError) as error:
            raise EventSchemaError("invalid resolved reference snapshot") from error
        event["references"] = json.loads(json.dumps(references))
    error = next(iter(_validator().iter_errors(event)), None)
    if error is not None:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise EventSchemaError(f"{event_type} 事件不符合 Schema（{location}）：{error.message}")

    db.add(
        TutorEventRow(
            id=event["id"],
            session_id=session.id,
            seq_no=event["seq_no"],
            event_type=event_type,
            event_json=event,
            created_at=now,
        )
    )
    session.state = state_after
    session.updated_at = now
    db.flush()
    return event


def list_events(
    db: Session, session_id: str, *, after_seq: int, limit: int
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(TutorEventRow)
        .where(TutorEventRow.session_id == session_id, TutorEventRow.seq_no > after_seq)
        .order_by(TutorEventRow.seq_no)
        .limit(limit)
    )
    return [row.event_json for row in rows]
