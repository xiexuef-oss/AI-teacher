"""Persistent cost incidents and a shared durable-dispatch admission pause."""

import json
from copy import deepcopy
from datetime import UTC
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from tutor_api.services.invocation_tables import dispatch_gate, incidents
from tutor_api.settings import CONTRACTS_DIR

REVIEW_REASONS = frozenset(
    ("pricing_corrected", "provider_usage_verified", "configuration_changed")
)


@lru_cache(maxsize=1)
def incident_validator():
    schema = json.loads(
        (CONTRACTS_DIR / "model_budget_incident.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class ModelCostGate:
    def __init__(self, factory, now, *, policy="record_only"):
        if policy not in ("record_only", "pause_platform"):
            raise ValueError("Invalid model cost overrun policy")
        self.factory, self.now, self.policy = factory, now, policy

    def can_send(self) -> bool:
        """Read the latest committed pause in a fresh transaction before sending."""
        with self.factory() as db:
            return (
                db.scalar(select(dispatch_gate.c.paused).where(dispatch_gate.c.id == "platform"))
                is not True
            )

    def lock(self, db):
        values = dict(id="platform", paused=False, incident_id=None, updated_at=self.now())
        dialect = db.get_bind().dialect.name
        if dialect == "mysql":
            statement = (
                mysql_insert(dispatch_gate)
                .values(**values)
                .on_duplicate_key_update(id=dispatch_gate.c.id)
            )
        elif dialect == "sqlite":
            statement = (
                sqlite_insert(dispatch_gate)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["id"])
            )
        else:
            raise RuntimeError("Unsupported model cost gate database")
        db.execute(statement)
        return (
            db.execute(
                select(dispatch_gate).where(dispatch_gate.c.id == "platform").with_for_update()
            )
            .mappings()
            .one()
        )

    def record_overrun(self, db, gate, record, attempt_id, *, reserved, observed):
        if type(reserved) is not int or type(observed) is not int or not 0 <= reserved < observed:
            raise ValueError("Invalid cost overrun")
        stamp = self.now().astimezone(UTC)
        payload = dict(
            schema_version=1,
            attempt_id=attempt_id,
            invocation_id=record["invocation_id"],
            actor_digest=record["actor_digest"],
            budget_key=record["budget_key"],
            quota_day=record["quota_day"],
            reason="estimate_overrun",
            policy=self.policy,
            reserved_cost_micros=reserved,
            observed_estimated_cost_micros=observed,
            detected_at=stamp.isoformat(),
        )
        incident_validator().validate(payload)
        db.execute(insert(incidents).values(id=attempt_id, metadata_json=payload, created_at=stamp))
        if self.policy == "pause_platform" or gate["paused"]:
            db.execute(
                update(dispatch_gate)
                .where(dispatch_gate.c.id == "platform")
                .values(
                    paused=True,
                    incident_id=attempt_id,
                    updated_at=stamp,
                )
            )

    def report(self, *, limit=50):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid incident report limit")
        with self.factory() as db:
            gate = (
                db.execute(select(dispatch_gate).where(dispatch_gate.c.id == "platform"))
                .mappings()
                .one_or_none()
            )
            values = list(
                db.scalars(
                    select(incidents.c.metadata_json)
                    .order_by(incidents.c.created_at.desc(), incidents.c.id.desc())
                    .limit(limit)
                )
            )
        for value in values:
            incident_validator().validate(value)
        return dict(
            paused=bool(gate and gate["paused"]),
            incident_id=gate["incident_id"] if gate else None,
            incidents=deepcopy(values),
        )

    def resume(self, incident_id, *, reason):
        if reason not in REVIEW_REASONS:
            raise ValueError("Invalid cost review reason")
        with self.factory.begin() as db:
            gate = self.lock(db)
            if gate["incident_id"] != incident_id:
                raise ValueError("Cost incident changed; inspect the current report")
            row = (
                db.execute(select(incidents).where(incidents.c.id == incident_id).with_for_update())
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("Cost incident unavailable")
            payload = deepcopy(row["metadata_json"])
            if not gate["paused"]:
                if payload.get("review_reason") != reason or "reviewed_at" not in payload:
                    raise ValueError("Cost review conflict")
                return
            stamp = self.now().astimezone(UTC)
            payload.update(reviewed_at=stamp.isoformat(), review_reason=reason)
            incident_validator().validate(payload)
            db.execute(
                update(incidents).where(incidents.c.id == incident_id).values(metadata_json=payload)
            )
            db.execute(
                update(dispatch_gate)
                .where(dispatch_gate.c.id == "platform")
                .values(
                    paused=False,
                    updated_at=stamp,
                )
            )
