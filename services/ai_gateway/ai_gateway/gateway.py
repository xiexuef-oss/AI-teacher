"""Model Gateway：任务路由 → 可用性与合规检查 → 预算 → 熔断与重试 → 输出校验 → 降级 → 审计。

网关从不抛出供应商异常，也不把供应商的错误文本放进响应；调用方只会看到枚举化的 error_code。
降级时 validated_output 为 None，由上层改用审核解析或规则文案。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_gateway.audit import AuditRecord, AuditSink, InMemoryAuditSink
from ai_gateway.breaker import CircuitBreaker
from ai_gateway.budget import (
    PLATFORM_KEY,
    PLATFORM_SCOPE,
    STUDENT_SCOPE,
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


@dataclass
class _CallState:
    provider_calls: int = 0
    timeouts: int = 0
    other_failures: int = 0
    schema_invalid: int = 0
    content_blocked: int = 0
    over_budget: int = 0

    def error_code(self) -> str:
        if self.content_blocked:
            return "CONTENT_BLOCKED"
        if self.schema_invalid:
            return "SCHEMA_INVALID"
        if self.timeouts and not self.other_failures:
            return "TIMEOUT"
        if not self.provider_calls and self.over_budget:
            return "BUDGET_EXCEEDED"
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
        self._validator = validator
        self._audit = audit
        self._budget_store = budget_store
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        breaker = config.defaults.circuit_breaker
        self._breakers = {
            name: CircuitBreaker(
                failure_threshold=breaker.failure_threshold,
                cooldown_seconds=breaker.cooldown_seconds,
                monotonic=monotonic,
            )
            for name in config.providers
        }

    @property
    def external_calls_possible(self) -> bool:
        """是否存在此刻真的可能被调用到的外部供应商。"""
        return any(
            status.usable and self._config.providers[status.provider].external
            for task in TaskType
            for status in self.describe_route(task)
        )

    # ------------------------------------------------------------ 可用性

    def _resolve(self, candidate: Candidate) -> tuple[str | None, str | None]:
        """返回 (模型, 不可用原因)。只看配置与环境，不看熔断状态。"""
        provider = self._config.providers[candidate.provider]
        if not provider.enabled:
            return None, "disabled"
        if provider.environments is not None and self._environment not in provider.environments:
            return None, "not_allowed_in_environment"
        if provider.external:
            if not self._allow_external_calls:
                return None, "external_calls_not_allowed"
            if not provider.compliance_approved:
                return None, "not_compliance_approved"
            for env_name in (provider.base_url_env, provider.api_key_env):
                if not self._env.get(env_name or ""):
                    return None, f"missing_env:{env_name}"
            if provider.pricing is None or not provider.pricing.verified:
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

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        started = self._monotonic()
        state = _CallState()

        if request.response_schema_version != SUPPORTED_RESPONSE_SCHEMA_VERSION:
            return self._finish(
                request, started, state, status="error", error_code="UNSUPPORTED_SCHEMA_VERSION"
            )

        day = self._now().astimezone(UTC).date()
        budgets = self._config.budgets
        student_used = self._budget_store.get_requests(
            STUDENT_SCOPE, request.student_pseudonym, day
        )
        platform_used = self._budget_store.get_requests(PLATFORM_SCOPE, PLATFORM_KEY, day)
        if (
            student_used >= budgets.student_daily_requests
            or platform_used >= budgets.platform_daily_requests
        ):
            return self._finish(
                request, started, state, status="degraded", error_code="BUDGET_EXCEEDED"
            )

        cost_cap = budgets.per_request_max_cost_micros
        if request.cost_budget.max_estimated_cost_micros is not None:
            cost_cap = min(cost_cap, request.cost_budget.max_estimated_cost_micros)

        route = self._config.routes[request.task_type]
        external_tried = False
        for candidate in route.candidates:
            provider = self._config.providers[candidate.provider]
            model, reason = self._resolve(candidate)
            if reason is not None or model is None:
                continue
            if (
                provider.external
                and external_tried
                and not request.privacy_policy.allow_cross_provider_fallback
            ):
                continue
            pricing = provider.pricing if provider.external else None
            if estimate_request_cost_micros(pricing, request) > cost_cap:
                state.over_budget += 1
                continue
            if not self._breakers[candidate.provider].allow():
                continue

            external_tried = external_tried or provider.external
            outcome = self._call_candidate(candidate.provider, model, request, route, state)
            if outcome is None:
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
        self, name: str, model: str, request: GatewayRequest, route: RouteConfig, state: _CallState
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
            day = now.astimezone(UTC).date()
            spent = usage.estimated_cost_micros or 0
            self._budget_store.add(
                STUDENT_SCOPE, request.student_pseudonym, day, requests=1, cost_micros=spent
            )
            self._budget_store.add(PLATFORM_SCOPE, PLATFORM_KEY, day, requests=1, cost_micros=spent)

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
        budget_store=budget_store or InMemoryBudgetStore(),
        now=now or (lambda: datetime.now(UTC)),
        monotonic=monotonic,
        sleep=sleep,
    )
