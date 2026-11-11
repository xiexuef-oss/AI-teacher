from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_gateway.dto import GatewayRequest


@dataclass(frozen=True)
class ProviderResult:
    """适配器返回的原始结果。output 尚未校验，不能直接下发。"""

    output: dict[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    image_units: int | None = None
    confidence: float | None = None


class ProviderAdapter(Protocol):
    def invoke(self, *, model: str, request: GatewayRequest, timeout_s: float) -> ProviderResult:
        """调用一次模型。失败时抛 ProviderError，并归类 kind。"""
        ...
