"""路由配置的结构与加载。模型 ID、端点、密钥通过环境变量名引用，不写在配置里。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_gateway.dto import TaskType


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CircuitBreakerConfig(_Strict):
    failure_threshold: int = Field(ge=1)
    cooldown_seconds: float = Field(gt=0)


class Defaults(_Strict):
    timeout_ms: int = Field(gt=0)
    max_retries: int = Field(ge=0, le=5)
    circuit_breaker: CircuitBreakerConfig


class Budgets(_Strict):
    per_request_max_cost_micros: int = Field(ge=0)
    student_daily_requests: int = Field(ge=0)
    platform_daily_requests: int = Field(ge=0)


class Pricing(_Strict):
    """单价（微元）。None 表示尚未核验，这样的外部供应商不会被启用。"""

    input_per_1k_tokens_micros: int | None = Field(default=None, ge=0)
    output_per_1k_tokens_micros: int | None = Field(default=None, ge=0)
    image_unit_micros: int | None = Field(default=None, ge=0)

    @property
    def verified(self) -> bool:
        return (
            self.input_per_1k_tokens_micros is not None
            and self.output_per_1k_tokens_micros is not None
        )


class ProviderConfig(_Strict):
    kind: Literal["mock", "openai_compatible"]
    external: bool
    enabled: bool = False
    compliance_approved: bool = False
    # 允许加载该供应商的环境；None 表示不限制
    environments: list[str] | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    pricing: Pricing | None = None

    @model_validator(mode="after")
    def _check_external_fields(self) -> Self:
        if self.external:
            if self.kind == "mock":
                raise ValueError("mock 供应商不能标记为 external")
            if not self.base_url_env or not self.api_key_env:
                raise ValueError("外部供应商必须通过 base_url_env / api_key_env 引用环境变量")
        return self


class Candidate(_Strict):
    provider: str
    model: str | None = None
    model_env: str | None = None

    @model_validator(mode="after")
    def _exactly_one_model_reference(self) -> Self:
        if (self.model is None) == (self.model_env is None):
            raise ValueError("候选必须且只能提供 model 或 model_env 之一")
        return self


class RouteConfig(_Strict):
    candidates: list[Candidate] = Field(min_length=1)
    timeout_ms: int | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    # 设置后，置信度缺失或低于该值的输出会被标记为需要复核
    min_confidence: float | None = Field(default=None, ge=0, le=1)


class GatewayConfig(_Strict):
    version: Literal[1]
    defaults: Defaults
    budgets: Budgets
    providers: dict[str, ProviderConfig]
    routes: dict[TaskType, RouteConfig]

    @model_validator(mode="after")
    def _check_routes(self) -> Self:
        missing = set(TaskType) - set(self.routes)
        if missing:
            raise ValueError(f"缺少任务类别的路由：{sorted(t.value for t in missing)}")
        for task, route in self.routes.items():
            for candidate in route.candidates:
                if candidate.provider not in self.providers:
                    raise ValueError(f"{task.value} 引用了未定义的供应商 {candidate.provider}")
        return self


def load_config(path: Path | str) -> GatewayConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return GatewayConfig.model_validate(raw)
