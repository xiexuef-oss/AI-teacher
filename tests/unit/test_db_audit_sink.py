"""SQL audit mapping preserves metadata and ignores undeclared attributes."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_gateway import AuditRecord
from tutor_api.gateway_io import DbAuditSink
from tutor_api.models import ModelCallAudit


def test_sql_audit_preserves_metadata_without_copying_extra_fields():
    @dataclass(frozen=True)
    class ExtendedRecord(AuditRecord):
        secret: str = "must-not-be-persisted"

    values = dict(
        request_id="request",
        trace_id="trace",
        student_pseudonym="stu_test",
        task_type="tutor_explain",
        provider="local",
        model_id="mock",
        status="degraded",
        error_code="TIMEOUT",
        provider_calls=2,
        latency_ms=42,
        input_tokens=11,
        output_tokens=None,
        image_units=1,
        estimated_cost_micros=23,
        schema_valid=None,
        review_required=True,
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    engine = create_engine("sqlite://")
    try:
        ModelCallAudit.__table__.create(engine)
        factory = sessionmaker(engine)
        DbAuditSink(factory).record(ExtendedRecord(**values))
        with factory() as db:
            row = db.scalars(select(ModelCallAudit)).one()
            assert row.id
            assert {name: getattr(row, name) for name in values} == values
    finally:
        engine.dispose()
