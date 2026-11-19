"""Dart 契约包由 contracts/ 生成（docs/05：客户端通过 OpenAPI 生成类型，禁止手写不一致请求对象）。

这里不需要 Dart 工具链：只检查生成结果覆盖了契约里的每个 schema 与操作，并且落盘文件没有过期。
生成代码能否通过 Dart 分析与测试，由 `dart analyze`、`dart test` 在 packages/contracts/dart 下验证。
"""

from __future__ import annotations

import re

import pytest
from gen_dart_contracts import OUTPUT_DIR, dart_identifier, enum_member, render

from support.contract import (
    iter_operations,
    load_event_schema,
    load_openapi,
    load_visual_registry,
    resolve,
)

MODELS = "lib/src/models.g.dart"
CLIENT = "lib/src/client.g.dart"
PAYLOADS = "lib/src/event_payloads.g.dart"
VISUALS = "lib/src/visual_templates.g.dart"
ROUND_TRIP = "test/round_trip.g.dart"


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    return render()


# ---------------------------------------------------------------- 命名


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("CN-51", "cn51"),
        ("G10", "g10"),
        ("math", "math"),
        ("single_choice", "singleChoice"),
        ("READY", "ready"),
        ("INDEPENDENT_ATTEMPT", "independentAttempt"),
        ("MODEL_UNAVAILABLE", "modelUnavailable"),
        ("image/jpeg", "imageJpeg"),
        ("new", "new$"),
        ("default", "default$"),
        ("in", "in$"),
        ("1st_place", "v1stPlace"),
    ],
)
def test_enum_member_names(value, expected):
    assert enum_member(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("user_id", "userId"),
        ("exam_year_from", "examYearFrom"),
        ("id", "id"),
        ("class", "class$"),
        ("is", "is$"),
        ("type", "type"),  # 契约里到处是 type 字段（题型、事件类型）；它在 Dart 里是合法标识符
        ("X-Request-Id", "xRequestId"),
    ],
)
def test_field_names(name, expected):
    assert dart_identifier(name) == expected


# ---------------------------------------------------------------- 覆盖


def test_multi_line_descriptions_stay_inside_their_doc_comment():
    """YAML 的多行描述（| 块）不能漏到注释外面：漏出去的那几行会让生成的 Dart 无法编译。"""
    from gen_dart_contracts import _render_class, _render_enum

    enum_text = _render_enum("Mode", {"description": "第一行\n第二行\n", "enum": ["a", "b"]})
    head = enum_text.split("enum Mode {")[0]
    assert head.strip() == "/// 第一行 第二行"

    class_text = _render_class(
        "Thing", {"description": "第一行\n第二行\n", "properties": {}}, resolver=None
    )
    assert class_text.split("class Thing {")[0].strip() == "/// 第一行 第二行"


def test_every_generated_doc_comment_is_a_single_line(generated):
    """生成的每一行中文说明都在 /// 注释里：契约里的多行描述压成一行，没有哪一行光秃秃地落在注释外。"""
    for relative in (MODELS, CLIENT, PAYLOADS):
        lines = generated[relative].splitlines()
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not re.search(r"[一-鿿]", stripped):
                continue
            in_comment = stripped.startswith("//")
            in_string = "'" in stripped or '"' in stripped
            assert in_comment or in_string, f"{relative}:{number} 有一行说明漏到了注释外面：{line}"


def test_expected_files_are_generated(generated):
    assert set(generated) == {MODELS, CLIENT, PAYLOADS, VISUALS, ROUND_TRIP}
    for path, content in generated.items():
        assert content.startswith("// GENERATED CODE - DO NOT MODIFY BY HAND"), path
        assert content.endswith("\n") and "\r" not in content, path
        assert "\t" not in content, path


def test_every_schema_becomes_a_dart_type(generated):
    models = generated[MODELS]
    for name, schema in load_openapi()["components"]["schemas"].items():
        if "enum" in schema:
            assert re.search(rf"^enum {name} \{{", models, re.M), name
        elif schema.get("type") == "object" and "properties" in schema:
            assert re.search(rf"^class {name} \{{", models, re.M), name
            assert f"factory {name}.fromJson(Map<String, dynamic> json)" in models, name


def test_every_property_becomes_a_field(generated):
    models = generated[MODELS]
    for name, schema in load_openapi()["components"]["schemas"].items():
        if schema.get("type") != "object" or "properties" not in schema:
            continue
        body = models.split(f"class {name} {{", 1)[1].split("\n}\n", 1)[0]
        for prop in schema["properties"]:
            assert re.search(rf"\b{re.escape(dart_identifier(prop))};", body), f"{name}.{prop}"
            assert f"json['{prop}']" in body, f"{name}.{prop} 没有按契约字段名解析"


def test_required_fields_are_non_nullable_and_optional_ones_nullable(generated):
    models = generated[MODELS]
    profile = models.split("class StudentProfile {", 1)[1].split("\n}\n", 1)[0]
    assert "final String userId;" in profile
    assert "final RegionCode? regionCode;" in profile, "required 但可为 null"
    assert "final List<Subject> subjects;" in profile
    assert "final DateTime updatedAt;" in profile

    update = models.split("class ProfileUpdate {", 1)[1].split("\n}\n", 1)[0]
    assert "final RegionCode regionCode;" in update
    assert "final int? examYear;" in update, "可选字段"
    assert "if (examYear != null) 'exam_year': examYear" in update, "可选字段为空时不发送"


def _class_body(models: str, name: str) -> str:
    return models.split(f"class {name} {{", 1)[1].split("\n}\n", 1)[0]


def test_fields_that_reference_an_enum_use_the_enum_type(generated):
    """曾经因为事件 Schema 里的同名枚举被跳过，OpenAPI 的 SessionState 字段被生成成了 String。"""
    models = generated[MODELS]
    assert "final SessionState state;" in _class_body(models, "StudySession")
    assert "final SessionState stateAfter;" in _class_body(models, "TutorEvent")
    assert "final TutorEventType type;" in _class_body(models, "TutorEvent")
    assert "final EvaluationState state;" in _class_body(models, "Evaluation")
    assert "final Subject subject;" in _class_body(models, "StudyTask")
    assert "final ReviewStatus status;" in _class_body(models, "ReviewItem")


def test_enums_tolerate_unknown_values(generated):
    """新增枚举值不能让旧客户端崩溃：未知值落到 $unknown。"""
    models = generated[MODELS]
    body = models.split("enum SessionState {", 1)[1].split("\n}\n", 1)[0]
    assert "independentAttempt('INDEPENDENT_ATTEMPT')" in body
    assert "$unknown('')" in body
    assert "orElse: () => SessionState.$unknown" in body


def test_every_operation_becomes_a_client_method(generated):
    client = generated[CLIENT]
    for _, _, op in iter_operations():
        assert re.search(rf"  Future<\w[\w<>, ?]*> {op['operationId']}\(", client), op[
            "operationId"
        ]


def _method(client: str, operation_id: str) -> str:
    start = re.search(rf"  Future<[^\n]*> {operation_id}\(", client)
    assert start, operation_id
    return client[start.start() :].split("\n  }\n", 1)[0]


def test_operations_that_need_an_idempotency_key_demand_one(generated):
    client = generated[CLIENT]
    for _, _, op in iter_operations():
        needs_key = any(
            p["name"] == "Idempotency-Key" and p.get("required")
            for p in map(resolve, op.get("parameters", []))
        )
        method = _method(client, op["operationId"])
        assert ("required String idempotencyKey" in method) == needs_key, op["operationId"]


def test_public_operations_do_not_send_the_token(generated):
    client = generated[CLIENT]
    for _, _, op in iter_operations():
        public = op.get("security") == []
        assert ("authenticated: false" in _method(client, op["operationId"])) == public, op[
            "operationId"
        ]


def test_client_uses_contract_paths_and_methods(generated):
    client = generated[CLIENT]
    assert "'POST', '/sessions'" in client
    assert "'PUT', '/attempts/${Uri.encodeComponent(attemptId)}/draft'" in client
    assert "'GET', '/reviews/due'" in client
    submit = _method(client, "submitAttempt")
    assert "Future<SubmitResult> submitAttempt(" in submit
    assert "required SubmitRequest body" in submit
    assert "SubmitResult.fromJson(" in submit


def test_query_parameters_are_typed(generated):
    listing = _method(generated[CLIENT], "listQuestions")
    for fragment in (
        "Subject? subject",
        "AnswerMode? answerMode",
        "QuestionScope? scope",
        "int? limit",
        "String? cursor",
    ):
        assert fragment in listing, fragment
    assert "'answer_mode': answerMode?.value" in listing
    assert "'limit': limit?.toString()" in listing


# ---------------------------------------------------------------- 教学事件与图解


def test_every_event_payload_has_a_typed_class_and_accessor(generated):
    payloads = generated[PAYLOADS]
    schema = load_event_schema()
    for rule in schema["allOf"]:
        event_type = rule["if"]["properties"]["type"]["const"]
        payload = rule["then"]["properties"]["payload"]["$ref"].rsplit("/", 1)[1]
        assert f"class {payload} {{" in payloads, payload
        assert re.search(rf"{payload} get \w+ => {payload}\.fromJson\(payload\);", payloads), (
            event_type
        )
    assert "extension TutorEventPayloads on TutorEvent" in payloads


def test_visual_payload_params_are_numbers(generated):
    body = generated[PAYLOADS].split("class VisualPayload {", 1)[1].split("\n}\n", 1)[0]
    assert "final Map<String, double> params;" in body


def test_visual_registry_is_embedded_for_the_client(generated):
    visuals = generated[VISUALS]
    for template_id, template in load_visual_registry()["templates"].items():
        assert f"'{template_id}': VisualTemplateSpec(" in visuals, template_id
        for param in template["params"]:
            assert f"name: '{param['name']}'" in visuals, (template_id, param["name"])


def test_round_trip_helpers_cover_every_class_and_event_type(generated):
    """Dart 侧的样例测试靠这张表把"真实响应 → 模型 → JSON"过一遍。"""
    helpers = generated[ROUND_TRIP]
    for name, schema in load_openapi()["components"]["schemas"].items():
        if schema.get("type") == "object" and "properties" in schema:
            assert f"'{name}': (json) => {name}.fromJson(json).toJson()," in helpers, name
    for event_type in load_event_schema()["$defs"]["EventType"]["enum"]:
        assert f"TutorEventType.{event_type} => event.{event_type}.toJson()," in helpers, event_type
    assert "TutorEventType.$unknown => null," in helpers


# ---------------------------------------------------------------- 落盘文件没有过期


def test_round_trip_normalization_metadata_is_schema_scoped(generated):
    from gen_dart_contracts import round_trip_metadata

    metadata = round_trip_metadata(load_openapi())
    assert set(metadata["Attempt"]["nullable"]) == {
        "submission_no",
        "copied_from_attempt_id",
        "copied_from_revision",
    }
    assert "independent" not in metadata["Attempt"]["nullable"]
    assert metadata["DraftCopy"]["objects"]["attempt"] == "Attempt"
    assert "roundTripMetadata" in generated[ROUND_TRIP]


def test_generated_files_on_disk_are_up_to_date(generated):
    """改了契约却没有重新生成时，这里会失败。运行 `uv run python tools/gen_dart_contracts.py` 更新。"""
    for relative, content in generated.items():
        path = OUTPUT_DIR / relative
        assert path.exists(), f"缺少 {relative}，请先运行生成器"
        assert path.read_text(encoding="utf-8") == content, f"{relative} 已过期，请重新运行生成器"
