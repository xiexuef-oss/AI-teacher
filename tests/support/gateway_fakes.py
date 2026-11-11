"""模型网关测试用的假适配器与配置构造器。

外部模型供应商是不可避免的边界，这里用按脚本应答的假适配器代替；网关本身用真实代码。
"""

from __future__ import annotations

from typing import Any

from ai_gateway import (
    GatewayRequest,
    InMemoryAuditSink,
    InMemoryBudgetStore,
    InputPart,
    ModelGateway,
    ProviderError,
    ProviderResult,
    TaskType,
)
from support import CONTRACTS_DIR, REPO_ROOT
from support.clock import FakeClock

__all__ = ["FakeClock"]

EVENT_SCHEMA_PATH = CONTRACTS_DIR / "tutor_event.schema.json"
VISUAL_REGISTRY_PATH = REPO_ROOT / "packages" / "visual_templates" / "registry.json"
EXAMPLE_ROUTES_PATH = REPO_ROOT / "config" / "model_routes.example.yaml"

SECRET_TEXT = "SECRET-STUDENT-TEXT-4711"
FULL_ENV = {
    "X_BASE_URL": "https://models.invalid/v1",
    "X_API_KEY": "test-key-not-real",
    "X_MODEL": "x-model-1",
}


def hint_ok(text: str = "换个角度：先找到对称轴，再看开口方向。") -> dict[str, Any]:
    return {
        "event_type": "hint",
        "payload": {
            "level": 1,
            "total_levels": 3,
            "style": "rephrase",
            "text": text,
            "concept": "二次函数的单调性",
        },
    }


def visual_ok(**payload_overrides: Any) -> dict[str, Any]:
    payload = {
        "template_id": "quadratic_graph",
        "params": {"a": 1, "b": -2, "c": -3},
        "caption": "拖动 a 观察开口方向。",
        "static_fallback": "开口向上，对称轴 x=1。",
    }
    payload.update(payload_overrides)
    return {"event_type": "visual", "payload": payload}


class ScriptedProvider:
    """按顺序吐出预设结果的假适配器；元素可以是输出字典、ProviderResult 或要抛出的异常。

    脚本用完后重复最后一项。
    """

    def __init__(self, *script: Any) -> None:
        assert script, "至少给一个脚本项"
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def invoke(self, *, model: str, request: GatewayRequest, timeout_s: float) -> ProviderResult:
        self.calls.append({"model": model, "request": request, "timeout_s": timeout_s})
        item = self.script[min(len(self.calls), len(self.script)) - 1]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ProviderResult):
            return item
        return ProviderResult(output=item)


def timeout() -> ProviderError:
    return ProviderError("timeout", "upstream timed out after 8s (internal detail)")


def unavailable() -> ProviderError:
    return ProviderError("unavailable", "HTTP 503 from upstream (internal detail)")


def local_provider(*, enabled: bool = True, **extra: Any) -> dict[str, Any]:
    """非外部供应商（配置上与 Mock 同类）。"""
    return {
        "kind": "mock",
        "external": False,
        "enabled": enabled,
        "compliance_approved": True,
        "environments": ["local", "dev"],
        **extra,
    }


def external_provider(
    *, enabled: bool = True, approved: bool = True, **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "openai_compatible",
        "external": True,
        "enabled": enabled,
        "compliance_approved": approved,
        "base_url_env": "X_BASE_URL",
        "api_key_env": "X_API_KEY",
        "pricing": {
            "input_per_1k_tokens_micros": 1000,
            "output_per_1k_tokens_micros": 2000,
            "image_unit_micros": 5000,
        },
        **extra,
    }


def config_dict(providers: dict[str, dict], order: list[str], **overrides: Any) -> dict[str, Any]:
    """所有任务类型都走同一个候选顺序的最小配置；overrides 按顶层键浅合并。"""
    candidates = []
    for name in order:
        if providers[name]["external"]:
            candidates.append({"provider": name, "model_env": "X_MODEL"})
        else:
            candidates.append({"provider": name, "model": f"{name}-model"})
    config: dict[str, Any] = {
        "version": 1,
        "defaults": {
            "timeout_ms": 8000,
            "max_retries": 1,
            "circuit_breaker": {"failure_threshold": 3, "cooldown_seconds": 60},
        },
        "budgets": {
            "per_request_max_cost_micros": 50000,
            "student_daily_requests": 200,
            "platform_daily_requests": 20000,
        },
        "providers": providers,
        "routes": {task.value: {"candidates": list(candidates)} for task in TaskType},
    }
    for key, value in overrides.items():
        config[key] = {**config[key], **value}
    return config


class Harness:
    def __init__(
        self,
        gateway: ModelGateway,
        clock: FakeClock,
        audit: InMemoryAuditSink,
        budget: InMemoryBudgetStore,
    ) -> None:
        self.gateway = gateway
        self.clock = clock
        self.audit = audit
        self.budget = budget


def make_request(task: TaskType = TaskType.TUTOR_EXPLAIN, **overrides: Any) -> GatewayRequest:
    fields: dict[str, Any] = {
        "request_id": "req-1",
        "student_pseudonym": "stu_9f2c",
        "task_type": task,
        "input_parts": [InputPart(kind="text", text=f"{SECRET_TEXT} 讲讲单调性")],
        "trace_id": "trace-1",
    }
    fields.update(overrides)
    return GatewayRequest(**fields)
