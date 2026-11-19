from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from ai_gateway.audit import AuditRecord
from ai_gateway.invocation_state import InvocationTransitions
from support.flows import begin
from tutor_api.errors import ApiError
from tutor_api.idempotency import request_fingerprint, run_idempotent
from tutor_api.models import IdempotencyReceipt, TutorEventRow
from tutor_api.receipts import SqlReceiptStore
from tutor_api.schemas import TutorActionIn
from tutor_api.services.invocation_context import capture_context
from tutor_api.services.invocation_finalize import actor_binding, finalize_rephrase, session_binding
from tutor_api.services.invocation_store import InvocationStore, metadata


@pytest.mark.parametrize("formal", [False, True])
def test_rephrase_event_intent_and_receipt_share_transaction(onboarded, app, db, clock, formal):
    session, _ = begin(onboarded, "math-mono-quadratic")
    factory = app.state.session_factory
    metadata.create_all(factory.kw["bind"])
    pseudo = "stu_" + "b" * 32
    context = capture_context(db, onboarded.user_id, session["id"])
    db.commit()
    record = dict(
        schema_version=1,
        invocation_id="a" * 32,
        actor_digest=actor_binding(pseudo),
        budget_key=pseudo,
        session_digest=session_binding(pseudo, session["id"]),
        question_version=context.question_version,
        context_generation=context.event_sequence,
        context_digest=context.digest,
        fingerprint=request_fingerprint(
            SimpleNamespace(
                request=SimpleNamespace(
                    method="POST",
                    url=SimpleNamespace(path=f"/api/v1/tutor/sessions/{session['id']}/next"),
                )
            ),
            TutorActionIn(action="mark_confused"),
        ),
        quota_day="2026-11-17",
        fence=1,
        state="prepared",
        attempts=[],
    )
    store = InvocationStore(
        factory, InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    )
    store.prepare(record)
    store.dispatch(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=1,
        attempt_id="e" * 32,
        estimated_cost_micros=3,
        request_cost_cap=3,
        student_limit=10,
        platform_limit=10,
    )
    audit = AuditRecord(
        request_id="request",
        trace_id="trace",
        student_pseudonym=pseudo,
        task_type="tutor_explain",
        provider="mock",
        model_id="test",
        status="ok",
        error_code=None,
        provider_calls=1,
        latency_ms=1,
        input_tokens=None,
        output_tokens=None,
        image_units=None,
        estimated_cost_micros=3,
        schema_valid=True,
        review_required=False,
        created_at=datetime.now(UTC),
    )
    store.settle_metadata(
        record["invocation_id"],
        record["actor_digest"],
        expected_fence=1,
        attempt_id="e" * 32,
        audit=audit,
    )
    tc = SimpleNamespace(
        db=db,
        student_id=onboarded.user_id,
        pseudonym=pseudo,
        request_id="finalize-test",
        now=clock.now(),
    )
    output = dict(
        event_type="hint",
        payload=dict(
            level=1,
            total_levels=3,
            style="rephrase",
            text="先判断函数的类型，再考虑图像特征。",
            concept=None,
        ),
    )

    def apply():
        result = finalize_rephrase(
            tc,
            store,
            record["invocation_id"],
            session["id"],
            expected_fence=1,
            expected_fingerprint=record["fingerprint"],
            output=output,
            offered_catalog=[],
        )
        db.add(
            IdempotencyReceipt(
                id="f" * 32,
                actor_id=onboarded.user_id,
                key_digest="f" * 64,
                fingerprint="d" * 64,
                state="complete",
                status_code=200,
                response_json={"data": result.model_dump(mode="json")},
                created_at=clock.now(),
            )
        )
        db.flush()
        return result

    before = db.scalar(select(func.count()).select_from(TutorEventRow))
    db.commit()
    invalid = dict(output, payload=dict(output["payload"], text="<script>alert(1)</script>"))
    with pytest.raises(ApiError):
        finalize_rephrase(
            tc,
            store,
            record["invocation_id"],
            session["id"],
            expected_fence=1,
            expected_fingerprint="0" * 64,
            output=output,
            offered_catalog=[],
        )
    db.rollback()
    with pytest.raises(ApiError):
        finalize_rephrase(
            tc,
            store,
            record["invocation_id"],
            session["id"],
            expected_fence=1,
            expected_fingerprint=record["fingerprint"],
            output=invalid,
            offered_catalog=[],
        )
    db.rollback()
    assert (
        store.read(record["invocation_id"], record["actor_digest"])["state"] == "settled_metadata"
    )
    apply()
    db.rollback()
    assert (
        store.read(record["invocation_id"], record["actor_digest"])["state"] == "settled_metadata"
    )
    assert db.scalar(select(func.count()).select_from(TutorEventRow)) == before
    assert db.get(IdempotencyReceipt, "f" * 32) is None
    db.commit()
    if formal:
        ctx = SimpleNamespace(
            db=db,
            actor_id=onboarded.user_id,
            student_id=onboarded.user_id,
            now=clock.now,
            request=SimpleNamespace(
                headers={"Idempotency-Key": "finalize-formal-replay-key"},
                method="POST",
                url=SimpleNamespace(path=f"/api/v1/tutor/sessions/{session['id']}/next"),
                app=SimpleNamespace(state=SimpleNamespace(receipt_store=SqlReceiptStore())),
            ),
        )
        body = TutorActionIn(action="mark_confused")
        fail = True
        calls = 0

        def formal_action(digest):
            nonlocal calls
            calls += 1
            result = finalize_rephrase(
                tc,
                store,
                record["invocation_id"],
                session["id"],
                expected_fence=1,
                expected_fingerprint=record["fingerprint"],
                output=output,
                offered_catalog=[],
            )
            if fail:
                raise RuntimeError("failure after event before receipt")
            return result

        with pytest.raises(RuntimeError, match="failure after event"):
            run_idempotent(ctx, body, 200, formal_action)
        assert (
            store.read(record["invocation_id"], record["actor_digest"])["state"]
            == "settled_metadata"
        )
        assert db.scalar(select(func.count()).select_from(TutorEventRow)) == before
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 0
        db.commit()
        fail = False
        response = run_idempotent(ctx, body, 200, formal_action)
        replay = run_idempotent(ctx, body, 200, formal_action)
        assert response.body == replay.body
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert calls == 2
        assert db.scalar(select(func.count()).select_from(TutorEventRow)) == before + 1
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 1
        assert store.read(record["invocation_id"], record["actor_digest"])["state"] == "applied"
        return
    result = apply()
    db.commit()
    assert result.events[0]["meta"]["source"] == "model"
    assert store.read(record["invocation_id"], record["actor_digest"])["state"] == "applied"
    assert db.get(IdempotencyReceipt, "f" * 32) is not None
