"""成本预算：估算单次调用成本，记录每学生与平台的每日用量。

token 数是按字符数做的保守估算，只用于预算控制，不能当作账单。
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Protocol

from ai_gateway.config import Pricing
from ai_gateway.dto import GatewayRequest

STUDENT_SCOPE = "student"
PLATFORM_SCOPE = "platform"
PLATFORM_KEY = "platform"


class BudgetStore(Protocol):
    def get_requests(self, scope: str, key: str, day: date) -> int: ...

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None: ...


class InMemoryBudgetStore:
    def __init__(self) -> None:
        self._requests: dict[tuple[str, str, date], int] = {}
        self._cost: dict[tuple[str, str, date], int] = {}

    def get_requests(self, scope: str, key: str, day: date) -> int:
        return self._requests.get((scope, key, day), 0)

    def get_cost_micros(self, scope: str, key: str, day: date) -> int:
        return self._cost.get((scope, key, day), 0)

    def add(self, scope: str, key: str, day: date, *, requests: int, cost_micros: int) -> None:
        slot = (scope, key, day)
        self._requests[slot] = self._requests.get(slot, 0) + requests
        self._cost[slot] = self._cost.get(slot, 0) + cost_micros


def estimate_input_tokens(request: GatewayRequest) -> int:
    """按字符数估算输入 token，上取整到每字符一个 token（对中文偏保守）。"""
    chars = 0
    for part in request.input_parts:
        if part.text:
            chars += len(part.text)
        if part.data is not None:
            chars += len(json.dumps(part.data, ensure_ascii=False))
    return chars


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
    """调用前的成本上界：输出按 max_output_tokens 计。"""
    return cost_micros(
        pricing,
        input_tokens=estimate_input_tokens(request),
        output_tokens=request.constraints.max_output_tokens,
        image_units=count_image_units(request),
    )
