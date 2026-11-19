import uuid
from collections import Counter

import pytest
from sqlalchemy import select

from support.flows import begin, blank, solve, tutor
from tutor_api.models import KnowledgeNode, Question, QuestionKnowledge, QuestionVersion


def test_private_only_topic_is_not_listed_or_counted(onboarded, db, clock):
    question_id, node_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(
        Question(
            id=question_id,
            subject="math",
            type="single_choice",
            answer_mode="single_choice",
            status="draft",
            version=1,
            difficulty=2,
            source_type="self_authored",
            source_category="foundation",
            source_license="engineering-only",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
    )
    db.add(
        KnowledgeNode(
            id=node_id,
            subject="math",
            code="PRIVATE_TOPIC",
            title="PRIVATE_TOPIC",
            created_at=clock.now(),
        )
    )
    db.flush()
    original = db.scalar(select(QuestionVersion))
    db.add(
        QuestionVersion(
            id=str(uuid.uuid4()),
            question_id=question_id,
            version=1,
            content_json={**original.content_json, "title": "PRIVATE_TOPIC"},
            answer_json={},
            teaching_json={},
            created_at=clock.now(),
        )
    )
    db.add(QuestionKnowledge(question_id=question_id, knowledge_id=node_id))
    db.commit()
    topics = onboarded.data("GET", "/questions/topics")["items"]
    assert node_id not in {topic["id"] for topic in topics}
    assert onboarded.data("GET", "/questions", params={"knowledge_id": node_id})["items"] == []


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"subject": "math"},
        {"subject": "physics", "answer_mode": "experiment"},
        {"scope": "general"},
        {"scope": "region"},
    ],
)
def test_topics_match_only_deliverable_questions_and_filter_them(onboarded, filters):
    page = onboarded.data("GET", "/questions", params={**filters, "limit": 50})
    assert page["next_cursor"] is None
    counts = Counter(node["id"] for question in page["items"] for node in question["knowledge"])
    topics = onboarded.data("GET", "/questions/topics", params=filters)["items"]
    assert {node["id"]: node["question_count"] for node in topics} == counts
    for topic in topics:
        questions = onboarded.data(
            "GET", "/questions", params={**filters, "knowledge_id": topic["id"], "limit": 50}
        )["items"]
        assert {q["id"] for q in questions} == {
            q["id"] for q in page["items"] if topic["id"] in {node["id"] for node in q["knowledge"]}
        }
    assert (
        onboarded.data("GET", "/questions", params={"knowledge_id": str(uuid.uuid4())})["items"]
        == []
    )


def test_roles_and_invalid_topic_filter(student, parent, reviewer):
    for actor in (parent, reviewer):
        assert actor.get("/questions/topics").status_code == 403
    assert student.get("/questions", params={"knowledge_id": "not-a-uuid"}).status_code == 422


def test_cold_start_uses_only_own_learning_history(onboarded, new_student):
    assert onboarded.data("GET", "/tasks/today")["cold_start"]
    begin(onboarded, "math-mono-quadratic")  # Opening a question is not a finished attempt.
    assert onboarded.data("GET", "/tasks/today")["cold_start"]
    other = new_student()
    other.save_profile(json={"region_code": "CN-51", "subjects": ["math"]})
    solve(other, "math-ineq-min", blank("4"))
    assert onboarded.data("GET", "/tasks/today")["cold_start"]
    assert not other.data("GET", "/tasks/today")["cold_start"]
    session, _ = begin(onboarded, "math-ineq-min")
    tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)
    assert not onboarded.data("GET", "/tasks/today")["cold_start"]
