"""审计记录：每次网关调用一条，只有元数据，不含学生原文、图片或模型输出正文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuditRecord:
    request_id: str
    trace_id: str
    student_pseudonym: str
    task_type: str
    provider: str | None
    model_id: str | None
    status: str
    error_code: str | None
    provider_calls: int
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    image_units: int | None
    estimated_cost_micros: int | None
    schema_valid: bool | None
    review_required: bool
    created_at: datetime


class AuditSink(Protocol):
    def record(self, record: AuditRecord) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def record(self, record: AuditRecord) -> None:
        self.records.append(record)
