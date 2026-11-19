"""Self-authored metadata for cost incident tests; no real provider requests."""

from datetime import UTC, datetime

from ai_gateway.audit import AuditRecord


def record(key="a"):
    return dict(
        schema_version=1,
        invocation_id=key * 32,
        actor_digest="b" * 64,
        budget_key="stu_" + "b" * 32,
        session_digest=key * 64,
        question_version=1,
        context_generation=0,
        fingerprint="d" * 64,
        context_digest="e" * 64,
        quota_day="2026-11-17",
        fence=1,
        state="prepared",
        attempts=[],
    )


def audit(cost=5):
    return AuditRecord(
        request_id="self-authored",
        trace_id="f" * 32,
        student_pseudonym="stu_" + "b" * 32,
        task_type="tutor_explain",
        provider="fake",
        model_id="fake",
        status="ok",
        error_code=None,
        provider_calls=1,
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
        image_units=None,
        estimated_cost_micros=cost,
        schema_valid=True,
        review_required=True,
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
