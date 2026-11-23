from sqlalchemy import select

from tutor_api.models import AuditLog, ContentFactoryQuestionTypeKnowledge, KnowledgeNode


def test_editor_can_create_draft_with_linked_knowledge(admin, reviewer, new_reviewer, db):
    path = "/admin/content-factory/question-types"
    catalog = "/admin/content-factory/knowledge-nodes"
    query = {"subject": "math"}
    reviewer.error("GET", catalog, params=query, expect=403)
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": reviewer.user_id, "role": "editor", "enabled": True},
    )
    response = reviewer.request("GET", catalog, params=query)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    items = response.json()["data"]["items"]
    assert {item["id"] for item in items} == set(
        db.scalars(select(KnowledgeNode.id).where(KnowledgeNode.subject == "math"))
    )
    assert [item["code"] for item in items] == sorted(item["code"] for item in items)
    nodes = [item["id"] for item in items[:2]]
    body = {
        "code": "math.test.type",
        "title": "工程题型",
        "subject": "math",
        "specification": {"format": "fill"},
        "knowledge": [
            {"knowledge_id": nodes[0], "relation": "primary"},
            {"knowledge_id": nodes[1], "relation": "supporting"},
        ],
    }
    admin.error("POST", path, json=body, expect=403)
    receipt = reviewer.data("POST", path, json=body, key="cf-type-create", expect=201)
    assert receipt["status"] == "draft"
    assert reviewer.data("POST", path, json=body, key="cf-type-create", expect=201) == receipt
    reviewer.error("POST", path, json=body, expect=409)
    grants = db.scalars(
        select(ContentFactoryQuestionTypeKnowledge).where(
            ContentFactoryQuestionTypeKnowledge.question_type_id == receipt["id"],
        )
    )
    assert {row.knowledge_id for row in grants} == set(nodes)
    detail_path = f"{path}/{receipt['id']}"
    admin.error("GET", detail_path, expect=403)
    auditor = new_reviewer()
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": auditor.user_id, "role": "reviewer", "enabled": True},
    )
    detail = auditor.request("GET", detail_path)
    assert detail.status_code == 200
    assert detail.headers["Cache-Control"] == "no-store"
    result = detail.json()["data"]
    assert result["status"] == "draft"
    assert result["definition"]["specification"] == body["specification"]
    assert result["definition"]["knowledge"] == body["knowledge"]
    assert reviewer.data("GET", detail_path) == result
    auditor.error("GET", f"{path}/00000000-0000-0000-0000-000000000000", expect=404)
    approval = {"decision": "approve", "notes": "规格和知识关系已核对"}
    review_path = detail_path + "/review"
    reviewer.error("POST", review_path, json=approval, expect=403)
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": reviewer.user_id, "role": "reviewer", "enabled": True},
    )
    reviewer.error("POST", review_path, json=approval, expect=403)
    deprecation = {"decision": "deprecate", "notes": "停止使用本题型"}
    auditor.error("POST", review_path, json=deprecation, expect=409)
    approved = auditor.data("POST", review_path, json=approval, key="cf-type-approve")
    assert approved["status"] == "approved"
    assert auditor.data("POST", review_path, json=deprecation)["status"] == "deprecated"
    assert auditor.data("POST", review_path, json=approval, key="cf-type-approve") == approved
    assert auditor.data("GET", detail_path)["status"] == "deprecated"
    events = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.target_id == receipt["id"],
                AuditLog.action == "content_factory_question_type_reviewed",
            )
        )
    )
    assert len(events) == 2
    assert all(event.actor_id == auditor.user_id for event in events)
    assert {(event.detail_json["status"], event.detail_json["notes"]) for event in events} == {
        ("approved", approval["notes"]),
        ("deprecated", deprecation["notes"]),
    }
