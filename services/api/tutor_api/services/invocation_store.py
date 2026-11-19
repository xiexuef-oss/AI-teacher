"""Internal metadata persistence. No provider dispatch is authorized by this store."""

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from ai_gateway.audit import AuditRecord
from ai_gateway.errors import InvocationBudgetExceeded
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.db import new_id
from tutor_api.models import ModelBudgetUsage, ModelCallAudit
from tutor_api.services.invocation_tables import intents
from tutor_api.services.invocation_tables import metadata as metadata
from tutor_api.services.model_cost_gate import ModelCostGate


def _resource_slot(record: dict) -> str:
    # Keep the deployed 014 column name, but never fabricate a tutoring session
    # for a document. Callers domain-separate document and session digests.
    return record["session_digest"] if record["schema_version"] == 1 else record["resource_digest"]


def _identity(record: dict) -> dict:
    mutable = {"quota_day", "fence", "state", "attempts"}
    return {key: value for key, value in record.items() if key not in mutable}


class InvocationStore:
    def applied_in_transaction(
        self,
        db,
        invocation_id: str,
        actor_digest: str,
        *,
        expected_fence: int,
        context_digest: str,
        close_unknown: bool = False,
        retire_stale: bool = False,
    ) -> dict:
        """Caller must hold the verified session/context lock and finish its receipt.

        This is a transaction primitive, not a standalone apply endpoint. It does
        not validate a model response, emit teaching, or commit the transaction.
        """
        if db.get_transaction() is None:
            raise ValueError("Application requires an existing business transaction")
        actual = db.get_bind()
        expected = self.factory.kw.get("bind")
        actual_engine = getattr(actual, "engine", actual)
        expected_engine = getattr(expected, "engine", expected)
        if expected_engine is None or actual_engine.url != expected_engine.url:
            raise ValueError("Application database does not match invocation store")
        row = (
            db.execute(
                select(intents)
                .where(
                    intents.c.id == invocation_id,
                    intents.c.actor_digest == actor_digest,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("Invocation unavailable")
        if close_unknown and retire_stale:
            raise ValueError("Ambiguous terminal transition")
        operation = (
            self.transitions.stale
            if retire_stale
            else (self.transitions.close_unknown if close_unknown else self.transitions.applied)
        )
        result = operation(
            row["metadata_json"], expected_fence=expected_fence, context_digest=context_digest
        )
        changed = db.execute(
            update(intents)
            .where(
                intents.c.id == invocation_id,
                intents.c.actor_digest == actor_digest,
                intents.c.state
                == (
                    row["state"]
                    if retire_stale
                    else ("outcome_unknown" if close_unknown else "settled_metadata")
                ),
                intents.c.fence == expected_fence,
            )
            .values(state=result["state"], metadata_json=result, active_session_digest=None)
        )
        if changed.rowcount != 1:
            raise ValueError("Invocation changed concurrently")
        return result

    def settle_metadata(
        self,
        invocation_id: str,
        actor_digest: str,
        *,
        expected_fence: int,
        attempt_id: str,
        audit: AuditRecord,
        retryable_failure: bool = False,
        retry_disposition: str = "none",
    ) -> dict:
        if type(retryable_failure) is not bool or (
            retryable_failure
            and (
                audit.status == "ok"
                or audit.error_code not in ("MODEL_UNAVAILABLE", "SCHEMA_INVALID")
            )
        ):
            raise ValueError("Invalid retryable failure evidence")
        for field in (
            "provider_calls",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "image_units",
            "estimated_cost_micros",
        ):
            value = getattr(audit, field)
            if value is None and field not in ("provider_calls", "latency_ms"):
                continue
            if type(value) is not int or value < 0:
                raise ValueError("Invalid audit numeric metadata")
        if audit.status not in ("ok", "degraded", "error"):
            raise ValueError("Invalid audit status")
        if type(audit.review_required) is not bool or (
            audit.schema_valid is not None and type(audit.schema_valid) is not bool
        ):
            raise ValueError("Invalid audit validation flags")
        if audit.created_at.tzinfo is None or audit.created_at.utcoffset() is None:
            raise ValueError("Audit timestamp must be timezone aware")
        payload = asdict(audit)
        timestamp = audit.created_at.astimezone(UTC)
        payload["created_at"] = timestamp.replace(microsecond=timestamp.microsecond // 1000 * 1000)
        with self.factory.begin() as db:
            gate = self.cost_gate.lock(db)
            row = (
                db.execute(
                    select(intents)
                    .where(
                        intents.c.id == invocation_id,
                        intents.c.actor_digest == actor_digest,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("Invocation unavailable")
            record = row["metadata_json"]
            if audit.student_pseudonym != record["budget_key"] or audit.provider_calls != 1:
                raise ValueError("Audit identity conflict")
            if record["state"] in ("settled_metadata", "applied") or (
                record["state"] in ("closed_unknown", "stale")
                and record["attempts"]
                and record["attempts"][-1]["state"] == "settled"
            ):
                if type(expected_fence) is not int or record["fence"] != expected_fence:
                    raise ValueError("Stale invocation fence")
                if (
                    (record["schema_version"] != 3 and len(record["attempts"]) != 1)
                    or record["attempts"][-1]["attempt_id"] != attempt_id
                    or record["attempts"][-1].get("retryable_failure", False) != retryable_failure
                    or record["attempts"][-1].get("sdk_context", {}).get("continuation", "none")
                    != retry_disposition
                ):
                    raise ValueError("Attempt identity conflict")
                previous = db.get(ModelCallAudit, attempt_id)
                if previous is None or any(
                    getattr(previous, key) != value for key, value in payload.items()
                ):
                    raise ValueError("Audit settlement conflict")
                return deepcopy(record)
            result = self.transitions.settle_metadata(
                record,
                expected_fence=expected_fence,
                attempt_id=attempt_id,
                retryable_failure=retryable_failure,
                retry_disposition=retry_disposition,
            )
            changed = db.execute(
                update(intents)
                .where(
                    intents.c.id == invocation_id,
                    intents.c.actor_digest == actor_digest,
                    intents.c.state == record["state"],
                    intents.c.fence == expected_fence,
                )
                .values(state=result["state"], metadata_json=result)
            )
            if changed.rowcount != 1:
                raise ValueError("Invocation changed concurrently")
            delta = max(
                0,
                (audit.estimated_cost_micros or 0)
                - record["attempts"][-1]["estimated_cost_micros"],
            )
            if delta:
                for scope, key in (("platform", "platform"), ("student", record["budget_key"])):
                    updated = db.execute(
                        update(ModelBudgetUsage)
                        .where(
                            ModelBudgetUsage.scope == scope,
                            ModelBudgetUsage.scope_key == key,
                            ModelBudgetUsage.usage_date == date.fromisoformat(record["quota_day"]),
                        )
                        .values(
                            estimated_cost_micros=ModelBudgetUsage.estimated_cost_micros + delta
                        )
                    )
                    if updated.rowcount != 1:
                        raise ValueError("Invocation budget missing")
                self.cost_gate.record_overrun(
                    db,
                    gate,
                    record,
                    attempt_id,
                    reserved=record["attempts"][-1]["estimated_cost_micros"],
                    observed=audit.estimated_cost_micros,
                )
            db.add(ModelCallAudit(id=attempt_id, **payload))
            db.flush()
        return result

    def __init__(
        self,
        factory: sessionmaker,
        transitions: InvocationTransitions,
        *,
        now=None,
        overrun_policy="record_only",
    ):
        self.factory = factory
        self.transitions = transitions
        self.now = now or (lambda: datetime.now(UTC))
        self.cost_gate = ModelCostGate(factory, self.now, policy=overrun_policy)

    def prepare(self, record: dict) -> dict:
        # Validate as a prepared record without changing the stored fence.
        self.transitions.claim(record, expected_fence=record["fence"])
        try:
            with self.factory.begin() as db:
                db.execute(
                    insert(intents).values(
                        id=record["invocation_id"],
                        actor_digest=record["actor_digest"],
                        active_session_digest=_resource_slot(record),
                        state=record["state"],
                        fence=record["fence"],
                        metadata_json=deepcopy(record),
                    )
                )
        except IntegrityError:
            # Use a new transaction so MySQL RR does not reuse a pre-insert snapshot.
            existing = self.read(record["invocation_id"], record["actor_digest"])
            if existing is None:
                raise ValueError("Invocation unavailable or session already occupied") from None
            if _identity(existing) != _identity(record):
                raise ValueError("Invocation identity conflict") from None
            return existing
        return deepcopy(record)

    def read(self, invocation_id: str, actor_digest: str) -> dict | None:
        with self.factory() as db:
            row = (
                db.execute(
                    select(intents).where(
                        intents.c.id == invocation_id,
                        intents.c.actor_digest == actor_digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            return deepcopy(row["metadata_json"]) if row else None

    def claim(self, invocation_id: str, actor_digest: str, *, expected_fence: int) -> dict:
        return self._change(invocation_id, actor_digest, expected_fence, cancel=False)

    def dispatch(
        self,
        invocation_id: str,
        actor_digest: str,
        *,
        expected_fence: int,
        attempt_id: str,
        estimated_cost_micros: int,
        request_cost_cap: int,
        student_limit: int,
        platform_limit: int,
        student_cost_limit: int | None = None,
        platform_cost_limit: int | None = None,
        context_guard=None,
        recover_after=None,
        sdk_context: dict | None = None,
    ) -> dict:
        if any(
            type(v) is not int or v < 0
            for v in (estimated_cost_micros, request_cost_cap, student_limit, platform_limit)
        ):
            raise ValueError("Invalid budget parameters")
        if estimated_cost_micros > request_cost_cap:
            raise InvocationBudgetExceeded("Request budget exceeded")
        if any(
            limit is not None and (type(limit) is not int or limit < 0)
            for limit in (student_cost_limit, platform_cost_limit)
        ):
            raise ValueError("Invalid daily cost limit")
        with self.factory.begin() as db:
            # The application guard acquires user/session locks before intent
            # and budget locks, matching finalization's order.
            if context_guard is not None:
                context_guard(db)
            gate = self.cost_gate.lock(db)
            if gate["paused"]:
                raise InvocationBudgetExceeded("Model dispatch paused pending cost review")
            row = (
                db.execute(
                    select(intents).where(
                        intents.c.id == invocation_id,
                        intents.c.actor_digest == actor_digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("Invocation unavailable")
            record = row["metadata_json"]
            continuation = record["schema_version"] == 3 and record["state"] == "settled_metadata"
            prior_cost = 0
            if continuation:
                for attempt in record["attempts"]:
                    audit = db.get(ModelCallAudit, attempt["attempt_id"])
                    if (
                        audit is None
                        or audit.student_pseudonym != record["budget_key"]
                        or audit.provider_calls != 1
                    ):
                        raise ValueError("Prior attempt audit missing")
                    prior_cost += max(
                        attempt["estimated_cost_micros"], audit.estimated_cost_micros or 0
                    )
                if (
                    not record["attempts"]
                    or audit.status not in ("degraded", "error")
                    or audit.error_code not in ("MODEL_UNAVAILABLE", "SCHEMA_INVALID")
                ):
                    raise ValueError("Successful attempt cannot continue")
                if prior_cost + estimated_cost_micros > request_cost_cap:
                    raise InvocationBudgetExceeded("Cumulative request budget exceeded")
            result = self.transitions.dispatch(
                record,
                expected_fence=expected_fence,
                attempt_id=attempt_id,
                estimated_cost_micros=estimated_cost_micros,
                sdk_context=sdk_context,
            )
            # Prepared records have not consumed quota. Freeze UTC admission day
            # in the same transaction as dispatch and both budget buckets.
            if not continuation:
                result["quota_day"] = self.now().astimezone(UTC).date().isoformat()
            if recover_after is not None:
                if recover_after.tzinfo is None or recover_after.utcoffset() is None:
                    raise ValueError("Recovery deadline must have timezone")
                result["attempts"][-1]["recover_after"] = recover_after.astimezone(UTC).isoformat()
            changed = db.execute(
                update(intents)
                .where(
                    intents.c.id == invocation_id,
                    intents.c.actor_digest == actor_digest,
                    intents.c.state == record["state"],
                    intents.c.fence == expected_fence,
                )
                .values(state=result["state"], fence=result["fence"], metadata_json=result)
            )
            if changed.rowcount != 1:
                raise ValueError("Invocation changed concurrently")
            day = date.fromisoformat(result["quota_day"])
            dialect = db.get_bind().dialect.name
            for scope, key, limit, cost_limit in (
                ("platform", "platform", platform_limit, platform_cost_limit),
                ("student", result["budget_key"], student_limit, student_cost_limit),
            ):
                values = dict(
                    id=new_id(),
                    scope=scope,
                    scope_key=key,
                    usage_date=day,
                    request_count=0,
                    estimated_cost_micros=0,
                    updated_at=datetime.now(UTC),
                )
                if dialect == "mysql":
                    statement = (
                        mysql_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_duplicate_key_update(id=ModelBudgetUsage.id)
                    )
                elif dialect == "sqlite":
                    statement = (
                        sqlite_insert(ModelBudgetUsage)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["scope", "scope_key", "usage_date"])
                    )
                else:
                    raise RuntimeError("Unsupported invocation budget store")
                db.execute(statement)
                bucket = db.scalar(
                    select(ModelBudgetUsage)
                    .where(
                        ModelBudgetUsage.scope == scope,
                        ModelBudgetUsage.scope_key == key,
                        ModelBudgetUsage.usage_date == day,
                    )
                    .with_for_update()
                )
                if continuation and (
                    bucket.request_count < 1 or bucket.estimated_cost_micros < prior_cost
                ):
                    raise ValueError("Prior invocation budget missing")
                if bucket.request_count + (0 if continuation else 1) > limit:
                    raise InvocationBudgetExceeded("Daily request budget exceeded")
                if (
                    cost_limit is not None
                    and bucket.estimated_cost_micros + estimated_cost_micros > cost_limit
                ):
                    raise InvocationBudgetExceeded("Daily cost budget exceeded")
                bucket.request_count += 0 if continuation else 1
                bucket.estimated_cost_micros += estimated_cost_micros
                bucket.updated_at = datetime.now(UTC)
            db.flush()
        return result

    def cancel(self, invocation_id: str, actor_digest: str, *, expected_fence: int) -> dict:
        return self._change(invocation_id, actor_digest, expected_fence, cancel=True)

    def mark_unknown(
        self,
        invocation_id: str,
        actor_digest: str,
        *,
        expected_fence: int,
        require_due: bool = False,
    ) -> dict:
        with self.factory.begin() as db:
            row = (
                db.execute(
                    select(intents).where(
                        intents.c.id == invocation_id,
                        intents.c.actor_digest == actor_digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("Invocation unavailable")
            record = row["metadata_json"]
            if require_due and record["state"] == "dispatch_unknown":
                deadline = record["attempts"][-1].get("recover_after")
                if deadline is None or datetime.fromisoformat(deadline).astimezone(
                    UTC
                ) > self.now().astimezone(UTC):
                    raise ValueError("Invocation may still be running")
            if record["state"] == "outcome_unknown":
                if type(expected_fence) is not int or record["fence"] != expected_fence:
                    raise ValueError("Stale invocation fence")
                return deepcopy(record)
            result = self.transitions.mark_unknown(record, expected_fence=expected_fence)
            changed = db.execute(
                update(intents)
                .where(
                    intents.c.id == invocation_id,
                    intents.c.actor_digest == actor_digest,
                    intents.c.state == "dispatch_unknown",
                    intents.c.fence == expected_fence,
                )
                .values(state="outcome_unknown", metadata_json=result)
            )
            if changed.rowcount != 1:
                raise ValueError("Invocation changed concurrently")
            return result

    def _change(
        self, invocation_id: str, actor_digest: str, expected_fence: int, *, cancel: bool
    ) -> dict:
        with self.factory.begin() as db:
            row = (
                db.execute(
                    select(intents).where(
                        intents.c.id == invocation_id,
                        intents.c.actor_digest == actor_digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("Invocation unavailable")
            operation = self.transitions.cancel if cancel else self.transitions.claim
            result = operation(row["metadata_json"], expected_fence=expected_fence)
            changed = db.execute(
                update(intents)
                .where(
                    intents.c.id == invocation_id,
                    intents.c.actor_digest == actor_digest,
                    intents.c.state == "prepared",
                    intents.c.fence == expected_fence,
                )
                .values(
                    metadata_json=result,
                    state=result["state"],
                    fence=result["fence"],
                    active_session_digest=None if cancel else _resource_slot(result),
                )
            )
            if changed.rowcount != 1:
                raise ValueError("Invocation changed concurrently")
            return result
