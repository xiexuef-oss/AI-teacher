"""OpenAI 兼容的 chat/completions 适配器。

未经真实供应商验证：百炼、DeepSeek、火山方舟的端点、协议兼容性、模型 ID 都要在接入前由负责人核验
（DECISIONS_PENDING Q-04A）。本适配器只有在总开关、供应商启用、合规核验、定价与环境变量全部就绪时
才会被网关构造，仓库里的示例配置不会触发它。

图片仅接受服务端准备的有界 PNG/JPEG data URI；不下载远程 URL 或读取本地路径。
"""

from __future__ import annotations

import base64
import binascii
import io
import json
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

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
        _validate_images(request)

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
            raise ProviderError("rate_limited", "upstream returned HTTP 429", outcome_known=True)
        if response.status_code >= 500:
            raise ProviderError(
                "unavailable", f"upstream returned HTTP {response.status_code}", outcome_known=True
            )
        if response.status_code >= 400:
            raise ProviderError(
                "rejected", f"upstream returned HTTP {response.status_code}", outcome_known=True
            )

        try:
            data: Any = response.json()
            content = data["choices"][0]["message"]["content"]
            output = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                "bad_response", "upstream body is not a usable completion", outcome_known=True
            ) from None
        if not isinstance(output, dict):
            raise ProviderError(
                "bad_response", "completion content is not a JSON object", outcome_known=True
            )

        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return ProviderResult(
            output=output,
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
        )


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# Local adapter ceilings, independent of vendor-specific limits. Server settings may
# tighten these before preparing data URIs; none permits arbitrary URL fetching.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGES = 10


def _validate_images(request: GatewayRequest) -> None:
    images = [part for part in request.input_parts if part.kind == "image_ref"]
    if len(images) > MAX_IMAGES:
        raise ProviderError("rejected", "too many input images")
    total = 0
    for part in images:
        uri = part.media_ref or ""
        prefix, separator, encoded = uri.partition(",")
        formats = {"data:image/png;base64": "PNG", "data:image/jpeg;base64": "JPEG"}
        if not separator or prefix not in formats or not encoded:
            raise ProviderError("rejected", "image must be an inline PNG or JPEG data URI")
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ProviderError("rejected", "input image exceeds byte limit")
        try:
            data = base64.b64decode(encoded, validate=True)
            if base64.b64encode(data).decode("ascii") != encoded:
                raise ValueError("noncanonical base64")
            total += len(data)
            if len(data) > MAX_IMAGE_BYTES or total > MAX_TOTAL_IMAGE_BYTES:
                raise ProviderError("rejected", "input images exceed byte limit")
            with Image.open(io.BytesIO(data)) as image:
                if image.format != formats[prefix]:
                    raise ValueError("image MIME mismatch")
                if (
                    image.width * image.height > MAX_IMAGE_PIXELS
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("image dimensions or frame count exceed limits")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        except (
            ValueError,
            binascii.Error,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ):
            # Never echo image bytes, URI, paths or upstream secrets.
            raise ProviderError("rejected", "invalid or oversized inline image") from None
