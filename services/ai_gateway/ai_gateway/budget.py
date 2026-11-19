"""成本预算：估算单次调用成本，记录每学生与平台的每日用量。

文本按完整消息的 UTF-8 字节数保守估算，图片另计；只用于预算控制，不能当作账单。
"""

from __future__ import annotations

import json
import math
from datetime import date
from threading import Lock
from typing import Protocol

from ai_gateway.config import Pricing
from ai_gateway.dto import GatewayRequest
from ai_gateway.prompts import build_messages

STUDENT_SCOPE = "student"
PLATFORM_SCOPE = "platform"
PLATFORM_KEY = "platform"


class BudgetStore(Protocol):
    def record_cost(self, student_key: str, day: date, *, cost_micros: int) -> None: ...
    def try_consume_request(
        self, student_key: str, day: date, *, student_limit: int, platform_limit: int
    ) -> bool: ...

    def get_requests(self, scope: str, key: str, day: date) -> int: ...

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None: ...


class InMemoryBudgetStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[tuple[str, str, date], int] = {}
        self._cost: dict[tuple[str, str, date], int] = {}

    def get_requests(self, scope: str, key: str, day: date) -> int:
        with self._lock:
            return self._requests.get((scope, key, day), 0)

    def record_cost(self, student_key: str, day: date, *, cost_micros: int) -> None:
        if cost_micros < 0:
            raise ValueError("Cost must be nonnegative")
        with self._lock:
            for slot in ((PLATFORM_SCOPE, PLATFORM_KEY, day), (STUDENT_SCOPE, student_key, day)):
                self._cost[slot] = self._cost.get(slot, 0) + cost_micros

    def get_cost_micros(self, scope: str, key: str, day: date) -> int:
        with self._lock:
            return self._cost.get((scope, key, day), 0)

    def try_consume_request(
        self, student_key: str, day: date, *, student_limit: int, platform_limit: int
    ) -> bool:
        student = (STUDENT_SCOPE, student_key, day)
        platform = (PLATFORM_SCOPE, PLATFORM_KEY, day)
        with self._lock:
            if (
                self._requests.get(student, 0) >= student_limit
                or self._requests.get(platform, 0) >= platform_limit
            ):
                return False
            for slot in (student, platform):
                self._requests[slot] = self._requests.get(slot, 0) + 1
            return True

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None:
        slot = (scope, key, day)
        with self._lock:
            self._requests[slot] = self._requests.get(slot, 0) + requests
            self._cost[slot] = self._cost.get(slot, 0) + cost_micros


def estimate_input_tokens(request: GatewayRequest) -> int:
    """Use complete message text UTF-8 bytes as conservative estimation units.

    Includes system instructions, JSON framing and the authorized reference
    catalog. Inline image bytes are image billing units, not text tokens. This
    estimate is not a vendor tokenizer result or an actual invoice.
    """
    messages = build_messages(request)
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            message["content"] = [
                {"type": "image_url"} if part.get("type") == "image_url" else part
                for part in content
            ]
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))


def count_image_units(request: GatewayRequest) -> int:
    return sum(1 for part in request.input_parts if part.kind == "image_ref")


def cost_micros(
    pricing: Pricing | None, *, input_tokens: int, output_tokens: int, image_units: int
) -> int:
    """没有定价（本地供应商）视为零成本。"""
    if pricing is None:
        return 0
    total = (
        input_tokens / 1000 * (pricing.input_per_1k_tokens_micros or 0)
        + output_tokens / 1000 * (pricing.output_per_1k_tokens_micros or 0)
        + image_units * (pricing.image_unit_micros or 0)
    )
    return math.ceil(total)


def estimate_request_cost_micros(pricing: Pricing | None, request: GatewayRequest) -> int:
    """调用前成本预估：完整文本消息、输出上限及配置的图像计费单位。"""
    return cost_micros(
        pricing,
        input_tokens=estimate_input_tokens(request),
        output_tokens=request.constraints.max_output_tokens,
        image_units=count_image_units(request),
    )
