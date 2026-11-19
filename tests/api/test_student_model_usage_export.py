import json
from datetime import date

from sqlalchemy import select

from tutor_api.db import new_id
from tutor_api.gateway_io import pseudonym
from tutor_api.models import ModelBudgetUsage, ModelCallAudit

PATH = "/profile/learning-export"


def seed(db, app, student_id, *, scope="student", secret=None):
    key = pseudonym(secret or app.state.pseudonym_secret, student_id)
    now = app.state.clock()
    db.add(
        ModelBudgetUsage(
            id=new_id(),
            scope=scope,
            scope_key=key,
            usage_date=date(2026, 11, 17),
            request_count=3,
            estimated_cost_micros=12,
            updated_at=now,
        )
    )
    db.add(
        ModelCallAudit(
            id=new_id(),
            request_id="PRIVATE_REQUEST",
            trace_id="PRIVATE_TRACE",
            student_pseudonym=key,
            task_type="tutor_hint",
            provider="private-provider",
            model_id="private-model",
            status="fallback",
            error_code="private-error",
            provider_calls=0,
            latency_ms=9,
            input_tokens=None,
            output_tokens=None,
            image_units=None,
            estimated_cost_micros=None,
            schema_valid=None,
            review_required=False,
            created_at=now,
        )
    )
    db.commit()
    return key


def test_model_usage_owned_whitelisted_readonly(student, new_student, parent, app, db):
    own = seed(db, app, student.user_id)
    other = seed(db, app, new_student().user_id)
    seed(db, app, student.user_id, secret="old-key")
    db.add(
        ModelBudgetUsage(
            id=new_id(),
            scope="platform",
            scope_key=own,
            usage_date=date(2026, 11, 17),
            request_count=999,
            estimated_cost_micros=999,
            updated_at=app.state.clock(),
        )
    )
    db.commit()
    before = [
        (r.id, r.request_count, r.estimated_cost_micros)
        for r in db.scalars(select(ModelBudgetUsage))
    ]
    usage = student.data("GET", PATH)["model_usage"]
    assert usage["history_complete"] is False
    assert usage["costs_are_billing"] is False
    assert usage["identity_scope"] == "current_server_pseudonym"
    assert len(usage["calls"]) == len(usage["budget_days"]) == 1
    assert usage["calls"][0]["input_tokens"] is None
    assert usage["calls"][0]["estimated_cost_micros"] is None
    assert usage["budget_days"][0]["request_count"] == 3
    raw = json.dumps(usage)
    for private in (own, other, "PRIVATE", "private-", "scope_key", "999"):
        assert private not in raw
    assert parent.get(PATH).status_code == 403
    db.expire_all()
    assert before == [
        (r.id, r.request_count, r.estimated_cost_micros)
        for r in db.scalars(select(ModelBudgetUsage))
    ]


def test_empty_model_usage_is_explicit(student):
    usage = student.data("GET", PATH)["model_usage"]
    assert usage["calls"] == usage["budget_days"] == []
    assert usage["history_complete"] is False


def test_rotated_secret_does_not_claim_old_history(student, app, db):
    old = seed(db, app, student.user_id)
    app.state.pseudonym_secret = "replacement-test-secret"
    usage = student.data("GET", PATH)["model_usage"]
    assert usage["calls"] == usage["budget_days"] == []
    assert usage["history_complete"] is False
    assert db.scalar(select(ModelCallAudit.student_pseudonym)) == old


def test_model_usage_budget_and_call_costs_are_distinct(student, app, db):
    seed(db, app, student.user_id)
    call = db.scalar(select(ModelCallAudit))
    call.input_tokens = 23
    call.output_tokens = 7
    call.provider_calls = 1
    call.estimated_cost_micros = 5
    db.commit()
    usage = student.data("GET", PATH)["model_usage"]
    assert usage["calls"][0]["estimated_cost_micros"] == 5
    assert usage["budget_days"][0]["estimated_cost_micros"] == 12
    assert usage["calls"][0]["input_tokens"] == 23
    assert usage["calls"][0]["output_tokens"] == 7
    assert usage["costs_are_billing"] is False


def test_model_usage_counts_towards_shared_limit(student, app, db, monkeypatch):
    from tutor_api.services import student_learning_export

    seed(db, app, student.user_id)
    monkeypatch.setattr(student_learning_export, "MAX_RECORDS", 1)
    assert student.get(PATH).status_code == 413
