"""网关内部的统一调用 DTO（docs/10）。不是面向学生的公开 API。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_RESPONSE_SCHEMA_VERSION = "1.0"


class TaskType(StrEnum):
    """逻辑任务类别。路由按任务类别配置，客户端不能选择或绕过。"""

    OCR_EXTRACT = "ocr_extract"
    HANDWRITING_UNDERSTAND = "handwriting_understand"
    KNOWLEDGE_CLASSIFY = "knowledge_classify"
    TUTOR_HINT = "tutor_hint"
    TUTOR_EXPLAIN = "tutor_explain"
    COMPLEX_REASONING = "complex_reasoning"
    SOLUTION_VERIFY = "solution_verify"
    VISUAL_SPEC = "visual_spec"
    REVIEW_PLAN = "review_plan"


class InputPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "json", "image_ref"]
    text: str | None = None
    data: dict[str, Any] | None = None
    media_ref: str | None = None


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(default=800, ge=1, le=8000)
    language: str = "zh-CN"
    # 输出里不允许出现的表述（例如独立作答阶段的最终答案）。出现即丢弃该输出。
    forbidden_substrings: list[str] = Field(default_factory=list)


class CostBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 只能把配置里的单请求上限收紧，不能放宽
    max_estimated_cost_micros: int | None = Field(default=None, ge=0)


class PrivacyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 默认只把数据交给第一个可用的外部供应商；它失败后不再转给别的外部供应商。
    allow_cross_provider_fallback: bool = False


class GatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    student_pseudonym: str
    task_type: TaskType
    input_parts: list[InputPart]
    constraints: Constraints = Field(default_factory=Constraints)
    trace_id: str
    cost_budget: CostBudget = Field(default_factory=CostBudget)
    privacy_policy: PrivacyPolicy = Field(default_factory=PrivacyPolicy)
    response_schema_version: str = SUPPORTED_RESPONSE_SCHEMA_VERSION


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    image_units: int | None = None
    # 估算值，只用于预算控制，不是账单
    estimated_cost_micros: int | None = None


class GatewayResponse(BaseModel):
    provider: str | None
    model_id: str | None
    status: Literal["ok", "degraded", "error"]
    validated_output: dict[str, Any] | None
    usage: Usage
    latency_ms: int
    confidence: float | None
    review_required: bool
    error_code: str | None
    trace_id: str
    provider_calls: int = 0
    prompt_version: str | None = None
