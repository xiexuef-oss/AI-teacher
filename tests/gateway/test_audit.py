"""审计追踪：每次调用一条记录，只含元数据（docs/10：日志脱敏、审计追踪）。"""

from __future__ import annotations

import dataclasses
import json

from ai_gateway import AuditRecord
from support.gateway_fakes import (
    SECRET_TEXT,
    ScriptedProvider,
    external_provider,
    hint_ok,
    local_provider,
    make_request,
    unavailable,
)


def test_successful_call_writes_one_audit_record(make_gateway):
    a = ScriptedProvider(hint_ok("这是模型输出正文"))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    h.gateway.invoke(make_request())

    assert len(h.audit.records) == 1
    record = h.audit.records[0]
    assert isinstance(record, AuditRecord)
    assert record.request_id == "req-1"
    assert record.trace_id == "trace-1"
    assert record.student_pseudonym == "stu_9f2c"
    assert record.task_type == "tutor_explain"
    assert record.provider == "a" and record.model_id == "x-model-1"
    assert record.status == "ok" and record.error_code is None
    assert record.schema_valid is True
    assert record.provider_calls == 1
    assert record.created_at == h.clock.now()


def test_degraded_call_is_audited_too(make_gateway):
    a = ScriptedProvider(unavailable())
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    h.gateway.invoke(make_request())

    record = h.audit.records[0]
    assert record.status == "degraded"
    assert record.error_code == "MODEL_UNAVAILABLE"
    assert record.provider is None
    assert record.provider_calls == 2


def test_schema_rejection_is_visible_in_audit(make_gateway):
    a = ScriptedProvider({"event_type": "hint", "payload": {}})
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    h.gateway.invoke(make_request())

    record = h.audit.records[0]
    assert record.error_code == "SCHEMA_INVALID"
    assert record.schema_valid is False


def test_audit_never_contains_input_or_output_text(make_gateway):
    a = ScriptedProvider(hint_ok("这是模型输出正文"))
    h = make_gateway({"a": external_provider()}, ["a"], {"a": a})

    h.gateway.invoke(make_request())

    dumped = json.dumps(dataclasses.asdict(h.audit.records[0]), default=str, ensure_ascii=False)
    assert SECRET_TEXT not in dumped
    assert "这是模型输出正文" not in dumped
    assert "test-key-not-real" not in dumped


def test_audit_sink_failure_does_not_break_the_call(make_gateway):
    m = ScriptedProvider(hint_ok())
    h = make_gateway({"m": local_provider()}, ["m"], {"m": m})

    def broken(record):
        raise OSError("disk full")

    h.audit.record = broken  # type: ignore[method-assign]

    response = h.gateway.invoke(make_request())

    assert response.status == "ok"
