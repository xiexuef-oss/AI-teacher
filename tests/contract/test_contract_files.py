"""契约文件自身的规则（CON-001）。不依赖任何服务实现。"""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from support import CONTRACTS_DIR, REPO_ROOT
from support.contract import (
    iter_operations,
    load_event_schema,
    load_openapi,
    load_visual_registry,
    operations_by_id,
    resolve,
    validate_event,
)

IMPLEMENTED = {
    "requestLearningPackPhotoOcr",
    "getLearningPackPhotoOcr",
    "getScanUploadContent",
    "resolveLearningPackPage",
    "getParentWeeklySnapshot",
    "getPaperReviewSchedule",
    "correctLearningPackReturn",
    "getLearningPackReturn",
    "listLearningPacks",
    "listLearningPackItems",
    "abandonLearningPack",
    "downloadLearningPackSolutionPdf",
    "submitLearningPackReturn",
    "downloadLearningPackStudentPdf",
    "resolveLearningPackItem",
    "createLearningPack",
    "getLearningJob",
    "cancelLearningJob",
    "getDiagnosticWorkspace",
    "listDiagnosticHistory",
    "createDiagnostic",
    "getDiagnostic",
    "openDiagnosticSession",
    "abandonDiagnostic",
    "getPublishedQuestionMedia",
    "confirmQuestionMediaReview",
    "createMediaUpload",
    "uploadMediaContent",
    "confirmMediaUpload",
    "getMediaContent",
    "deleteMedia",
    "getQuestionMediaContent",
    "reviewQuestionBatch",
    "getHealth",
    "getLaunchConfig",
    "createLocalIdentity",
    "getProfile",
    "getStudentLearningExport",
    "getStudentMediaExport",
    "updateProfile",
    "getTodayTasks",
    "listQuestions",
    "listQuestionTopics",
    "getQuestion",
    "createSession",
    "getSession",
    "listSessionEvents",
    "createAttempt",
    "getAttempt",
    "getDraft",
    "syncDraft",
    "submitAttempt",
    "tutorNext",
    "listDueReviews",
    "completeReview",
    "getReviewState",
    "getProgressSummary",
    # P0 第 9 条：最小审核流
    "listAdminQuestions",
    "getAdminQuestion",
    "reviewQuestion",
    "createQuestionVersion",
    "importQuestionDraft",
    "getQuestionVersion",
    # P0 第 3、4 条：解答题（主观题）提交后的对照自查
    "getSelfCheck",
    "saveSelfCheck",
    # P0 第 8 条：家长周报与学生明确授权的绑定
    "createParentInvite",
    "listParentLinks",
    "revokeParentLink",
    "redeemParentInvite",
    "listParentStudents",
    "getParentWeekly",
}
DOCUMENT_IMPORT_OPERATIONS = {
    "getDocumentImportOptions",
    "listDocumentImportJobs",
    "createDocumentImportJob",
    "getDocumentImportJob",
    "uploadDocumentImportFile",
    "getDocumentImportContent",
    "getDocumentImportPreview",
    "processDocumentImportJob",
    "cancelDocumentImportJob",
    "editDocumentImportCandidates",
    "submitDocumentImportCandidates",
}
DOCUMENT_IMPORT_IMPLEMENTED = {
    "reviewQuestionBatch",
    "submitDocumentImportCandidates",
    "editDocumentImportCandidates",
    "getDocumentImportPreview",
    "getDocumentImportOptions",
    "listDocumentImportJobs",
    "createDocumentImportJob",
    "getDocumentImportJob",
    "uploadDocumentImportFile",
    "getDocumentImportContent",
    "processDocumentImportJob",
    "cancelDocumentImportJob",
}
IMPLEMENTED |= DOCUMENT_IMPORT_IMPLEMENTED
IMPLEMENTED |= {"createScanUpload", "uploadScanContent", "createScan", "getScan", "confirmScan"}
IMPLEMENTED |= {"createSchoolMaterialUpload", "uploadSchoolMaterialContent", "submitSchoolMaterial"}
IMPLEMENTED |= {"listSchoolMaterialPages", "correctSchoolMaterialPage"}
IMPLEMENTED.add("listSchoolMaterialCandidates")
IMPLEMENTED.add("confirmSchoolMaterialCandidates")
IMPLEMENTED.add("getSchoolMaterialPagePreview")
IMPLEMENTED |= {"createDraftCopy", "listQuestionDrafts", "getSessionQuestion"}
PLANNED = DOCUMENT_IMPORT_OPERATIONS - DOCUMENT_IMPORT_IMPLEMENTED
# docs/05：提交、评分触发、草稿同步、教学下一步等非幂等动作必须带 Idempotency-Key
MUST_REQUIRE_IDEMPOTENCY_KEY = {
    "requestLearningPackPhotoOcr",
    "correctLearningPackReturn",
    "abandonLearningPack",
    "submitLearningPackReturn",
    "createLearningPack",
    "cancelLearningJob",
    "createDiagnostic",
    "openDiagnosticSession",
    "abandonDiagnostic",
    "createDraftCopy",
    "createScanUpload",
    "uploadScanContent",
    "createSchoolMaterialUpload",
    "submitSchoolMaterial",
    "correctSchoolMaterialPage",
    "confirmSchoolMaterialCandidates",
    "uploadSchoolMaterialContent",
    "confirmQuestionMediaReview",
    "uploadMediaContent",
    "confirmMediaUpload",
    "deleteMedia",
    "reviewQuestionBatch",
    "createDocumentImportJob",
    "uploadDocumentImportFile",
    "processDocumentImportJob",
    "cancelDocumentImportJob",
    "editDocumentImportCandidates",
    "submitDocumentImportCandidates",
    "createSession",
    "createAttempt",
    "syncDraft",
    "submitAttempt",
    "tutorNext",
    "completeReview",
    "createMediaUpload",
    "createScan",
    "confirmScan",
    "reviewQuestion",
    "createQuestionVersion",
    "importQuestionDraft",
    "saveSelfCheck",
    "createParentInvite",
    "redeemParentInvite",
    "revokeParentLink",
}
PUBLIC_OPERATIONS = {"getHealth", "getLaunchConfig", "createLocalIdentity"}
DOC06_TEMPLATES = {
    "quadratic_graph",
    "rectangle_area",
    "number_line",
    "force_diagram",
    "motion_chart",
    "chemical_flow",
    "chemical_process",
    "triangle_schematic",
    "circle_schematic",
}


def _parameters(op: dict) -> list[dict]:
    return [resolve(p) for p in op.get("parameters", [])]


# ---------------------------------------------------------------- 重复的键


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML 默认让后出现的键悄悄覆盖先出现的；契约里这只可能是笔误（同名 schema 写了两遍），所以直接报错。"""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"重复的键 {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    assert not duplicated, f"JSON 里有重复的键：{duplicated}"
    return dict(pairs)


def test_duplicate_key_detector_really_detects():
    with pytest.raises(yaml.YAMLError, match="重复的键 'a'"):
        yaml.load("x:\n  a: 1\n  a: 2\n", Loader=_UniqueKeyLoader)
    with pytest.raises(AssertionError, match="重复的键"):
        json.loads('{"a": 1, "a": 2}', object_pairs_hook=_no_duplicate_pairs)


def test_contract_files_have_no_duplicate_keys():
    openapi = (CONTRACTS_DIR / "openapi.yaml").read_text(encoding="utf-8")
    yaml.load(openapi, Loader=_UniqueKeyLoader)
    for path in (
        CONTRACTS_DIR / "tutor_event.schema.json",
        REPO_ROOT / "packages" / "visual_templates" / "registry.json",
    ):
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_pairs)


# ---------------------------------------------------------------- OpenAPI


def test_openapi_is_valid_31():
    spec = load_openapi()
    assert spec["openapi"].startswith("3.1")
    validate(copy.deepcopy(spec))


def test_api_is_served_under_versioned_prefix():
    assert load_openapi()["servers"] == [{"url": "/api/v1"}]


def test_operation_ids_are_unique():
    ids = [op["operationId"] for _, _, op in iter_operations()]
    assert len(ids) == len(set(ids))


def test_slice_and_planned_operations_are_exactly_as_agreed():
    status = {
        op["operationId"]: op.get("x-implementation-status") for _, _, op in iter_operations()
    }
    assert {k for k, v in status.items() if v == "implemented"} == IMPLEMENTED
    assert {k for k, v in status.items() if v == "planned"} == PLANNED
    assert set(status) == IMPLEMENTED | PLANNED


def test_planned_operations_declare_501():
    for op_id in PLANNED:
        _, _, op = operations_by_id()[op_id]
        assert "501" in op["responses"], op_id


def test_non_idempotent_operations_require_idempotency_key():
    for op_id in MUST_REQUIRE_IDEMPOTENCY_KEY:
        _, _, op = operations_by_id()[op_id]
        headers = [
            p for p in _parameters(op) if p["in"] == "header" and p["name"] == "Idempotency-Key"
        ]
        assert headers and headers[0].get("required") is True, (
            f"{op_id} 必须声明必填的 Idempotency-Key"
        )


def test_every_post_except_identity_requires_idempotency_key():
    for _, method, op in iter_operations():
        if method == "post" and op["operationId"] != "createLocalIdentity":
            assert op["operationId"] in MUST_REQUIRE_IDEMPOTENCY_KEY, op["operationId"]


def test_only_public_operations_skip_authentication():
    assert load_openapi()["security"] == [{"bearerAuth": []}]
    for _, _, op in iter_operations():
        is_public = op.get("security") == []
        assert is_public == (op["operationId"] in PUBLIC_OPERATIONS), op["operationId"]
        if not is_public:
            assert "401" in op["responses"], f"{op['operationId']} 需要声明 401"


def test_success_bodies_use_data_envelope():
    for _, _, op in iter_operations():
        success = [code for code in op["responses"] if code.startswith("2")]
        assert success, f"{op['operationId']} 没有 2xx 响应"
        for code in success:
            schema = resolve(op["responses"][code])["content"]["application/json"]["schema"]
            assert schema["type"] == "object", op["operationId"]
            assert schema["required"] == ["data"], op["operationId"]
            assert set(schema["properties"]) == {"data"}, op["operationId"]


def test_error_bodies_use_error_envelope():
    for _, _, op in iter_operations():
        for code, response in op["responses"].items():
            if code.startswith("2"):
                continue
            schema = resolve(response)["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorEnvelope"}, (
                op["operationId"],
                code,
            )
    error = load_openapi()["components"]["schemas"]["ErrorBody"]
    assert set(error["required"]) == {"code", "message", "details", "request_id"}


def test_every_response_echoes_request_id():
    for _, _, op in iter_operations():
        for code, response in op["responses"].items():
            headers = resolve(response).get("headers", {})
            assert "X-Request-Id" in headers, (op["operationId"], code)


def test_question_schemas_cannot_carry_answers():
    """题目接口不得带出答案、解法、提示原文或选项分析（docs/03 P04 验收）。"""
    schemas = load_openapi()["components"]["schemas"]
    forbidden = {
        "answer",
        "answer_json",
        "solutions",
        "hints",
        "option_analysis",
        "rubric",
        "points",  # 解答题的自查要点
        "steps",  # 证明题的参考证明（解法的步骤也叫这个名字）
        "reference_steps",
        "reference_cells",
    }
    for name in (
        "Question",
        "QuestionSummary",
        "QuestionContent",
        "QuestionOption",
        "QuestionBlank",
        "Subquestion",
    ):
        assert not forbidden & set(schemas[name]["properties"]), name


def _reachable_schemas(name: str) -> set[str]:
    """从一个 schema 出发，沿 $ref 能走到的所有 schema 名（含自己）。"""
    schemas = load_openapi()["components"]["schemas"]
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)

        def walk(node) -> None:
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    pending.append(ref.rsplit("/", 1)[1])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schemas[current])
    return seen


def test_question_payloads_cannot_reach_the_self_check_points():
    """自查要点（采分点）只能在提交之后通过自查接口拿到，题目与作答前的任何接口都走不到它。"""
    for name in ("Question", "QuestionSummary", "QuestionPage", "StudyTask", "TodayTasks"):
        reachable = _reachable_schemas(name)
        assert not {"SelfCheck", "SelfCheckPoint"} & reachable, name


def _property_names(name: str) -> set[str]:
    """从一个 schema 出发，沿 $ref 能走到的所有 schema 里出现过的字段名。"""
    schemas = load_openapi()["components"]["schemas"]
    return {
        field
        for reachable in _reachable_schemas(name)
        for field in schemas[reachable].get("properties", {})
    }


def test_question_payloads_cannot_reach_the_reference_data_of_an_experiment():
    """实验题数据表里留空格子的参考值（reference_cells）只能在提交之后通过自查接口拿到。"""
    for name in ("Question", "QuestionSummary", "QuestionPage", "StudyTask", "TodayTasks"):
        reachable = _reachable_schemas(name)
        assert "reference_cells" not in _property_names(name), name
        assert "SelfCheck" not in reachable and "AnswerCell" not in reachable, name


def test_question_payloads_cannot_reach_the_reference_proof():
    """证明题的参考证明（reference_steps）只能在提交之后通过自查接口拿到：题目与作答前的任何接口都走不到它。"""
    for name in ("Question", "QuestionSummary", "QuestionPage", "StudyTask", "TodayTasks"):
        reachable = _reachable_schemas(name)
        assert "reference_steps" not in _property_names(name), name
        assert not {"SelfCheck", "ProofReferenceStep"} & reachable, name


def test_questions_never_carry_a_field_called_value():
    """题目接口里不允许出现名为 value 的键：答案类的字段（空位的答案、格子里的数）都叫这个名字。
    所以题目给定的数据表格子叫 text，留空的格子 text 为 null。"""
    for name in (
        "Question",
        "QuestionContent",
        "DataTable",
        "DataTableRow",
        "DataTableCell",
        "ProofStatement",
    ):
        assert "value" not in _property_names(name), name
    cell = load_openapi()["components"]["schemas"]["DataTableCell"]
    assert set(cell["properties"]) == {"col", "text"} and cell["required"] == ["col", "text"]
    assert cell["properties"]["text"]["type"] == ["string", "null"]


def test_experiment_questions_carry_tables_and_safety_notes():
    schemas = load_openapi()["components"]["schemas"]
    content = schemas["QuestionContent"]
    assert {"data_tables", "safety"} <= set(content["required"])
    assert content["properties"]["data_tables"]["maxItems"] <= 5
    safety = schemas["ExperimentSafety"]
    assert safety["required"] == ["level", "notes"]
    assert schemas["ExperimentSafetyLevel"]["enum"] == ["low", "medium", "high"]
    assert safety["properties"]["notes"]["minItems"] >= 1
    # 表、行、列的键只用字母、数字、下划线：格子的键是"表键.行键.列键"，不能含点
    for name in ("DataTable", "DataTableRow", "DataTableColumn"):
        assert schemas[name]["properties"]["key"]["pattern"] == "^[A-Za-z0-9_]+$", name


def test_experiment_answers_use_cells_for_the_blank_table_cells():
    schemas = load_openapi()["components"]["schemas"]
    payload = schemas["AnswerPayload"]["properties"]
    assert payload["cells"]["items"] == {"$ref": "#/components/schemas/AnswerCell"}
    assert payload["cells"]["maxItems"] <= 200
    cell = schemas["AnswerCell"]
    assert cell["required"] == ["table", "row", "col", "value"]
    assert cell["properties"]["value"]["maxLength"] <= 40
    assert all(cell["properties"][name]["maxLength"] <= 16 for name in ("table", "row", "col"))


def test_proof_questions_carry_givens_and_a_claim_but_no_proof():
    schemas = load_openapi()["components"]["schemas"]
    content = schemas["QuestionContent"]
    assert "proof" in content["required"]
    assert content["properties"]["proof"]["oneOf"] == [
        {"$ref": "#/components/schemas/ProofStatement"},
        {"type": "null"},
    ]
    statement = schemas["ProofStatement"]
    assert statement["required"] == ["givens", "claim"] and not statement["additionalProperties"]
    assert set(statement["properties"]) == {"givens", "claim"}
    assert statement["properties"]["givens"]["maxItems"] <= 8
    assert statement["properties"]["claim"]["minLength"] >= 1
    assert "proof" in schemas["AnswerMode"]["enum"] and "proof" in schemas["QuestionType"]["enum"]


def test_proof_answers_use_steps_with_a_reason_for_each():
    schemas = load_openapi()["components"]["schemas"]
    payload = schemas["AnswerPayload"]["properties"]
    assert payload["steps"]["items"] == {"$ref": "#/components/schemas/AnswerStep"}
    assert payload["steps"]["maxItems"] <= 30
    step = schemas["AnswerStep"]
    assert step["required"] == ["text", "reason"] and not step["additionalProperties"]
    assert step["properties"]["text"]["maxLength"] <= 1000
    assert step["properties"]["reason"]["maxLength"] <= 400


def test_the_self_check_carries_the_reference_proof_with_four_stages_and_no_score():
    schemas = load_openapi()["components"]["schemas"]
    check = schemas["SelfCheck"]
    assert "reference_steps" in check["required"]
    assert check["properties"]["reference_steps"]["items"] == {
        "$ref": "#/components/schemas/ProofReferenceStep"
    }
    assert schemas["ProofStage"]["enum"] == ["premise", "construction", "reasoning", "conclusion"]
    step = schemas["ProofReferenceStep"]
    assert step["required"] == ["stage", "text", "reason"] and not step["additionalProperties"]
    assert step["properties"]["stage"] == {"$ref": "#/components/schemas/ProofStage"}
    assert not {"score", "points_earned", "weight"} & set(step["properties"])


def test_the_self_check_carries_reference_cells_but_no_score():
    schemas = load_openapi()["components"]["schemas"]
    check = schemas["SelfCheck"]
    assert "reference_cells" in check["required"]
    assert check["properties"]["reference_cells"]["items"] == {
        "$ref": "#/components/schemas/AnswerCell"
    }
    assert not {"score", "points_earned", "weight"} & set(check["properties"])


def test_written_answers_use_parts_keyed_by_subquestion():
    schemas = load_openapi()["components"]["schemas"]
    payload = schemas["AnswerPayload"]["properties"]
    assert payload["parts"]["items"] == {"$ref": "#/components/schemas/AnswerPart"}
    assert payload["parts"]["maxItems"] <= 20
    part = schemas["AnswerPart"]
    assert part["required"] == ["key", "text"]
    assert part["properties"]["key"]["maxLength"] <= 16
    assert part["properties"]["text"]["maxLength"] <= 4000


def test_self_check_has_three_levels_and_no_numeric_score():
    """自查只有"完成 / 部分 / 没做到"三档，不出现分数；它也不是官方阅卷。"""
    schemas = load_openapi()["components"]["schemas"]
    assert schemas["SelfCheckLevel"]["enum"] == ["done", "partial", "missed"]
    for name in ("SelfCheck", "SelfCheckMark", "SelfCheckPoint", "SelfCheckSummary"):
        assert not {"score", "points_earned", "weight"} & set(schemas[name]["properties"]), name
    assert "disclaimer" in schemas["SelfCheck"]["required"]


def test_progress_reports_subjective_work_apart_from_accuracy():
    schemas = load_openapi()["components"]["schemas"]
    assert "subjective" in schemas["ProgressSummary"]["required"]
    subjective = schemas["SubjectiveProgress"]
    assert not {"rate", "accuracy", "score"} & set(subjective["properties"])


PARENT_VIEW_SCHEMAS = ("ParentWeekly", "ParentStudent", "ParentStudents", "PreviousWeek")


def test_what_a_parent_can_see_never_reaches_questions_answers_or_drafts():
    """家长只看汇总（PRD §3、US-06）：周报与学生列表沿 $ref 走不到题目、作答、草稿笔迹和教学事件。"""
    forbidden = {
        "Question",
        "QuestionOut",
        "QuestionSummary",
        "QuestionContent",
        "Attempt",
        "AnswerPayload",
        "AnswerPart",
        "AnswerStep",
        "ProofStatement",
        "ProofReferenceStep",
        "Draft",
        "DraftSync",
        "Stroke",
        "StrokeDoc",
        "StrokePage",
        "TutorEvent",
        "TutorEventPayload",
        "SelfCheck",
        "SelfCheckPoint",
        "StudySession",
        "ReviewItem",
    }
    for name in PARENT_VIEW_SCHEMAS:
        assert not forbidden & _reachable_schemas(name), name


def test_the_weekly_report_has_no_per_interaction_ranking_or_streak_fields():
    properties = set(load_openapi()["components"]["schemas"]["ParentWeekly"]["properties"])
    banned = {
        "question_id",
        "question_ids",
        "title",
        "answer",
        "answers",
        "strokes",
        "draft",
        "hints",
        "submitted_at",
        "events",
        "rank",
        "ranking",
        "percentile",
        "streak",
        "consecutive_days",
        "score",
    }
    assert not banned & properties
    # 比例和计数分开，比例样本不足时是 null（RateStat 已经这样约定）
    assert {"independent", "assisted", "hint_dependency", "retest_success"} <= properties


def test_the_invite_code_is_only_in_the_create_response():
    """邀请码只在创建时出现一次：授权列表、待用邀请、家长看到的学生里都没有 code 字段。"""
    schemas = load_openapi()["components"]["schemas"]
    assert "code" in schemas["ParentInvite"]["properties"]
    for name in (
        "ParentLink",
        "ParentLinks",
        "PendingParentInvite",
        "ParentStudent",
        "ParentStudents",
    ):
        assert "code" not in schemas[name]["properties"], name


def test_a_parent_is_a_local_mock_role_and_revocation_is_part_of_the_contract():
    schemas = load_openapi()["components"]["schemas"]
    assert "parent" in schemas["LocalRole"]["enum"]
    assert "revoked_at" in schemas["ParentLink"]["required"]
    _, _, weekly = operations_by_id()["getParentWeekly"]
    assert "501" not in weekly["responses"]
    assert {"401", "403", "404", "422"} <= set(weekly["responses"])


def test_response_schemas_are_closed_objects():
    """对象 schema 一律 additionalProperties: false，服务端多发字段会被契约测试抓到。"""
    for name, schema in load_openapi()["components"]["schemas"].items():
        if schema.get("type") == "object" and "properties" in schema:
            assert schema.get("additionalProperties") is False, name


# ------------------------------------------------------------ 教学事件 Schema


def _event(event_type: str, payload: dict, **overrides) -> dict:
    event = {
        "id": "7d0f3a52-6f0c-4a55-9d3e-1b2a3c4d5e6f",
        "session_id": "0b9c7c0e-1f66-4f0a-8a55-9d3e1b2a3c4d",
        "seq_no": 1,
        "type": event_type,
        "created_at": "2026-11-10T08:00:00Z",
        "state_after": "HINTED",
        "payload": payload,
        "meta": {
            "schema_version": "1.0",
            "source": "reviewed_content",
            "degraded": False,
            "provider": None,
            "model_id": None,
            "prompt_version": None,
            "question_id": "3f2b1c0a-9e8d-4c7b-a6f5-0e1d2c3b4a59",
            "question_version": 1,
            "trace_id": None,
            "request_id": "req-test",
        },
    }
    event.update(overrides)
    return event


VALID_PAYLOADS = {
    "diagnosis": {
        "outcome": "incorrect",
        "summary": "选项 B 不成立。",
        "feedback": [{"target": "B", "code": "wrong_option", "message": "忽略了定义域。"}],
        "knowledge": [],
        "suggestions": [
            {
                "action": "request_hint",
                "label": "给点提示",
                "question_id": None,
                "knowledge_id": None,
            }
        ],
    },
    "hint": {
        "level": 1,
        "total_levels": 3,
        "style": "layered",
        "text": "先看对称轴。",
        "concept": "单调性",
    },
    "standard": {
        "title": "常规解法",
        "steps": [{"text": "配方得 $y=(x-1)^2-4$。"}],
        "final_answer": "B",
        "option_analysis": [{"key": "A", "verdict": "wrong", "text": "区间方向反了。"}],
        "key_points": ["对称轴"],
    },
    "fast": {
        "title": "快速解法",
        "conditions": ["a>0 的二次函数"],
        "steps": [{"text": "对称轴右侧递增。"}],
        "final_answer": "B",
        "boundary": "a<0 时结论相反。",
        "reviewed": True,
    },
    "visual": {
        "template_id": "quadratic_graph",
        "params": {"a": 1, "b": -2, "c": -3},
        "caption": "拖动 a 观察开口方向。",
        "static_fallback": "开口向上，对称轴 x=1。",
    },
    "ask": {
        "prompt": "要不要试一道变式题？",
        "suggestions": [
            {
                "action": "start_variant",
                "label": "做变式",
                "question_id": "3f2b1c0a-9e8d-4c7b-a6f5-0e1d2c3b4a59",
                "knowledge_id": None,
            }
        ],
    },
    "notice": {
        "code": "review_scheduled",
        "text": "已安排复测。",
        "due_at": "2026-11-11T08:00:00Z",
    },
    "uncertainty": {
        "reason_code": "equivalence_unconfirmed",
        "text": "暂时无法确认这个答案是否等价。",
        "review_required": True,
    },
    "fallback": {
        "reason_code": "MODEL_UNAVAILABLE",
        "text": "讲解服务暂时不可用，可以先看审核解析。",
        "suggestions": [],
    },
}


def test_tutor_event_schema_is_valid_2020_12():
    schema = load_event_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_event_types_cover_docs05_and_docs06():
    types = set(load_event_schema()["$defs"]["EventType"]["enum"])
    assert types == set(VALID_PAYLOADS)
    assert {"hint", "standard", "fast", "visual", "ask"} <= types  # docs/05
    assert {"uncertainty", "fallback"} <= types  # docs/06


@pytest.mark.parametrize("event_type", sorted(VALID_PAYLOADS))
def test_valid_event_passes(event_type):
    validate_event(_event(event_type, VALID_PAYLOADS[event_type]))


def test_subjective_questions_use_a_dedicated_uncertainty_reason():
    """解答题不自动评分：用专门的原因码说明"没有判定、请自查"，而不是冒充格式认不出或等价未确认。"""
    payload = _mutated(
        "uncertainty",
        reason_code="subjective_self_check",
        text="解答题不自动评分，请对照要点自己检查。",
    )
    validate_event(_event("uncertainty", payload, state_after="DIAGNOSED"))


def _mutated(event_type: str, **changes) -> dict:
    payload = copy.deepcopy(VALID_PAYLOADS[event_type])
    for key, value in changes.items():
        if value is ...:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


INVALID_EVENTS = {
    "未知事件类型": _event("celebrate", {}),
    "payload 与类型不匹配": _event("hint", VALID_PAYLOADS["visual"]),
    "payload 带多余字段": _event("hint", _mutated("hint", script="alert(1)")),
    "提示层级小于 1": _event("hint", _mutated("hint", level=0)),
    "图解缺模板": _event("visual", _mutated("visual", template_id=...)),
    "图解用未注册模板": _event("visual", _mutated("visual", template_id="free_canvas")),
    "图解参数不是数值": _event("visual", _mutated("visual", params={"a": "1; drop table"})),
    "图解没有静态后备": _event("visual", _mutated("visual", static_fallback=...)),
    "快速解法没有适用条件": _event("fast", _mutated("fast", conditions=[])),
    "快速解法未审核": _event("fast", _mutated("fast", reviewed=False)),
    "不确定事件却不要求复核": _event("uncertainty", _mutated("uncertainty", review_required=False)),
    "不确定事件的原因码未知": _event(
        "uncertainty", _mutated("uncertainty", reason_code="graded_by_vibes")
    ),
    "缺元数据": {k: v for k, v in _event("hint", VALID_PAYLOADS["hint"]).items() if k != "meta"},
    "信封带多余字段": _event("hint", VALID_PAYLOADS["hint"], html="<b>x</b>"),
    "未知会话状态": _event("hint", VALID_PAYLOADS["hint"], state_after="CHEATING"),
    "序号从 0 开始": _event("hint", VALID_PAYLOADS["hint"], seq_no=0),
}


@pytest.mark.parametrize("label", sorted(INVALID_EVENTS))
def test_invalid_event_is_rejected(label):
    with pytest.raises(AssertionError):
        validate_event(INVALID_EVENTS[label])


def test_event_meta_is_traceable():
    """docs/06 §5：模型版本、提示版本、题库版本写入事件元数据。"""
    meta = load_event_schema()["$defs"]["EventMeta"]
    assert {"provider", "model_id", "prompt_version", "question_id", "question_version"} <= set(
        meta["required"]
    )


def test_openapi_event_envelope_matches_schema_file():
    """OpenAPI 里的事件信封与 Schema 文件必须一致，避免两处各改各的。"""
    schemas = load_openapi()["components"]["schemas"]
    event_schema = load_event_schema()
    envelope = schemas["TutorEvent"]
    assert set(envelope["required"]) == set(event_schema["required"])
    assert set(envelope["properties"]) == set(event_schema["properties"])
    assert schemas["TutorEventType"]["enum"] == event_schema["$defs"]["EventType"]["enum"]
    assert schemas["SessionState"]["enum"] == event_schema["$defs"]["SessionState"]["enum"]
    meta = schemas["TutorEventMeta"]
    assert set(meta["required"]) == set(event_schema["$defs"]["EventMeta"]["required"])
    assert set(meta["properties"]) == set(event_schema["$defs"]["EventMeta"]["properties"])


def test_session_states_follow_docs06_state_machine():
    assert load_event_schema()["$defs"]["SessionState"]["enum"] == [
        "READY",
        "INDEPENDENT_ATTEMPT",
        "SUBMITTED",
        "DIAGNOSED",
        "HINTED",
        "STANDARD",
        "FAST",
        "VISUAL",
        "VARIANT",
        "REVIEW_SCHEDULED",
        "DONE",
        "FALLBACK",
    ]


# ------------------------------------------------------------ 图解模板注册表


def test_visual_registry_matches_doc06():
    registry = load_visual_registry()
    assert set(registry["templates"]) == DOC06_TEMPLATES
    schema_ids = load_event_schema()["$defs"]["VisualPayload"]["properties"]["template_id"]["enum"]
    assert set(schema_ids) == DOC06_TEMPLATES


def test_visual_params_have_finite_bounds():
    for template_id, template in load_visual_registry()["templates"].items():
        assert template["static_fallback"].strip(), template_id
        names = [p["name"] for p in template["params"]]
        assert names and len(names) == len(set(names)), template_id
        for param in template["params"]:
            lo, hi, default = param["min"], param["max"], param["default"]
            for value in (lo, hi, default, param["step"]):
                assert isinstance(value, (int, float)) and not isinstance(value, bool)
                assert abs(value) < 1e6, (template_id, param["name"])
            assert lo < hi and lo <= default <= hi, (template_id, param["name"])
            assert param["step"] > 0, (template_id, param["name"])
