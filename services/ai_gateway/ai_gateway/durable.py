"""Opt-in standalone SDK dispatch using the existing injected invocation store.

Only metadata is durable. Replays never resend or pretend to restore model text.
"""

import hashlib
import hmac
import json
import re
from datetime import UTC, timedelta
from uuid import uuid4

from ai_gateway.audit import AuditRecord
from ai_gateway.dto import GatewayRequest, GatewayResponse, Usage
from ai_gateway.errors import InvocationBudgetExceeded
from ai_gateway.prompts import build_messages


def invoke(gateway, request, store, secret, *, context_guard=None):
    def unavailable(code, response=None):
        if response is not None:
            return response.model_copy(
                update={
                    "status": "degraded",
                    "validated_output": None,
                    "error_code": code,
                    "prompt_version": None,
                    "retry_disposition": "none",
                }
            )
        return GatewayResponse(
            provider=None,
            model_id=None,
            status="degraded",
            validated_output=None,
            usage=Usage(),
            latency_ms=0,
            confidence=None,
            review_required=False,
            error_code=code,
            trace_id=request.trace_id,
        )

    try:
        request = GatewayRequest.model_validate(request.model_dump(mode="json"))
        if (
            not 0 < len(request.request_id) <= 128
            or not 0 < len(request.trace_id) <= 64
            or not re.fullmatch(r"stu_[a-f0-9]{32}", request.student_pseudonym)
        ):
            return unavailable("INVALID_INVOCATION_IDENTITY")

        def binding(purpose, value):
            return hmac.new(
                secret.encode(), f"sdk:{purpose}:{value}".encode(), hashlib.sha256
            ).hexdigest()

        def routing_digest():
            return binding(
                "routing",
                json.dumps(
                    [
                        {
                            "provider": c.provider,
                            "model": c.model or gateway._env.get(c.model_env or ""),
                            "external": gateway._config.providers[c.provider].external,
                        }
                        for c in gateway._config.routes[request.task_type].candidates
                    ],
                    sort_keys=True,
                ),
            )

        actor = binding("actor", request.student_pseudonym)
        slot = binding("resource", f"{actor}:{request.request_id}")
        fingerprint = binding(
            "request",
            json.dumps(
                {
                    "request": request.model_dump(mode="json", exclude={"request_id", "trace_id"}),
                    "messages": build_messages(request),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        record = dict(
            schema_version=3,
            invocation_id=binding("invocation", slot)[:32],
            actor_digest=actor,
            budget_key=request.student_pseudonym,
            context_kind="sdk_request",
            resource_digest=slot,
            context_generation=0,
            context_digest=fingerprint,
            fingerprint=fingerprint,
            quota_day=gateway._now().astimezone(UTC).date().isoformat(),
            fence=1,
            state="prepared",
            attempts=[],
        )
        try:
            record = store.prepare(record)
        except ValueError:
            return unavailable("INVOCATION_CONFLICT")
        first_candidate = first_retry = 0
        external_used = set()
        if record["state"] != "prepared":
            attempts = record["attempts"]
            can_resume = (
                record["state"] == "settled_metadata"
                and attempts
                and attempts[-1].get("retryable_failure")
                and all(a["state"] == "settled" and a.get("sdk_context") for a in attempts)
            )
            if not can_resume:
                return unavailable(
                    "INVOCATION_ALREADY_SETTLED"
                    if record["state"] in {"settled_metadata", "applied"}
                    else "INVOCATION_UNCERTAIN"
                )
            route = gateway._config.routes[request.task_type]
            digest = routing_digest()
            for attempt in attempts:
                context = attempt["sdk_context"]
                index = context["candidate_index"]
                if context["routing_digest"] != digest or not 0 <= index < len(route.candidates):
                    return unavailable("INVOCATION_CONFLICT")
                provider = route.candidates[index].provider
                if (
                    context["provider_digest"] != binding("provider", provider)
                    or context["external"] != gateway._config.providers[provider].external
                ):
                    return unavailable("INVOCATION_CONFLICT")
                if context["external"]:
                    external_used.add(context["provider_digest"])
            context = attempts[-1]["sdk_context"]
            if context["continuation"] == "retry":
                first_candidate, first_retry = (
                    context["candidate_index"],
                    context["retry_index"] + 1,
                )
            elif context["continuation"] == "fallback":
                first_candidate = context["candidate_index"] + 1
            else:
                return unavailable("INVOCATION_ALREADY_SETTLED")
    except Exception:
        return unavailable("INVOCATION_UNAVAILABLE")

    from ai_gateway.gateway import _BACKOFF_BASE_SECONDS, _BACKOFF_MAX_SECONDS

    calls = 0
    last = None
    route = gateway._config.routes[request.task_type]
    for index in range(first_candidate, len(route.candidates)):
        retries = (
            route.max_retries
            if route.max_retries is not None
            else gateway._config.defaults.max_retries
        )
        for retry in range(first_retry if index == first_candidate else 0, 1 + retries):
            if retry:
                gateway._sleep(min(_BACKOFF_BASE_SECONDS * 2 ** (retry - 1), _BACKOFF_MAX_SECONDS))
                current = gateway._config.routes[request.task_type]
                allowed = (
                    current.max_retries
                    if current.max_retries is not None
                    else gateway._config.defaults.max_retries
                )
                if retry > allowed:
                    break
            try:
                plan = gateway.prepare_single_attempt(request, candidate_index=index)
            except ValueError:
                break
            if (
                plan.external
                and external_used - {binding("provider", plan.provider)}
                and not request.privacy_policy.allow_cross_provider_fallback
            ):
                break
            limits = gateway._config.budgets
            try:
                record = store.dispatch(
                    record["invocation_id"],
                    actor,
                    expected_fence=record["fence"],
                    attempt_id=uuid4().hex,
                    estimated_cost_micros=plan.estimated_cost_micros,
                    request_cost_cap=min(
                        limits.per_request_max_cost_micros,
                        request.cost_budget.max_estimated_cost_micros
                        if request.cost_budget.max_estimated_cost_micros is not None
                        else limits.per_request_max_cost_micros,
                    ),
                    student_limit=limits.student_daily_requests,
                    platform_limit=limits.platform_daily_requests,
                    student_cost_limit=limits.student_daily_max_cost_micros,
                    platform_cost_limit=limits.platform_daily_max_cost_micros,
                    context_guard=context_guard,
                    recover_after=gateway._now() + timedelta(seconds=plan.timeout_s),
                    sdk_context={
                        "routing_digest": routing_digest(),
                        "candidate_index": index,
                        "retry_index": retry,
                        "provider_digest": binding("provider", plan.provider),
                        "external": plan.external,
                        "continuation": "none",
                    },
                )
            except InvocationBudgetExceeded:
                last = unavailable("BUDGET_EXCEEDED", last)
                break
            except Exception:
                return unavailable("INVOCATION_UNAVAILABLE", last)
            # Process exit leaves this separately committed attempt unknown.
            try:
                response = gateway.invoke_single_attempt(plan, legacy_only=context_guard is None)
            except Exception:
                return unavailable("INVOCATION_UNCERTAIN", last)
            calls += response.provider_calls
            if plan.external and response.provider_calls:
                external_used.add(binding("provider", plan.provider))
            try:
                if response.provider_calls != 1:
                    store.mark_unknown(
                        record["invocation_id"], actor, expected_fence=record["fence"]
                    )
                    return unavailable(
                        "INVOCATION_UNCERTAIN",
                        response.model_copy(update={"provider_calls": calls}),
                    )
                record = store.settle_metadata(
                    record["invocation_id"],
                    actor,
                    expected_fence=record["fence"],
                    attempt_id=record["attempts"][-1]["attempt_id"],
                    retryable_failure=response.retry_disposition != "none",
                    retry_disposition=response.retry_disposition,
                    audit=AuditRecord(
                        request_id=request.request_id,
                        trace_id=response.trace_id,
                        student_pseudonym=request.student_pseudonym,
                        task_type=request.task_type.value,
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
                        created_at=gateway._now(),
                    ),
                )
            except Exception:
                return unavailable(
                    "INVOCATION_UNCERTAIN", response.model_copy(update={"provider_calls": calls})
                )
            last = response.model_copy(
                update={"provider_calls": calls, "retry_disposition": "none"}
            )
            if response.status == "ok" or response.retry_disposition == "none":
                return last
            if response.retry_disposition == "fallback":
                break
    if record["state"] == "prepared" and last is None:
        try:
            store.cancel(record["invocation_id"], actor, expected_fence=record["fence"])
        except Exception:
            return unavailable("INVOCATION_UNAVAILABLE")
    return last or unavailable("MODEL_UNAVAILABLE")
