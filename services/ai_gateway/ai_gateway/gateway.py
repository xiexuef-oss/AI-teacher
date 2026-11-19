"""Model Gateway：任务路由 → 可用性与合规检查 → 预算 → 熔断与重试 → 输出校验 → 降级 → 审计。

网关从不抛出供应商异常，也不把供应商的错误文本放进响应；调用方只会看到枚举化的 error_code。
降级时 validated_output 为 None，由上层改用审核解析或规则文案。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from ai_gateway.audit import AuditRecord, AuditSink, InMemoryAuditSink
from ai_gateway.breaker import CircuitBreaker
from ai_gateway.budget import (
    BudgetStore,
    InMemoryBudgetStore,
    cost_micros,
    count_image_units,
    estimate_request_cost_micros,
)
from ai_gateway.config import Candidate, GatewayConfig, ProviderConfig, RouteConfig, load_config
from ai_gateway.dto import (
    SUPPORTED_RESPONSE_SCHEMA_VERSION,
    GatewayRequest,
    GatewayResponse,
    TaskType,
    Usage,
)
from ai_gateway.errors import RETRYABLE_KINDS, OutputRejected, ProviderError
from ai_gateway.prompts import PROMPT_VERSION
from ai_gateway.providers.base import ProviderAdapter, ProviderResult
from ai_gateway.providers.mock import MockProvider
from ai_gateway.providers.openai_compat import OpenAICompatAdapter
from ai_gateway.validation import OutputValidator
from ai_gateway.visual_templates import VisualRegistry

logger = logging.getLogger("ai_gateway")

_BACKOFF_BASE_SECONDS = 0.2
_BACKOFF_MAX_SECONDS = 2.0


@dataclass(frozen=True)
class CandidateStatus:
    """某个候选此刻能否使用，以及不能用的原因（用于诊断，不含任何密钥）。"""

    provider: str
    model: str | None
    usable: bool
    reason: str | None


@dataclass(frozen=True)
class SingleAttemptPlan:
    provider: str
    model: str
    estimated_cost_micros: int
    timeout_s: float
    request_json: str = field(repr=False)
    owner: object = field(repr=False, compare=False)
    external: bool
    consumed: bool = field(default=False, init=False)


@dataclass
class _CallState:
    reserved_estimate: int = 0
    quota_day: date | None = None
    provider_calls: int = 0
    timeouts: int = 0
    other_failures: int = 0
    schema_invalid: int = 0
    content_blocked: int = 0
    over_budget: int = 0
    dispatch_error: str | None = None

    def error_code(self) -> str:
        if self.content_blocked:
            return "CONTENT_BLOCKED"
        if self.schema_invalid:
            return "SCHEMA_INVALID"
        if self.dispatch_error:
            return self.dispatch_error
        if self.over_budget:
            return "BUDGET_EXCEEDED"
        if self.timeouts and not self.other_failures:
            return "TIMEOUT"
        return "MODEL_UNAVAILABLE"

    def schema_valid(self) -> bool | None:
        return False if (self.schema_invalid or self.content_blocked) else None


class ModelGateway:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        adapters: Mapping[str, ProviderAdapter],
        env: Mapping[str, str],
        environment: str,
        allow_external_calls: bool,
        validator: OutputValidator,
        audit: AuditSink,
        budget_store: BudgetStore,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._config = config
        self._adapters = dict(adapters)
        self._env = env
        self._environment = environment
        self._allow_external_calls = allow_external_calls
        self._external_dispatch_mode = "legacy"
        self._durable_sdk = None
        self._validator = validator
        self._audit = audit
        self._budget_store = budget_store
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._single_lock = Lock()
        self._dispatch_guard: Callable[[], bool] | None = None
        breaker = config.defaults.circuit_breaker
        self._breakers = {
            name: CircuitBreaker(
                failure_threshold=breaker.failure_threshold,
                cooldown_seconds=breaker.cooldown_seconds,
                monotonic=monotonic,
            )
            for name in config.providers
        }

    def require_durable_external_calls(self) -> None:
        """One-way business startup policy; standalone SDK use stays compatible."""
        if self._external_dispatch_mode == "legacy":
            self._external_dispatch_mode = "durable"

    def bind_durable_invocations(self, store, *, secret: str) -> None:
        """Explicit standalone wiring; business startup policies still take precedence."""
        if (
            not isinstance(secret, str)
            or not secret
            or any(
                not callable(getattr(store, name, None))
                for name in ("prepare", "dispatch", "cancel", "mark_unknown", "settle_metadata")
            )
            or not callable(getattr(getattr(store, "cost_gate", None), "can_send", None))
        ):
            raise ValueError("Durable invocation store and stable secret required")
        if self._durable_sdk is not None and (
            self._durable_sdk[0] is not store or self._durable_sdk[1] != secret
        ):
            raise ValueError("Durable invocation binding cannot be replaced")
        self._durable_sdk = (store, secret)

    def disable_external_calls(self) -> None:
        """Managed runtime policy; later flag or candidate changes cannot open it."""
        self._external_dispatch_mode = "disabled"

    def bind_dispatch_guard(self, guard: Callable[[], bool] | None) -> None:
        """Trusted server startup wiring; never derived from client request fields."""
        if guard is not None and not callable(guard):
            raise ValueError("Dispatch guard must be callable")
        self._dispatch_guard = guard

    def _dispatch_error(self) -> str | None:
        guards = [self._dispatch_guard]
        if self._durable_sdk is not None and self._external_dispatch_mode == "legacy":
            guards.append(self._durable_sdk[0].cost_gate.can_send)
        for guard in guards:
            if guard is None:
                continue
            try:
                allowed = guard()
            except Exception:
                logger.warning("shared model dispatch guard unavailable")
                return "BUDGET_UNAVAILABLE"
            if allowed is not True:
                return "BUDGET_EXCEEDED" if allowed is False else "BUDGET_UNAVAILABLE"
        return None

    @property
    def external_calls_possible(self) -> bool:
        """是否存在此刻真的可能被调用到的外部供应商。"""
        return any(
            status.usable and self._config.providers[status.provider].external
            for task in TaskType
            for status in self.describe_route(task)
        )

    def provider_is_mock(self, name: str | None) -> bool:
        provider = self._config.providers.get(name) if name is not None else None
        return provider is not None and provider.kind == "mock"

    # ------------------------------------------------------------ 可用性

    @staticmethod
    def _pricing_verified(provider: ProviderConfig, request: GatewayRequest | None) -> bool:
        if not provider.external:
            return True
        pricing = provider.pricing
        if pricing is None or not pricing.verified:
            return False
        return (
            request is None
            or not count_image_units(request)
            or pricing.image_unit_micros is not None
        )

    def _resolve(
        self, candidate: Candidate, request: GatewayRequest | None = None
    ) -> tuple[str | None, str | None]:
        """返回模型与不可用原因；有请求时检查其图像报价，不看熔断状态。"""
        provider = self._config.providers[candidate.provider]
        if provider.external != (provider.kind == "openai_compatible"):
            return None, "provider_kind_mismatch"
        if not provider.enabled:
            return None, "disabled"
        if provider.environments is not None and self._environment not in provider.environments:
            return None, "not_allowed_in_environment"
        if provider.external:
            if not self._allow_external_calls or self._external_dispatch_mode == "disabled":
                return None, "external_calls_not_allowed"
            if not provider.compliance_approved:
                return None, "not_compliance_approved"
            for env_name in (provider.base_url_env, provider.api_key_env):
                if not self._env.get(env_name or ""):
                    return None, f"missing_env:{env_name}"
            if not self._pricing_verified(provider, request):
                return None, "pricing_unverified"
        model = candidate.model or self._env.get(candidate.model_env or "")
        if not model:
            return None, f"missing_env:{candidate.model_env}"
        if candidate.provider not in self._adapters:
            return model, "adapter_unavailable"
        return model, None

    def describe_route(self, task_type: TaskType) -> list[CandidateStatus]:
        statuses = []
        for candidate in self._config.routes[task_type].candidates:
            model, reason = self._resolve(candidate)
            if reason is None and self._breakers[candidate.provider].would_block():
                reason = "circuit_open"
            statuses.append(CandidateStatus(candidate.provider, model, reason is None, reason))
        return statuses

    # ------------------------------------------------------------ 调用

    def _candidate_available(
        self, name: str, model: str, request: GatewayRequest, *, legacy: bool = False
    ) -> bool:
        if (
            legacy
            and self._external_dispatch_mode != "legacy"
            and self._config.providers[name].external
        ):
            return False
        return any(
            c.provider == name and self._resolve(c, request) == (model, None)
            for c in self._config.routes[request.task_type].candidates
        )

    def _estimate(self, name: str, request: GatewayRequest) -> int:
        provider = self._config.providers[name]
        return estimate_request_cost_micros(
            provider.pricing if provider.external else None, request
        )

    def prepare_single_attempt(
        self, request: GatewayRequest, *, candidate_index: int | None = None
    ) -> SingleAttemptPlan:
        """Internal durable orchestration seam; does not reserve quota or send."""
        if request.response_schema_version != SUPPORTED_RESPONSE_SCHEMA_VERSION:
            raise ValueError("Unsupported response schema")
        route = self._config.routes[request.task_type]
        cap = self._config.budgets.per_request_max_cost_micros
        if request.cost_budget.max_estimated_cost_micros is not None:
            cap = min(cap, request.cost_budget.max_estimated_cost_micros)
        candidates = route.candidates
        if candidate_index is not None:
            if type(candidate_index) is not int or not 0 <= candidate_index < len(candidates):
                raise ValueError("Invalid candidate index")
            candidates = [candidates[candidate_index]]
        for candidate in candidates:
            model, reason = self._resolve(candidate, request)
            if (
                reason is not None
                or model is None
                or self._breakers[candidate.provider].would_block()
            ):
                continue
            estimate = self._estimate(candidate.provider, request)
            if estimate <= cap:
                return SingleAttemptPlan(
                    candidate.provider,
                    model,
                    estimate,
                    (route.timeout_ms or self._config.defaults.timeout_ms) / 1000,
                    request.model_dump_json(),
                    self,
                    self._config.providers[candidate.provider].external,
                )
        raise ValueError("No usable candidate within budget")

    def invoke_single_attempt(
        self, plan: SingleAttemptPlan, *, legacy_only=False
    ) -> GatewayResponse:
        """One send only. Caller must first commit durable dispatch and budget.

        Deliberately does not call _finish: audit and cost settlement belong to
        the durable invocation transaction, not independent legacy sinks.
        """
        request = GatewayRequest.model_validate_json(plan.request_json)
        started = self._monotonic()
        with self._single_lock:
            available = plan.owner is self and not plan.consumed
            if available:
                object.__setattr__(plan, "consumed", True)

        def response(
            *, error=None, output=None, usage=None, calls=0, confidence=None, retry="none"
        ):
            route = self._config.routes[request.task_type]
            return GatewayResponse(
                provider=plan.provider,
                model_id=plan.model,
                status="ok" if output is not None else "degraded",
                validated_output=output,
                usage=usage or Usage(),
                latency_ms=max(0, round((self._monotonic() - started) * 1000)),
                confidence=confidence,
                review_required=route.min_confidence is not None
                and (confidence is None or confidence < route.min_confidence),
                error_code=error,
                trace_id=request.trace_id,
                provider_calls=calls,
                prompt_version=PROMPT_VERSION if output is not None else None,
                retry_disposition=retry,
            )

        if not available:
            return response(error="ATTEMPT_ALREADY_USED")
        # Recheck config gates after dispatch; a revoked candidate is never sent.
        breaker = self._breakers.get(plan.provider)
        if (
            not self._candidate_available(plan.provider, plan.model, request)
            or breaker is None
            or not breaker.allow()
        ):
            return response(error="MODEL_UNAVAILABLE")
        if error := self._dispatch_error():
            return response(error=error)
        if legacy_only and self._external_dispatch_mode != "legacy":
            return response(error="MODEL_UNAVAILABLE")
        # A shared guard can perform IO; recheck revocation, price and request cap afterwards.
        if not self._candidate_available(plan.provider, plan.model, request):
            return response(error="MODEL_UNAVAILABLE")
        if self._config.providers[plan.provider].external != plan.external:
            return response(error="MODEL_UNAVAILABLE")
        if self._estimate(plan.provider, request) > min(
            plan.estimated_cost_micros,
            self._config.budgets.per_request_max_cost_micros,
            request.cost_budget.max_estimated_cost_micros
            if request.cost_budget.max_estimated_cost_micros is not None
            else self._config.budgets.per_request_max_cost_micros,
        ):
            return response(error="BUDGET_EXCEEDED")
        try:
            result = self._adapters[plan.provider].invoke(
                model=plan.model, request=request, timeout_s=plan.timeout_s
            )
        except ProviderError as error:
            breaker.record_failure()
            return response(
                error="TIMEOUT" if error.kind == "timeout" else "MODEL_UNAVAILABLE",
                calls=1,
                retry=("retry" if error.kind in RETRYABLE_KINDS else "fallback")
                if error.outcome_known and error.kind != "timeout"
                else "none",
            )
        except Exception:
            breaker.record_failure()
            logger.exception("Single provider attempt failed request_id=%s", request.request_id)
            return response(error="MODEL_UNAVAILABLE", calls=1)
        breaker.record_success()
        usage = self._usage(self._config.providers[plan.provider], request, result)
        try:
            output = self._validator.validate(request.task_type, result.output, request.constraints)
        except OutputRejected as error:
            return response(
                error=error.code,
                usage=usage,
                calls=1,
                retry="fallback" if error.code == "SCHEMA_INVALID" else "none",
            )
        return response(output=output, usage=usage, calls=1, confidence=result.confidence)

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        if self._durable_sdk is not None and self._external_dispatch_mode == "legacy":
            from ai_gateway.durable import invoke

            return invoke(self, request, *self._durable_sdk)
        started = self._monotonic()
        state = _CallState()

        if request.response_schema_version != SUPPORTED_RESPONSE_SCHEMA_VERSION:
            return self._finish(
                request, started, state, status="error", error_code="UNSUPPORTED_SCHEMA_VERSION"
            )

        day = self._now().astimezone(UTC).date()
        budgets = self._config.budgets
        if budgets.has_daily_cost_limits:
            # Legacy invoke cannot atomically reserve a daily amount. Only the
            # durable orchestration seam may authorize sends under these caps.
            return self._finish(
                request, started, state, status="degraded", error_code="BUDGET_UNAVAILABLE"
            )
        cost_cap = budgets.per_request_max_cost_micros
        if request.cost_budget.max_estimated_cost_micros is not None:
            cost_cap = min(cost_cap, request.cost_budget.max_estimated_cost_micros)

        route = self._config.routes[request.task_type]
        external_tried = False
        for candidate in route.candidates:
            provider = self._config.providers[candidate.provider]
            if self._external_dispatch_mode != "legacy" and provider.external:
                continue
            model, reason = self._resolve(candidate, request)
            if reason is not None or model is None:
                continue
            if (
                provider.external
                and external_tried
                and not request.privacy_policy.allow_cross_provider_fallback
            ):
                continue
            if self._estimate(candidate.provider, request) > cost_cap:
                state.over_budget += 1
                continue
            if not self._breakers[candidate.provider].allow():
                continue

            if state.quota_day is None:
                if error := self._dispatch_error():
                    return self._finish(
                        request, started, state, status="degraded", error_code=error
                    )
                try:
                    admitted = self._budget_store.try_consume_request(
                        request.student_pseudonym,
                        day,
                        student_limit=budgets.student_daily_requests,
                        platform_limit=budgets.platform_daily_requests,
                    )
                except Exception:
                    logger.warning("budget admission unavailable request_id=%s", request.request_id)
                    return self._finish(
                        request, started, state, status="degraded", error_code="BUDGET_UNAVAILABLE"
                    )
                if not admitted:
                    return self._finish(
                        request, started, state, status="degraded", error_code="BUDGET_EXCEEDED"
                    )
                state.quota_day = day

            external_tried = external_tried or provider.external
            outcome = self._call_candidate(
                candidate.provider, model, request, route, state, cost_cap
            )
            if outcome is None:
                if state.dispatch_error:
                    break
                continue

            output, result = outcome
            usage = self._usage(provider, request, result)
            review_required = route.min_confidence is not None and (
                result.confidence is None or result.confidence < route.min_confidence
            )
            return self._finish(
                request,
                started,
                state,
                status="ok",
                error_code=None,
                provider=candidate.provider,
                model=model,
                output=output,
                usage=usage,
                confidence=result.confidence,
                review_required=review_required,
            )

        return self._finish(
            request, started, state, status="degraded", error_code=state.error_code()
        )

    def _call_candidate(
        self,
        name: str,
        model: str,
        request: GatewayRequest,
        route: RouteConfig,
        state: _CallState,
        cost_cap: int,
    ) -> tuple[dict[str, Any], ProviderResult] | None:
        breaker = self._breakers[name]
        adapter = self._adapters[name]
        defaults = self._config.defaults
        timeout_s = (route.timeout_ms or defaults.timeout_ms) / 1000
        max_retries = route.max_retries if route.max_retries is not None else defaults.max_retries
        attempts = 1 if breaker.is_half_open else 1 + max_retries

        for attempt in range(attempts):
            if attempt:
                self._sleep(min(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), _BACKOFF_MAX_SECONDS))
            if not self._candidate_available(name, model, request, legacy=True):
                state.other_failures += 1
                return None
            estimate = self._estimate(name, request)
            if state.reserved_estimate + estimate > min(
                cost_cap, self._config.budgets.per_request_max_cost_micros
            ):
                state.over_budget += 1
                return None
            if error := self._dispatch_error():
                state.dispatch_error = error
                return None
            # Commit the conservative estimate before an adapter can send. A
            # worker exit must not erase costs for potentially sent attempts.
            if estimate:
                try:
                    self._budget_store.record_cost(
                        request.student_pseudonym,
                        state.quota_day or self._now().astimezone(UTC).date(),
                        cost_micros=estimate,
                    )
                except Exception:
                    logger.warning(
                        "attempt cost accounting unavailable request_id=%s", request.request_id
                    )
                    state.dispatch_error = "BUDGET_UNAVAILABLE"
                    return None
            state.reserved_estimate += estimate
            # The budget commit is an I/O gap: authorization, pause and prices
            # may have changed. Committed estimates are not automatically refunded.
            if error := self._dispatch_error():
                state.dispatch_error = error
                return None
            if self._config.budgets.has_daily_cost_limits:
                state.dispatch_error = "BUDGET_UNAVAILABLE"
                return None
            if not self._candidate_available(name, model, request, legacy=True):
                state.other_failures += 1
                return None
            if self._estimate(name, request) > estimate or state.reserved_estimate > min(
                cost_cap, self._config.budgets.per_request_max_cost_micros
            ):
                state.over_budget += 1
                return None
            state.provider_calls += 1
            try:
                result = adapter.invoke(model=model, request=request, timeout_s=timeout_s)
            except ProviderError as error:
                kind: str = error.kind
                logger.warning(
                    "provider %s failed: kind=%s request_id=%s", name, kind, request.request_id
                )
            except Exception:
                # 适配器的任何意外都不能冒出网关；堆栈只进日志。
                kind = "unavailable"
                logger.exception(
                    "provider %s raised unexpectedly request_id=%s", name, request.request_id
                )
            else:
                breaker.record_success()
                try:
                    output = self._validator.validate(
                        request.task_type, result.output, request.constraints
                    )
                except OutputRejected as rejected:
                    if rejected.code == "CONTENT_BLOCKED":
                        state.content_blocked += 1
                    else:
                        state.schema_invalid += 1
                    logger.warning(
                        "provider %s output rejected: %s request_id=%s",
                        name,
                        rejected.code,
                        request.request_id,
                    )
                    return None
                return output, result

            breaker.record_failure()
            if kind == "timeout":
                state.timeouts += 1
            else:
                state.other_failures += 1
            if kind not in RETRYABLE_KINDS or breaker.is_open:
                break
        return None

    def _usage(
        self, provider: ProviderConfig, request: GatewayRequest, result: ProviderResult
    ) -> Usage:
        image_units = (
            result.image_units if result.image_units is not None else count_image_units(request)
        )
        if not provider.external:
            estimated = 0
        elif result.input_tokens is not None and result.output_tokens is not None:
            estimated = cost_micros(
                provider.pricing,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                image_units=image_units,
            )
        else:
            estimated = estimate_request_cost_micros(provider.pricing, request)
        return Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            image_units=image_units or None,
            estimated_cost_micros=estimated,
        )

    def _finish(
        self,
        request: GatewayRequest,
        started: float,
        state: _CallState,
        *,
        status: str,
        error_code: str | None,
        provider: str | None = None,
        model: str | None = None,
        output: dict[str, Any] | None = None,
        usage: Usage | None = None,
        confidence: float | None = None,
        review_required: bool = False,
    ) -> GatewayResponse:
        usage = usage or Usage()
        latency_ms = max(0, round((self._monotonic() - started) * 1000))
        now = self._now()

        if state.provider_calls:
            day = state.quota_day or now.astimezone(UTC).date()
            # Daily budget accounting conservatively retains every potentially
            # sent attempt. Response usage describes only the returned result;
            # missing upstream usage never proves that failed attempts were free.
            extra = max(0, (usage.estimated_cost_micros or 0) - state.reserved_estimate)
            if extra:
                self._budget_store.record_cost(request.student_pseudonym, day, cost_micros=extra)

        record = AuditRecord(
            request_id=request.request_id,
            trace_id=request.trace_id,
            student_pseudonym=request.student_pseudonym,
            task_type=request.task_type.value,
            provider=provider,
            model_id=model,
            status=status,
            error_code=error_code,
            provider_calls=state.provider_calls,
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            image_units=usage.image_units,
            estimated_cost_micros=usage.estimated_cost_micros,
            schema_valid=True if status == "ok" else state.schema_valid(),
            review_required=review_required,
            created_at=now,
        )
        try:
            self._audit.record(record)
        except Exception:
            logger.exception("audit sink failed request_id=%s", request.request_id)

        return GatewayResponse(
            provider=provider,
            model_id=model,
            status=status,  # type: ignore[arg-type]
            validated_output=output,
            usage=usage,
            latency_ms=latency_ms,
            confidence=confidence,
            review_required=review_required,
            error_code=error_code,
            trace_id=request.trace_id,
            provider_calls=state.provider_calls,
            prompt_version=PROMPT_VERSION if status == "ok" else None,
        )


def build_gateway(
    config: GatewayConfig | Path | str,
    *,
    env: Mapping[str, str],
    environment: str,
    allow_external_calls: bool,
    event_schema_path: Path | str,
    visual_registry_path: Path | str,
    audit: AuditSink | None = None,
    budget_store: BudgetStore | None = None,
    adapter_overrides: Mapping[str, ProviderAdapter] | None = None,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelGateway:
    """按配置组装网关。外部适配器只在所有前置条件满足时才会被构造。"""
    if not isinstance(config, GatewayConfig):
        config = load_config(config)
    overrides = dict(adapter_overrides or {})

    adapters: dict[str, ProviderAdapter] = {}
    for name, provider in config.providers.items():
        if name in overrides:
            adapters[name] = overrides[name]
        elif provider.kind == "mock":
            adapters[name] = MockProvider()
        elif (
            allow_external_calls
            and provider.enabled
            and provider.compliance_approved
            and env.get(provider.base_url_env or "")
            and env.get(provider.api_key_env or "")
        ):
            adapters[name] = OpenAICompatAdapter(
                base_url=env[provider.base_url_env or ""], api_key=env[provider.api_key_env or ""]
            )

    event_schema = json.loads(Path(event_schema_path).read_text(encoding="utf-8"))
    validator = OutputValidator(event_schema, VisualRegistry.load(visual_registry_path))
    return ModelGateway(
        config=config,
        adapters=adapters,
        env=env,
        environment=environment,
        allow_external_calls=allow_external_calls,
        validator=validator,
        audit=audit or InMemoryAuditSink(),
        budget_store=budget_store if budget_store is not None else InMemoryBudgetStore(),
        now=now or (lambda: datetime.now(UTC)),
        monotonic=monotonic,
        sleep=sleep,
    )
