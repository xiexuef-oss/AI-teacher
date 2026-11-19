"""模型输出校验。

三道关：结构（JSON Schema）→ 图解白名单与参数边界 → 内容（标记与泄题）。任何一道不过，
输出都不会离开网关。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ai_gateway.dto import Constraints, ContentSpanRef, TaskType
from ai_gateway.errors import OutputRejected
from ai_gateway.visual_templates import VisualRegistry, VisualTemplateError

# 只拦可执行或可外链的标记。数学文本里常见的 "x<a 且 b>0" 不能被误伤，所以不按通用标签匹配。
_MARKUP = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|svg|img|link|style|form|meta|base|video|audio)\b"
    r"|javascript\s*:",
    re.IGNORECASE,
)


def contains_blocked_markup(text: str) -> bool:
    """文本里是否带有可执行或可外链的标记。审核内容入库前和模型输出下发前共用这一条规则。"""
    return _MARKUP.search(text) is not None


def _event_output(event_type: str, payload_def: str, event_schema_id: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["event_type", "payload"],
        "properties": {
            "event_type": {"const": event_type},
            "payload": {"$ref": f"{event_schema_id}#/$defs/{payload_def}"},
            "references": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"$ref": f"{event_schema_id}#/$defs/ContentSpanRef"},
            },
        },
    }


def _task_schemas(event_schema_id: str) -> dict[TaskType, dict[str, Any]]:
    """各任务类别的输出结构。教学类直接复用教学事件 Schema 的 payload 定义；
    其余类别是本阶段尚未被业务使用的暂定结构。"""
    step = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 4000}},
    }
    return {
        TaskType.TUTOR_HINT: _event_output("hint", "HintPayload", event_schema_id),
        TaskType.TUTOR_EXPLAIN: _event_output("hint", "HintPayload", event_schema_id),
        TaskType.VISUAL_SPEC: _event_output("visual", "VisualPayload", event_schema_id),
        TaskType.OCR_EXTRACT: {
            "type": "object",
            "additionalProperties": False,
            "required": ["stem_text", "expressions"],
            "properties": {
                "stem_text": {"type": "string", "maxLength": 4000},
                "expressions": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["span_id", "latex", "confidence"],
                        "properties": {
                            "span_id": {"type": "string", "minLength": 1, "maxLength": 64},
                            "latex": {"type": "string", "maxLength": 1000},
                            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                        },
                    },
                },
            },
        },
        TaskType.HANDWRITING_UNDERSTAND: {
            "type": "object",
            "additionalProperties": False,
            "required": ["steps"],
            "properties": {
                "steps": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["span_id", "text"],
                        "properties": {
                            "span_id": {"type": ["string", "null"], "maxLength": 64},
                            "text": {"type": "string", "maxLength": 2000},
                        },
                    },
                }
            },
        },
        TaskType.KNOWLEDGE_CLASSIFY: {
            "type": "object",
            "additionalProperties": False,
            "required": ["knowledge_codes"],
            "properties": {
                "knowledge_codes": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 1, "maxLength": 64},
                }
            },
        },
        TaskType.COMPLEX_REASONING: {
            "type": "object",
            "additionalProperties": False,
            "required": ["steps", "final_answer"],
            "properties": {
                "steps": {"type": "array", "maxItems": 40, "items": step},
                "final_answer": {"type": ["string", "null"], "maxLength": 4000},
            },
        },
        TaskType.SOLUTION_VERIFY: {
            "type": "object",
            "additionalProperties": False,
            "required": ["verdict", "notes"],
            "properties": {
                "verdict": {"type": "string", "enum": ["consistent", "inconsistent", "uncertain"]},
                "notes": {"type": "string", "maxLength": 4000},
            },
        },
        TaskType.REVIEW_PLAN: {
            "type": "object",
            "additionalProperties": False,
            "required": ["intervals_days", "rationale"],
            "properties": {
                "intervals_days": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"type": "integer", "minimum": 1, "maximum": 365},
                },
                "rationale": {"type": "string", "maxLength": 2000},
            },
        },
    }


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _fold(text: str) -> str:
    """比较泄题表述时忽略全半角、大小写与空白。"""
    return "".join(unicodedata.normalize("NFKC", text).lower().split())


class OutputValidator:
    def __init__(self, event_schema: dict[str, Any], visual_registry: VisualRegistry) -> None:
        schema_id = event_schema["$id"]
        resource = Resource.from_contents(event_schema, default_specification=DRAFT202012)
        registry = Registry().with_resource(uri=schema_id, resource=resource)
        self._validators = {
            task: Draft202012Validator(schema, registry=registry)
            for task, schema in _task_schemas(schema_id).items()
        }
        self._visual_registry = visual_registry

    def validate(
        self, task_type: TaskType, output: Any, constraints: Constraints
    ) -> dict[str, Any]:
        """返回可下发的输出（图解参数已按注册表补齐）；不合格抛 OutputRejected。"""
        if not isinstance(output, dict):
            raise OutputRejected("SCHEMA_INVALID", "输出不是 JSON 对象")
        error = next(iter(self._validators[task_type].iter_errors(output)), None)
        if error is not None:
            location = "/".join(str(p) for p in error.absolute_path) or "<root>"
            raise OutputRejected("SCHEMA_INVALID", f"{location}: {error.message}")

        if task_type is TaskType.VISUAL_SPEC:
            payload = output["payload"]
            try:
                params = self._visual_registry.normalize(payload["template_id"], payload["params"])
            except VisualTemplateError as rejected:
                raise OutputRejected("SCHEMA_INVALID", str(rejected)) from rejected
            output = {**output, "payload": {**payload, "params": params}}

        # Identities are validated before content checks. Never treat digest digits as prose.
        resolved_texts: list[str] = []
        allowed = {item.identity(): item for item in constraints.reference_catalog}
        seen: set[tuple[str, str, int, int]] = set()
        for raw_reference in output.get("references", []):
            try:
                reference = ContentSpanRef.model_validate(raw_reference)
            except ValidationError as rejected:
                raise OutputRejected("SCHEMA_INVALID", "引用身份或区间无效") from rejected
            identity = reference.identity()
            if identity in seen or identity not in allowed:
                raise OutputRejected("SCHEMA_INVALID", "引用不在审核允许的精确范围内")
            seen.add(identity)
            resolved = allowed[identity]
            resolved_texts.extend(
                [
                    resolved.block_text,
                    resolved.block_text[reference.start : reference.end],
                    resolved.label,
                ]
            )

        forbidden = [_fold(item) for item in constraints.forbidden_substrings if item.strip()]
        content = output.get("payload", output)
        for text in [*_strings(content), *resolved_texts]:
            if contains_blocked_markup(text):
                raise OutputRejected("CONTENT_BLOCKED", "输出包含不允许的标记")
            folded = _fold(text)
            if any(item in folded for item in forbidden):
                raise OutputRejected("CONTENT_BLOCKED", "输出包含不允许出现的答案表述")
        return output
