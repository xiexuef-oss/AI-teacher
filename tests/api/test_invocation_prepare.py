from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from ai_gateway.invocation_state import InvocationTransitions
from support.flows import begin, tutor
from tutor_api.errors import ApiError
from tutor_api.models import ModelBudgetUsage
from tutor_api.schemas import TutorActionIn
from tutor_api.services.invocation_dispatch import dispatch_rephrase
from tutor_api.services.invocation_prepare import prepare_rephrase
from tutor_api.services.invocation_store import InvocationStore, metadata


def test_http_key_finds_original_invocation_after_context_change(onboarded, app, db, clock):
    session, _ = begin(onboarded, "math-mono-quadratic")
    factory = app.state.session_factory
    metadata.create_all(factory.kw["bind"])
    store = InvocationStore(
        factory, InvocationTransitions(Path("contracts/model_invocation.schema.json"))
    )
    request = SimpleNamespace(
        headers={"Idempotency-Key": "stable-invocation-key"},
        method="POST",
        url=SimpleNamespace(path=f"/api/v1/tutor/sessions/{session['id']}/next"),
    )
    ctx = SimpleNamespace(
        db=db,
        actor_id=onboarded.user_id,
        student_id=onboarded.user_id,
        request=request,
        now=clock.now,
    )
    body = TutorActionIn(action="mark_confused")
    arguments = dict(pseudonym="stu_" + "b" * 32, secret="isolated-test-secret")
    original = prepare_rephrase(ctx, store, session["id"], body, **arguments)
    tutor(onboarded, session["id"], "request_hint")
    restored = prepare_rephrase(ctx, store, session["id"], body, **arguments)
    assert restored == original
    with pytest.raises(ApiError) as stale:
        dispatch_rephrase(
            ctx,
            store,
            original,
            session["id"],
            pseudonym=arguments["pseudonym"],
            estimated_cost_micros=3,
            request_cost_cap=3,
            student_limit=1,
            platform_limit=1,
        )
    assert stale.value.status_code == 409
    assert store.read(original["invocation_id"], original["actor_digest"])["state"] == "prepared"
    with factory() as check:
        assert list(check.scalars(select(ModelBudgetUsage))) == []
    with pytest.raises(ApiError) as rejected:
        prepare_rephrase(
            ctx,
            store,
            session["id"],
            TutorActionIn(action="mark_confused", confirm_end_independent=True),
            **arguments,
        )
    assert rejected.value.status_code == 409
    ctx.db.info["receipt_commit_allowed"] = False
    try:
        with pytest.raises(RuntimeError, match="before the formal receipt"):
            prepare_rephrase(ctx, store, session["id"], body, **arguments)
    finally:
        ctx.db.info.pop("receipt_commit_allowed")
    store.cancel(original["invocation_id"], original["actor_digest"], expected_fence=1)
    ctx.request.headers["Idempotency-Key"] = "fresh-context-dispatch-key"
    fresh = prepare_rephrase(ctx, store, session["id"], body, **arguments)
    options = dict(
        pseudonym=arguments["pseudonym"],
        estimated_cost_micros=3,
        request_cost_cap=3,
        student_limit=1,
        platform_limit=1,
    )
    sent = dispatch_rephrase(ctx, store, fresh, session["id"], **options)
    assert sent["state"] == "dispatch_unknown"
    with pytest.raises(ValueError):
        dispatch_rephrase(ctx, store, fresh, session["id"], **options)
    with factory() as check:
        rows = list(check.scalars(select(ModelBudgetUsage)))
        assert len(rows) == 2
        assert all(row.request_count == 1 and row.estimated_cost_micros == 3 for row in rows)
