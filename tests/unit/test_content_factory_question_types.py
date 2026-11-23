from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tutor_api.errors import ApiError
from tutor_api.models import ContentFactoryQuestionTypeKnowledge, KnowledgeNode
from tutor_api.services.content_factory_question_types import (
    QuestionTypeDraft,
    create_question_type,
)


def test_question_type_links_existing_nodes_and_rejects_cross_subject(db, reviewer, clock):
    ctx = SimpleNamespace(
        db=db, actor_id=reviewer.user_id, now=clock.now, request_id="cf-type-test"
    )
    math_nodes = list(db.scalars(select(KnowledgeNode.id).where(KnowledgeNode.subject == "math")))[
        :2
    ]
    physics_node = db.scalar(select(KnowledgeNode.id).where(KnowledgeNode.subject == "physics"))
    draft = {
        "code": "math.inequality.practice",
        "title": "不等式",
        "subject": "math",
        "province_code": "CN-51",
        "specification": {"format": "fill"},
        "knowledge": [
            {"knowledge_id": math_nodes[0], "relation": "primary"},
            {"knowledge_id": physics_node, "relation": "prerequisite"},
        ],
    }
    with pytest.raises(ApiError) as caught:
        create_question_type(ctx, QuestionTypeDraft.model_validate(draft))
    assert caught.value.status_code == 422
    draft["knowledge"][1]["knowledge_id"] = math_nodes[1]
    question_type = create_question_type(ctx, QuestionTypeDraft.model_validate(draft))
    assert question_type.status == "draft"
    db.flush()
    rows = list(db.scalars(select(ContentFactoryQuestionTypeKnowledge)))
    assert {(row.knowledge_id, row.relation) for row in rows} == {
        (math_nodes[0], "primary"),
        (math_nodes[1], "prerequisite"),
    }
