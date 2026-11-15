"""由 contracts/ 生成 Dart 契约包（packages/contracts/dart）。

    uv run python tools/gen_dart_contracts.py           # 重新生成
    uv run python tools/gen_dart_contracts.py --check   # 只检查落盘文件是否过期

生成四个文件，全部在 packages/contracts/dart/lib/src/ 下：
- models.g.dart            openapi.yaml 的 components.schemas → 类与枚举
- client.g.dart            每个操作一个方法的 TutorApiClient
- event_payloads.g.dart    tutor_event.schema.json 的各类 payload 与按类型取用的扩展
- visual_templates.g.dart  packages/visual_templates/registry.json 的模板与参数边界

生成器只支持契约里实际用到的写法；遇到不认识的结构会直接报错，而不是悄悄生成错误的类型。
对象属性里不支持内联对象——请在 components.schemas 里起名字再引用。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi.yaml"
EVENT_SCHEMA_PATH = REPO_ROOT / "contracts" / "tutor_event.schema.json"
VISUAL_REGISTRY_PATH = REPO_ROOT / "packages" / "visual_templates" / "registry.json"
OUTPUT_DIR = REPO_ROOT / "packages" / "contracts" / "dart"

HEADER = (
    "// GENERATED CODE - DO NOT MODIFY BY HAND\n"
    "// 由 tools/gen_dart_contracts.py 根据 {source} 生成。要改动请改契约后重新生成。\n"
    "// dart format off\n"
    "// ignore_for_file: type=lint\n"
)

_RESERVED = {
    "abstract", "as", "assert", "async", "await", "base", "break", "case", "catch", "class", "const",
    "continue", "covariant", "default", "deferred", "do", "dynamic", "else", "enum", "export", "extends",
    "extension", "external", "factory", "false", "final", "finally", "for", "function", "get", "hide",
    "if", "implements", "import", "in", "interface", "is", "late", "library", "mixin", "new", "null",
    "of", "on", "operator", "part", "required", "rethrow", "return", "sealed", "set", "show", "static",
    "super", "switch", "sync", "this", "throw", "true", "try", "typedef", "var", "void", "when",
    "while", "with", "yield",
}  # fmt: skip
# 教学事件 Schema 里与 OpenAPI 同名但结构略有不同的定义，生成时换个名字
_EVENT_RENAMES = {"FeedbackItem": "DiagnosisFeedback", "KnowledgeRef": "EventKnowledgeRef"}
# 这些定义不生成类：基础别名，或 OpenAPI 里已有对应类型
_EVENT_SKIPPED = {"Text", "ShortText", "EventType", "SessionState", "EventMeta"}
_HTTP_METHODS = ("get", "put", "post", "delete", "patch")


# ---------------------------------------------------------------- 命名


def _camel(text: str) -> str:
    parts = [part for part in re.split(r"[^0-9A-Za-z]+", text) if part]
    if not parts:
        raise ValueError(f"无法从 {text!r} 得到标识符")
    name = parts[0].lower() + "".join(part[:1].upper() + part[1:].lower() for part in parts[1:])
    if name[0].isdigit():
        name = "v" + name
    return name + "$" if name in _RESERVED else name


def enum_member(value: str) -> str:
    """枚举值 → Dart 枚举成员名（CN-51 → cn51，INDEPENDENT_ATTEMPT → independentAttempt）。"""
    return _camel(value)


def dart_identifier(name: str) -> str:
    """契约字段名 → Dart 字段名（user_id → userId）。"""
    return _camel(name)


def _string(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\").replace("'", "\\'").replace("$", "\\$").replace("\n", "\\n")
    )
    return f"'{escaped}'"


def _number(value: float) -> str:
    return repr(float(value))


# ---------------------------------------------------------------- 类型解析


@dataclass(frozen=True)
class DartType:
    kind: str  # string / int / double / bool / datetime / enum / object / list / map / map_double / dynamic
    name: str = ""
    inner: DartType | None = None
    nullable: bool = False

    @property
    def base(self) -> str:
        match self.kind:
            case "string":
                return "String"
            case "int":
                return "int"
            case "double":
                return "double"
            case "bool":
                return "bool"
            case "datetime":
                return "DateTime"
            case "enum" | "object":
                return self.name
            case "list":
                assert self.inner is not None
                return f"List<{self.inner.base}>"
            case "map":
                return "Map<String, dynamic>"
            case "map_double":
                return "Map<String, double>"
            case _:
                return "dynamic"

    def declared(self, *, optional: bool) -> str:
        if self.kind == "dynamic":
            return "dynamic"
        return self.base + ("?" if self.nullable or optional else "")

    def decode(self, expr: str) -> str:
        match self.kind:
            case "string":
                return f"{expr} as String"
            case "int":
                return f"({expr} as num).toInt()"
            case "double":
                return f"({expr} as num).toDouble()"
            case "bool":
                return f"{expr} as bool"
            case "datetime":
                return f"DateTime.parse({expr} as String)"
            case "enum":
                return f"{self.name}.fromJson({expr} as String)"
            case "object":
                return f"{self.name}.fromJson({expr} as Map<String, dynamic>)"
            case "list":
                assert self.inner is not None
                return f"({expr} as List<dynamic>).map((e) => {self.inner.decode('e')}).toList()"
            case "map":
                return f"Map<String, dynamic>.from({expr} as Map)"
            case "map_double":
                return (
                    f"({expr} as Map).map((k, e) => MapEntry(k as String, (e as num).toDouble()))"
                )
            case _:
                return expr

    def encode(self, expr: str, access: str) -> str:
        """access 是 '.' 或 '?.'：字段可能为空时用后者。"""
        match self.kind:
            case "datetime":
                return f"{expr}{access}toUtc().toIso8601String()"
            case "enum" | "object":
                return f"{expr}{access}toJson()"
            case "list":
                assert self.inner is not None
                if self.inner.kind in {"datetime", "enum", "object", "list"}:
                    return f"{expr}{access}map((e) => {self.inner.encode('e', '.')}).toList()"
                return expr
            case _:
                return expr


class Resolver:
    """把 JSON Schema 片段解析成 Dart 类型。schemas 是可被 $ref 引用的定义表。"""

    def __init__(
        self,
        schemas: dict[str, Any],
        ref_prefix: str,
        renames: dict[str, str] | None = None,
        plain_enums: frozenset[str] = frozenset(),
    ) -> None:
        self.schemas = schemas
        self.ref_prefix = ref_prefix
        self.renames = renames or {}
        # 这些枚举不生成 Dart 枚举，保持为字符串（事件 Schema 里的 EventType、SessionState
        # 已由 OpenAPI 侧的同名枚举负责，payload 类用不到）
        self.plain_enums = plain_enums

    def resolve(self, schema: dict[str, Any], where: str) -> DartType:
        if "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith(self.ref_prefix):
                raise ValueError(f"{where}: 不支持的引用 {ref}")
            name = ref[len(self.ref_prefix) :]
            target = self.schemas[name]
            if "enum" in target and target.get("type") == "string" and name not in self.plain_enums:
                return DartType("enum", self.renames.get(name, name))
            if target.get("type") == "object" and "properties" in target:
                return DartType("object", self.renames.get(name, name))
            return self.resolve(target, f"{where} → {name}")

        if "oneOf" in schema:
            options = [option for option in schema["oneOf"] if option.get("type") != "null"]
            if len(options) != 1 or len(options) == len(schema["oneOf"]):
                raise ValueError(f"{where}: oneOf 只支持“某类型或 null”")
            resolved = self.resolve(options[0], where)
            return DartType(resolved.kind, resolved.name, resolved.inner, nullable=True)

        if "const" in schema:
            value = schema["const"]
            kind = (
                "bool" if isinstance(value, bool) else "string" if isinstance(value, str) else None
            )
            if kind is None:
                raise ValueError(f"{where}: 不支持的 const {value!r}")
            return DartType(kind)

        declared = schema.get("type")
        nullable = False
        if isinstance(declared, list):
            nullable = "null" in declared
            remaining = [t for t in declared if t != "null"]
            if len(remaining) != 1:
                raise ValueError(f"{where}: 不支持的联合类型 {declared}")
            declared = remaining[0]

        if declared == "string":
            kind = "datetime" if schema.get("format") == "date-time" else "string"
            return DartType(kind, nullable=nullable)
        if declared == "integer":
            return DartType("int", nullable=nullable)
        if declared == "number":
            return DartType("double", nullable=nullable)
        if declared == "boolean":
            return DartType("bool", nullable=nullable)
        if declared == "array":
            inner = self.resolve(schema.get("items", {}), f"{where}[]")
            return DartType("list", inner=inner, nullable=nullable)
        if declared == "object":
            if "properties" in schema:
                raise ValueError(f"{where}: 不支持内联对象，请在 schemas 里命名后引用")
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict) and extra.get("type") == "number":
                return DartType("map_double", nullable=nullable)
            return DartType("map", nullable=nullable)
        if declared is None:
            return DartType("dynamic")
        raise ValueError(f"{where}: 不支持的类型 {declared!r}")


# ---------------------------------------------------------------- 模型


def _render_enum(name: str, schema: dict[str, Any]) -> str:
    # 契约里的描述可以写成多行（YAML 的 | 块）：压成一行，否则后面的行会漏到注释外面
    lines = [
        f"/// {' '.join(schema['description'].split())}" for _ in [0] if schema.get("description")
    ]
    lines.append(f"enum {name} {{")
    members = [enum_member(value) for value in schema["enum"]]
    if len(set(members)) != len(members):
        raise ValueError(f"{name}: 枚举值生成的成员名有重复")
    for member, value in zip(members, schema["enum"], strict=True):
        lines.append(f"  {member}({_string(value)}),")
    lines += [
        "",
        "  /// 契约里新增、而这个版本的客户端还不认识的值。",
        "  $unknown('');",
        "",
        f"  const {name}(this.value);",
        "  final String value;",
        "",
        f"  static {name} fromJson(String value) =>",
        f"      values.firstWhere((e) => e.value == value, orElse: () => {name}.$unknown);",
        "",
        "  String toJson() => value;",
        "}",
    ]
    return "\n".join(lines)


def _render_class(name: str, schema: dict[str, Any], resolver: Resolver) -> str:
    required = set(schema.get("required", []))
    fields = []
    for prop, prop_schema in schema["properties"].items():
        dart_type = resolver.resolve(prop_schema, f"{name}.{prop}")
        fields.append((prop, dart_identifier(prop), dart_type, prop not in required))

    lines = []
    if schema.get("description"):
        lines.append(f"/// {' '.join(schema['description'].split())}")
    lines.append(f"class {name} {{")
    if fields:
        lines.append(f"  const {name}({{")
        for _, field, dart_type, optional in fields:
            needs_value = not optional and not dart_type.nullable and dart_type.kind != "dynamic"
            lines.append(f"    {'required ' if needs_value else ''}this.{field},")
        lines.append("  });")
    else:
        lines.append(f"  const {name}();")
    lines.append("")
    for _, field, dart_type, optional in fields:
        lines.append(f"  final {dart_type.declared(optional=optional)} {field};")
    lines.append("")

    lines.append(f"  factory {name}.fromJson(Map<String, dynamic> json) => {name}(")
    for prop, field, dart_type, optional in fields:
        source = f"json[{_string(prop)}]"
        decoded = dart_type.decode(source)
        if dart_type.kind == "dynamic":
            lines.append(f"        {field}: {source},")
        elif optional or dart_type.nullable:
            lines.append(f"        {field}: {source} == null ? null : {decoded},")
        else:
            lines.append(f"        {field}: {decoded},")
    lines.append("      );")
    lines.append("")

    lines.append("  Map<String, dynamic> toJson() => {")
    for prop, field, dart_type, optional in fields:
        maybe_null = optional or dart_type.nullable
        encoded = dart_type.encode(field, "?." if maybe_null else ".")
        if optional:
            # 可选字段为空时不发送（例如 exam_year 省略表示沿用手动值或按年级估算）
            lines.append(f"        if ({field} != null) {_string(prop)}: {encoded},")
        else:
            lines.append(f"        {_string(prop)}: {encoded},")
    lines.append("      };")
    lines.append("}")
    return "\n".join(lines)


def render_models(openapi: dict[str, Any]) -> str:
    schemas = openapi["components"]["schemas"]
    resolver = Resolver(schemas, "#/components/schemas/")
    blocks = []
    for name, schema in schemas.items():
        if "enum" in schema:
            blocks.append(_render_enum(name, schema))
        elif schema.get("type") == "object" and "properties" in schema:
            blocks.append(_render_class(name, schema, resolver))
    return HEADER.format(source="contracts/openapi.yaml") + "\n" + "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------- 客户端


def _local_ref(openapi: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = openapi
        for part in node["$ref"][2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


def _render_operation(
    openapi: dict[str, Any], path: str, method: str, op: dict[str, Any], resolver: Resolver
) -> str:
    operation_id = op["operationId"]
    parameters = [_local_ref(openapi, p) for p in op.get("parameters", [])]
    path_params = [p for p in parameters if p["in"] == "path"]
    query_params = [p for p in parameters if p["in"] == "query"]
    needs_key = any(
        p["in"] == "header" and p["name"] == "Idempotency-Key" and p.get("required")
        for p in parameters
    )
    public = op.get("security") == []

    success = next(code for code in sorted(op["responses"]) if code.startswith("2"))
    response = _local_ref(openapi, op["responses"][success])
    data_schema = response["content"]["application/json"]["schema"]["properties"]["data"]
    result = resolver.resolve(data_schema, f"{operation_id} 的响应")
    if result.kind != "object":
        raise ValueError(f"{operation_id}: 响应 data 必须引用一个具名对象")

    signature = [f"required String {dart_identifier(p['name'])}" for p in path_params]
    body_type = None
    if "requestBody" in op:
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        body_type = resolver.resolve(body_schema, f"{operation_id} 的请求体")
        signature.append(f"required {body_type.base} body")
    if needs_key:
        signature.append("required String idempotencyKey")
    query_entries = []
    for param in query_params:
        dart_type = resolver.resolve(param["schema"], f"{operation_id}.{param['name']}")
        field = dart_identifier(param["name"])
        signature.append(f"{dart_type.base}? {field}")
        if dart_type.kind == "enum":
            value = f"{field}?.value"
        elif dart_type.kind == "string":
            value = field
        else:
            value = f"{field}?.toString()"
        query_entries.append(f"{_string(param['name'])}: {value}")
    signature.append("String? requestId")

    dart_path = re.sub(
        r"\{([^}]+)\}",
        lambda m: "${Uri.encodeComponent(" + dart_identifier(m.group(1)) + ")}",
        path,
    )
    lines = [f"  /// {' '.join(op.get('summary', operation_id).split())}"]
    if op.get("x-implementation-status") == "planned":
        lines.append("  ///")
        lines.append("  /// 契约已规划、服务端尚未实现：调用会得到 501 `not_implemented`。")
    lines.append(f"  Future<{result.base}> {operation_id}({{")
    lines += [f"    {param}," for param in signature]
    lines.append("  }) async {")
    lines.append("    final data = await _core.send(")
    lines.append(f"      '{method.upper()}', '{dart_path}',")
    if query_entries:
        lines.append("      query: {" + ", ".join(query_entries) + "},")
    if body_type is not None:
        lines.append("      body: body.toJson(),")
    if needs_key:
        lines.append("      idempotencyKey: idempotencyKey,")
    lines.append("      requestId: requestId,")
    if public:
        lines.append("      authenticated: false,")
    lines.append("    );")
    lines.append(f"    return {result.base}.fromJson(data as Map<String, dynamic>);")
    lines.append("  }")
    return "\n".join(lines)


def render_client(openapi: dict[str, Any]) -> str:
    resolver = Resolver(openapi["components"]["schemas"], "#/components/schemas/")
    methods = [
        _render_operation(openapi, path, method, item[method], resolver)
        for path, item in openapi["paths"].items()
        for method in _HTTP_METHODS
        if method in item
    ]
    version = openapi["info"]["version"]
    return (
        HEADER.format(source="contracts/openapi.yaml")
        + "\n"
        + "import 'models.g.dart';\n"
        + "import 'runtime.dart';\n\n"
        + f"/// 生成时的契约版本。\nconst String contractVersion = {_string(version)};\n\n"
        + "/// 每个契约操作一个方法。请求与响应对象都是由契约生成的类型。\n"
        + "class TutorApiClient {\n"
        + "  TutorApiClient(this._core);\n\n"
        + "  final ApiCore _core;\n\n"
        + "\n\n".join(methods)
        + "\n}\n"
    )


# ---------------------------------------------------------------- 教学事件 payload


def render_event_payloads(event_schema: dict[str, Any]) -> str:
    defs = event_schema["$defs"]
    resolver = Resolver(defs, "#/$defs/", _EVENT_RENAMES, plain_enums=frozenset(_EVENT_SKIPPED))
    blocks = []
    for name, schema in defs.items():
        if name in _EVENT_SKIPPED:
            continue
        if schema.get("type") != "object" or "properties" not in schema:
            raise ValueError(f"$defs/{name}: 只支持对象定义")
        blocks.append(_render_class(_EVENT_RENAMES.get(name, name), schema, resolver))

    accessors = []
    for rule in event_schema["allOf"]:
        event_type = rule["if"]["properties"]["type"]["const"]
        payload = rule["then"]["properties"]["payload"]["$ref"].rsplit("/", 1)[1]
        accessors.append(f"  /// `type == {event_type}` 时的 payload。")
        accessors.append(
            f"  {payload} get {dart_identifier(event_type)} => {payload}.fromJson(payload);"
        )
    extension = (
        "/// 按事件类型把 payload 解析成对应的类型。调用前先看 `type`。\n"
        "extension TutorEventPayloads on TutorEvent {\n" + "\n".join(accessors) + "\n}"
    )
    return (
        HEADER.format(source="contracts/tutor_event.schema.json")
        + "\n"
        + "import 'models.g.dart';\n\n"
        + "\n\n".join([*blocks, extension])
        + "\n"
    )


# ---------------------------------------------------------------- 图解模板


def render_visual_templates(registry: dict[str, Any]) -> str:
    entries = []
    for template_id, template in registry["templates"].items():
        params = []
        for param in template["params"]:
            params.append(
                "      VisualParamSpec("
                f"name: {_string(param['name'])}, label: {_string(param['label'])}, "
                f"min: {_number(param['min'])}, max: {_number(param['max'])}, step: {_number(param['step'])}, "
                f"defaultValue: {_number(param['default'])}, "
                f"integer: {'true' if param['integer'] else 'false'}, "
                f"adjustable: {'true' if param['adjustable'] else 'false'}),"
            )
        entries.append(
            f"  {_string(template_id)}: VisualTemplateSpec(\n"
            f"    id: {_string(template_id)},\n"
            f"    title: {_string(template['title'])},\n"
            f"    summary: {_string(template['summary'])},\n"
            f"    staticFallback: {_string(template['static_fallback'])},\n"
            "    params: [\n" + "\n".join(params) + "\n    ],\n"
            "  ),"
        )
    body = """
/// 图解模板的一个数值参数及其边界。
class VisualParamSpec {
  const VisualParamSpec({
    required this.name,
    required this.label,
    required this.min,
    required this.max,
    required this.step,
    required this.defaultValue,
    required this.integer,
    required this.adjustable,
  });

  final String name;
  final String label;
  final double min;
  final double max;
  final double step;
  final double defaultValue;
  final bool integer;
  final bool adjustable;

  /// 把任意输入收进边界；不是有限数时退回默认值。
  double clamp(double? value) {
    if (value == null || value.isNaN || value.isInfinite) return defaultValue;
    final bounded = value < min ? min : (value > max ? max : value);
    return integer ? bounded.roundToDouble() : bounded;
  }
}

/// 一个注册过的图解模板。渲染器只认这里列出的模板和参数。
class VisualTemplateSpec {
  const VisualTemplateSpec({
    required this.id,
    required this.title,
    required this.summary,
    required this.staticFallback,
    required this.params,
  });

  final String id;
  final String title;
  final String summary;
  final String staticFallback;
  final List<VisualParamSpec> params;

  /// 按注册顺序补齐参数：没给的用默认值，越界的收进边界，不认识的丢弃。
  Map<String, double> normalize(Map<String, double> input) => {
        for (final param in params) param.name: param.clamp(input[param.name]),
      };
}

/// 图解模板白名单（docs/06 §6）。不在表里的 template_id 一律显示静态说明。
const Map<String, VisualTemplateSpec> visualTemplates = {
__ENTRIES__
};
""".replace("__ENTRIES__", "\n".join(entries))
    return HEADER.format(source="packages/visual_templates/registry.json") + body


# ---------------------------------------------------------------- 测试辅助


def render_round_trip(openapi: dict[str, Any], event_schema: dict[str, Any]) -> str:
    """Dart 测试用的表：schema 名 → "解析后再序列化"的函数；事件类型 → payload 的往返。"""
    classes = [
        name
        for name, schema in openapi["components"]["schemas"].items()
        if schema.get("type") == "object" and "properties" in schema
    ]
    entries = [f"  {_string(name)}: (json) => {name}.fromJson(json).toJson()," for name in classes]
    cases = [
        f"      TutorEventType.{enum_member(event_type)} => event.{dart_identifier(event_type)}.toJson(),"
        for event_type in event_schema["$defs"]["EventType"]["enum"]
    ]
    return (
        HEADER.format(source="contracts/openapi.yaml 与 contracts/tutor_event.schema.json")
        + "\n"
        + "import 'package:tutor_contracts/tutor_contracts.dart';\n\n"
        + "typedef RoundTrip = Map<String, dynamic> Function(Map<String, dynamic> json);\n\n"
        + "/// schema 名 → 把一段 JSON 解析成对应类型再序列化回来。\n"
        + "final Map<String, RoundTrip> roundTrips = {\n"
        + "\n".join(entries)
        + "\n};\n\n"
        + "/// 按事件类型把 payload 过一遍对应的类型；不认识的类型返回 null。\n"
        + "Map<String, dynamic>? payloadRoundTrip(TutorEvent event) => switch (event.type) {\n"
        + "\n".join(cases)
        + "\n      TutorEventType.$unknown => null,\n"
        + "    };\n"
    )


# ---------------------------------------------------------------- 入口


def render() -> dict[str, str]:
    """返回 {相对 packages/contracts/dart 的路径: 文件内容}。"""
    openapi = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    event_schema = json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = json.loads(VISUAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {
        "lib/src/models.g.dart": render_models(openapi),
        "lib/src/client.g.dart": render_client(openapi),
        "lib/src/event_payloads.g.dart": render_event_payloads(event_schema),
        "lib/src/visual_templates.g.dart": render_visual_templates(registry),
        "test/round_trip.g.dart": render_round_trip(openapi, event_schema),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="由契约生成 Dart 包")
    parser.add_argument(
        "--check", action="store_true", help="只检查落盘文件是否与契约一致，不写文件"
    )
    args = parser.parse_args(argv)

    stale = []
    for relative, content in render().items():
        path = OUTPUT_DIR / relative
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        stale.append(relative)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if args.check and stale:
        print(
            "以下生成文件已过期，请运行 uv run python tools/gen_dart_contracts.py：",
            file=sys.stderr,
        )
        for relative in stale:
            print(f"  {relative}", file=sys.stderr)
        return 1
    print("生成文件已是最新" if not stale else f"已更新 {len(stale)} 个文件：" + ", ".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
