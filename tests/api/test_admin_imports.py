"""结构化导入必须落为可编辑草稿，保留作者、来源与审核隔离。"""

import pytest
from sqlalchemy import func, select

from support.admin import KEY, decide, edit_body
from support.seeds import qid
from tutor_api.models import Question

PATH = "/admin/question-imports"


def import_body(reviewer):
    detail = reviewer.data("GET", f"/admin/questions/{qid(KEY)}")
    question = edit_body(detail)
    question.pop("expected_version")
    question.pop("expected_review_revision")
    return {
        "subject": detail["subject"],
        "answer_mode": detail["answer_mode"],
        "source": {
            k: detail["source"][k]
            for k in (
                "source_type",
                "source_category",
                "source_name",
                "source_year",
                "source_license",
                "source_url",
            )
        },
        "question": question,
    }


def test_import_is_private_draft_and_requires_independent_review(reviewer, admin, student):
    body = import_body(reviewer)
    data = reviewer.data("POST", PATH, json=body, expect=201)
    assert data["version"] == 1 and data["status"] == "draft"
    assert data["created_by"] == reviewer.user_id
    assert data["source"]["source_license"] == body["source"]["source_license"]
    assert all(not s["reviewed"] for s in data["solutions"])
    assert data["history"][0]["action"] == "import"
    student.error("GET", f"/questions/{data['id']}", expect=404)
    assert decide(reviewer, data["id"], "approve", expect=403)["code"] == "self_review_forbidden"
    decide(admin, data["id"], "approve")
    decide(admin, data["id"], "publish")
    student.data("GET", f"/questions/{data['id']}")


def test_import_retry_creates_only_one_question(reviewer, db):
    body = import_body(reviewer)
    before = db.scalar(select(func.count()).select_from(Question))
    first = reviewer.data("POST", PATH, json=body, expect=201, key="import-retry")
    second = reviewer.data("POST", PATH, json=body, expect=201, key="import-retry")
    assert first == second
    assert db.scalar(select(func.count()).select_from(Question)) == before + 1


def test_student_cannot_probe_import_validation(student):
    student.error("POST", PATH, json={"invalid": True}, expect=403)


@pytest.mark.parametrize("field", ["created_by", "status", "id"])
def test_import_cannot_set_server_fields(reviewer, field):
    body = import_body(reviewer)
    body[field] = "published"
    reviewer.error("POST", PATH, json=body, expect=422)


def test_invalid_knowledge_rolls_back_and_can_be_corrected(reviewer, db):
    body = import_body(reviewer)
    before = db.scalar(select(func.count()).select_from(Question))
    body["question"]["knowledge"] = ["missing.node"]
    reviewer.error("POST", PATH, json=body, expect=422)
    assert db.scalar(select(func.count()).select_from(Question)) == before


def test_content_problems_can_be_saved_but_not_approved(reviewer, admin):
    body = import_body(reviewer)
    body["question"]["solutions"] = []
    # This case removes solution content intentionally; remove its annotations
    # explicitly so dangling-reference validation does not mask review checks.
    body["question"]["teaching"] = dict(body["question"]["teaching"], reference_links=[])
    data = reviewer.data("POST", PATH, json=body, expect=201)
    assert data["check_problems"]
    assert decide(admin, data["id"], "approve", expect=422)["code"] == "content_checks_failed"


@pytest.mark.parametrize("license", ["", "   "])
def test_source_requires_nonblank_usage_basis(reviewer, license):
    body = import_body(reviewer)
    body["source"]["source_license"] = license
    reviewer.error("POST", PATH, json=body, expect=422)


def test_self_authored_question_cannot_claim_licensed_exam(reviewer):
    body = import_body(reviewer)
    body["source"]["source_category"] = "gaokao_real"
    reviewer.error("POST", PATH, json=body, expect=422)


def test_licensed_source_preserves_evidence_for_review(reviewer):
    body = import_body(reviewer)
    body["source"].update(
        source_type="public_license",
        source_name="授权练习",
        source_license="内部授权记录 DEMO-001",
        source_url="https://example.org/license",
    )
    data = reviewer.data("POST", PATH, json=body, expect=201)
    assert data["source"]["source_url"] == body["source"]["source_url"]
    assert data["status"] == "draft"


def test_downloadable_example_can_be_imported(reviewer):
    import json
    from pathlib import Path

    body = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    data = reviewer.data("POST", PATH, json=body, expect=201)
    assert data["check_problems"] == []


@pytest.mark.parametrize("mode", ["multiple_choice", "fill", "written", "experiment", "proof"])
def test_import_preserves_each_supported_question_mode(reviewer, db, mode):
    question = db.scalar(
        select(Question).where(Question.answer_mode == mode, Question.status == "published")
    )
    detail = reviewer.data("GET", f"/admin/questions/{question.id}")
    body = import_body(reviewer)
    body["subject"], body["answer_mode"] = detail["subject"], mode
    body["question"] = edit_body(detail)
    body["question"].pop("expected_version")
    body["question"].pop("expected_review_revision")
    data = reviewer.data("POST", PATH, json=body, expect=201)
    assert data["content"] == detail["content"]
    assert data["answer"] == detail["answer"]
    assert data["rubric"] == detail["rubric"]
    assert data["check_problems"] == []
