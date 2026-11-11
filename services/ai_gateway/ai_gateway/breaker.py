"""按供应商的熔断器：连续失败达到阈值后熔断，冷却后放行一次探测。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

BreakerState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(
        self, *, failure_threshold: int, cooldown_seconds: float, monotonic: Callable[[], float]
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._monotonic = monotonic
        self._failures = 0
        self._state: BreakerState = "closed"
        self._opened_at = 0.0

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == "open"

    @property
    def is_half_open(self) -> bool:
        return self._state == "half_open"

    def would_block(self) -> bool:
        """只读判断：此刻是否处于熔断且尚未冷却完。"""
        return self._state == "open" and self._monotonic() - self._opened_at < self._cooldown

    def allow(self) -> bool:
        """是否放行一次调用。熔断冷却结束时转入半开并放行一次探测。"""
        if self._state == "open":
            if self.would_block():
                return False
            self._state = "half_open"
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        if self._state == "half_open":
            self._trip()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = "open"
        self._opened_at = self._monotonic()
        self._failures = 0
