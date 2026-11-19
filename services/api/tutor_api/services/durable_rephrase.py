"""Durable rephrase orchestration; explicitly injected, no external enablement."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from ai_gateway import Constraints, GatewayRequest, InputPart, TaskType
from ai_gateway.audit import AuditRecord
from tutor_api.errors import ApiError, conflict
from tutor_api.gateway_io import pseudonym
from tutor_api.idempotency import key_digest, read_key, request_fingerprint, run_idempotent
from tutor_api.models import Question
from tutor_api.receipts import SqlReceiptStore
from tutor_api.schemas import TutorActionIn, TutorStep
from tutor_api.services import content_references, orchestrator, question_service, session_service
from tutor_api.services.invocation_context import capture_context, require_context
from tutor_api.services.invocation_dispatch import dispatch_rephrase
from tutor_api.services.invocation_finalize import actor_binding, finalize_rephrase
from tutor_api.services.invocation_prepare import invocation_id_for, prepare_rephrase
from tutor_api.services.invocation_store import InvocationBudgetExceeded, intents


def run_durable_rephrase(ctx, body: TutorActionIn, store):
    try:
        return _run_durable_rephrase(ctx, body, store)
    except ApiError as error:
        if error.status_code == 409:
            ctx.db.rollback()
            state = ctx.request.app.state
            pseudo = pseudonym(state.pseudonym_secret, ctx.student_id)
            record = store.read(
                invocation_id_for(ctx, state.pseudonym_secret), actor_binding(pseudo)
            )
            if (
                record is not None
                and record["fingerprint"] == request_fingerprint(ctx, body)
                and record["state"]
                in ("prepared", "dispatch_unknown", "outcome_unknown", "settled_metadata")
            ):
                with store.factory.begin() as db:
                    snapshot = capture_context(
                        db,
                        ctx.student_id,
                        str(ctx.request.path_params["session_id"]),
                        allow_done=True,
                    )
                    latest = (
                        db.execute(
                            select(intents)
                            .where(
                                intents.c.id == record["invocation_id"],
                                intents.c.actor_digest == record["actor_digest"],
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .one_or_none()
                    )
                    active = latest["metadata_json"] if latest is not None else None
                    if (
                        active is not None
                        and active["state"]
                        in ("prepared", "dispatch_unknown", "outcome_unknown", "settled_metadata")
                        and snapshot.digest != active["context_digest"]
                    ):
                        store.applied_in_transaction(
                            db,
                            active["invocation_id"],
                            active["actor_digest"],
                            expected_fence=active["fence"],
                            context_digest=snapshot.digest,
                            retire_stale=True,
                        )
        raise


def _run_durable_rephrase(ctx, body: TutorActionIn, store):
    state = ctx.request.app.state
    receipts = getattr(state, "receipt_store", None)
    if not isinstance(receipts, SqlReceiptStore):
        raise RuntimeError("Durable model orchestration requires formal receipts")
    key = read_key(ctx)
    if receipts.lookup(ctx, key, key_digest(ctx.actor_id, key)) is not None:
        return run_idempotent(
            ctx, body, 200, lambda _: (_ for _ in ()).throw(RuntimeError("Replay must not execute"))
        )
    # The request route binds the session; this function is internal only.
    session_id = str(ctx.request.path_params["session_id"])
    pseudo = pseudonym(state.pseudonym_secret, ctx.student_id)
    record = prepare_rephrase(
        ctx, store, session_id, body, pseudonym=pseudo, secret=state.pseudonym_secret
    )

    def unavailable_without_send(reason=None):
        def action(_):
            if reason is not None:
                current = session_service.lock_owned_session(ctx.db, ctx.student_id, session_id)
                if current.state == "DONE":
                    raise conflict("invalid_state", "这次学习已经结束")
                current.confused_streak = 1
                event = orchestrator.events.append_event(
                    ctx.db,
                    current,
                    event_type="fallback",
                    payload=dict(
                        reason_code=reason,
                        text="当前可用额度不足，可以先看审核提示。",
                        suggestions=[],
                    ),
                    state_after="FALLBACK",
                    source="rule_engine",
                    request_id=ctx.request_id,
                    now=ctx.now(),
                    degraded=True,
                )
                return TutorStep(
                    session=session_service.serialize_session(ctx.db, current), events=[event]
                )
            context = orchestrator.TutorContext(
                ctx.db,
                ctx.settings,
                state.gateway,
                ctx.student_id,
                pseudo,
                ctx.request_id,
                ctx.now(),
                allow_gateway=False,
            )
            return orchestrator.next_step(context, session_id, body)

        return run_idempotent(ctx, body, 200, action)

    if record["state"] == "cancelled_unsent":
        return unavailable_without_send()
    if record["state"] == "dispatch_unknown":
        try:
            record = store.mark_unknown(
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=record["fence"],
                require_due=True,
            )
        except ValueError as error:
            raise conflict("invalid_state", "原调用仍在处理，请稍后重试同一请求") from error
    if record["state"] in ("settled_metadata", "outcome_unknown"):

        def recover_settled(_):
            current = require_context(ctx.db, ctx.student_id, session_id, record["context_digest"])
            store.applied_in_transaction(
                ctx.db,
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=record["fence"],
                context_digest=record["context_digest"],
                close_unknown=record["state"] == "outcome_unknown",
            )
            current.confused_streak = 1
            event = orchestrator.events.append_event(
                ctx.db,
                current,
                event_type="fallback",
                payload=dict(
                    reason_code="MODEL_UNAVAILABLE",
                    text="这次换讲未能恢复，可以先看审核提示。",
                    suggestions=[],
                ),
                state_after="FALLBACK",
                source="rule_engine",
                request_id=ctx.request_id,
                now=ctx.now(),
                degraded=True,
            )
            return TutorStep(
                session=session_service.serialize_session(ctx.db, current), events=[event]
            )

        return run_idempotent(ctx, body, 200, recover_settled)
    if record["state"] != "prepared":
        raise conflict("invalid_state", "原调用尚需恢复确认，不会重复发送")
    session = require_context(ctx.db, ctx.student_id, session_id, record["context_digest"])
    version = question_service.get_version(ctx.db, session.question_id, session.question_version)
    tc = orchestrator.TutorContext(
        ctx.db, ctx.settings, state.gateway, ctx.student_id, pseudo, ctx.request_id, ctx.now()
    )
    turn = orchestrator._Turn(
        tc,
        session,
        ctx.db.get(Question, session.question_id),
        version,
        version.teaching_json or {},
        session_service.submitted_count(ctx.db, session.id),
        body,
    )
    orchestrator._block_in_retest(turn)
    if turn.teaching.get("concept_rephrase"):
        raise conflict("invalid_state", "受审换讲应走受审内容路径")
    catalog = content_references.catalog(turn, ["rephrase"])
    request = GatewayRequest(
        request_id=ctx.request_id,
        student_pseudonym=pseudo,
        task_type=TaskType.TUTOR_EXPLAIN,
        trace_id=uuid4().hex,
        input_parts=[
            InputPart(
                kind="json",
                data=dict(
                    subject=turn.question.subject,
                    concept=turn.teaching.get("concept"),
                    key_idea=None,
                    independent_attempt=turn.submitted == 0,
                ),
            )
        ],
        constraints=Constraints(
            forbidden_substrings=list(turn.teaching.get("leak_markers") or []),
            reference_catalog=catalog,
        ),
    )
    try:
        plan = state.gateway.prepare_single_attempt(request)
    except ValueError:
        ctx.db.rollback()
        store.cancel(
            record["invocation_id"], record["actor_digest"], expected_fence=record["fence"]
        )
        return unavailable_without_send()
    limits = state.gateway._config.budgets
    try:
        dispatched = dispatch_rephrase(
            ctx,
            store,
            record,
            session_id,
            pseudonym=pseudo,
            estimated_cost_micros=plan.estimated_cost_micros,
            request_cost_cap=limits.per_request_max_cost_micros,
            student_limit=limits.student_daily_requests,
            platform_limit=limits.platform_daily_requests,
            student_cost_limit=limits.student_daily_max_cost_micros,
            platform_cost_limit=limits.platform_daily_max_cost_micros,
            recover_after=ctx.now() + timedelta(seconds=plan.timeout_s),
        )
    except InvocationBudgetExceeded:
        try:
            store.cancel(
                record["invocation_id"], record["actor_digest"], expected_fence=record["fence"]
            )
        except ValueError as error:
            latest = store.read(record["invocation_id"], record["actor_digest"])
            if latest is None or latest["state"] != "cancelled_unsent":
                raise conflict("invalid_state", "调用状态已变化，请重试原请求") from error
        return unavailable_without_send("BUDGET_EXCEEDED")
    response = state.gateway.invoke_single_attempt(plan)
    if response.provider_calls != 1:
        store.mark_unknown(
            record["invocation_id"], record["actor_digest"], expected_fence=record["fence"]
        )
        raise conflict("invalid_state", "调用未取得可结算结果，保留原记录等待确认")
    audit = AuditRecord(
        request_id=ctx.request_id,
        trace_id=response.trace_id,
        student_pseudonym=pseudo,
        task_type=TaskType.TUTOR_EXPLAIN.value,
        provider=response.provider,
        model_id=response.model_id,
        status=response.status,
        error_code=response.error_code,
        provider_calls=1,
        latency_ms=response.latency_ms,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        image_units=response.usage.image_units,
        estimated_cost_micros=response.usage.estimated_cost_micros,
        schema_valid=True if response.status == "ok" else None,
        review_required=response.review_required,
        created_at=ctx.now(),
    )
    store.settle_metadata(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=record["fence"],
        attempt_id=dispatched["attempts"][0]["attempt_id"],
        audit=audit,
    )

    def finalize(_digest):
        tc.now = ctx.now()
        if response.status == "ok":
            return finalize_rephrase(
                tc,
                store,
                record["invocation_id"],
                session_id,
                expected_fence=record["fence"],
                expected_fingerprint=request_fingerprint(ctx, body),
                output=response.validated_output,
                offered_catalog=catalog,
            )
        current = require_context(ctx.db, ctx.student_id, session_id, record["context_digest"])
        current.confused_streak = 1
        store.applied_in_transaction(
            ctx.db,
            record["invocation_id"],
            record["actor_digest"],
            expected_fence=record["fence"],
            context_digest=record["context_digest"],
        )
        event = orchestrator.events.append_event(
            ctx.db,
            current,
            event_type="fallback",
            payload=dict(
                reason_code=response.error_code
                if response.error_code in orchestrator._FALLBACK_REASONS
                else "MODEL_UNAVAILABLE",
                text="换种讲法暂时不可用，可以先看审核提示。",
                suggestions=[],
            ),
            state_after="FALLBACK",
            source="rule_engine",
            request_id=ctx.request_id,
            now=tc.now,
            degraded=True,
            trace_id=response.trace_id,
        )
        return TutorStep(session=session_service.serialize_session(ctx.db, current), events=[event])

    return run_idempotent(ctx, body, 200, finalize)
