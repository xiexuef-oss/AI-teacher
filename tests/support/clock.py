from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    """可手动拨动的时钟：同时提供墙上时间（UTC）与单调时间。"""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 10, 8, 0, 0, tzinfo=UTC)
        self._mono = 1000.0
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def advance(
        self, seconds: float = 0, *, minutes: float = 0, hours: float = 0, days: float = 0
    ) -> None:
        total = seconds + minutes * 60 + hours * 3600 + days * 86400
        self._now += timedelta(seconds=total)
        self._mono += total
