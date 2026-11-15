from __future__ import annotations

from typing import Literal

ProviderErrorKind = Literal["timeout", "unavailable", "rate_limited", "rejected", "bad_response"]

# 只有这两类错误值得在同一供应商内重试
RETRYABLE_KINDS: frozenset[str] = frozenset({"timeout", "unavailable"})


class ProviderError(Exception):
    """供应商适配器抛出的、已归类的错误。message 只进日志，不进任何响应。"""

    def __init__(self, kind: ProviderErrorKind, message: str = "") -> None:
        super().__init__(message)
        self.kind: ProviderErrorKind = kind


class OutputRejected(Exception):
    """模型输出没有通过校验，不得下发。"""

    def __init__(
        self, code: Literal["SCHEMA_INVALID", "CONTENT_BLOCKED"], detail: str = ""
    ) -> None:
        super().__init__(detail)
        self.code = code
