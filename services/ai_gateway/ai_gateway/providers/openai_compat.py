"""OpenAI 兼容的 chat/completions 适配器。

未经真实供应商验证：百炼、DeepSeek、火山方舟的端点、协议兼容性、模型 ID 都要在接入前由负责人核验
（DECISIONS_PENDING Q-04A）。本适配器只有在总开关、供应商启用、合规核验、定价与环境变量全部就绪时
才会被网关构造，仓库里的示例配置不会触发它。

暂不支持图片输入：image_ref 需要媒体服务签发短期 URL，那部分还没有实现。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ai_gateway.dto import GatewayRequest
from ai_gateway.errors import ProviderError
from ai_gateway.prompts import build_messages
from ai_gateway.providers.base import ProviderResult


class OpenAICompatAdapter:
    def __init__(
        self, *, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(transport=transport)

    def __repr__(self) -> str:
        return f"OpenAICompatAdapter(base_url={self._base_url!r})"

    def invoke(self, *, model: str, request: GatewayRequest, timeout_s: float) -> ProviderResult:
        if any(part.kind == "image_ref" for part in request.input_parts):
            raise ProviderError("rejected", "image inputs are not supported by this adapter yet")

        body = {
            "model": model,
            "messages": build_messages(request),
            "response_format": {"type": "json_object"},
            "max_tokens": request.constraints.max_output_tokens,
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout_s,
            )
        except httpx.TimeoutException:
            raise ProviderError("timeout", "upstream request timed out") from None
        except httpx.HTTPError as error:
            raise ProviderError("unavailable", f"network error: {type(error).__name__}") from None

        # 错误信息里只放状态码，不回显上游响应体（可能带回密钥或请求内容）。
        if response.status_code == 429:
            raise ProviderError("rate_limited", "upstream returned HTTP 429")
        if response.status_code >= 500:
            raise ProviderError("unavailable", f"upstream returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError("rejected", f"upstream returned HTTP {response.status_code}")

        try:
            data: Any = response.json()
            content = data["choices"][0]["message"]["content"]
            output = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                "bad_response", "upstream body is not a usable completion"
            ) from None
        if not isinstance(output, dict):
            raise ProviderError("bad_response", "completion content is not a JSON object")

        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return ProviderResult(
            output=output,
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
        )


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
