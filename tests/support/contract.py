"""按 contracts/openapi.yaml 与 tutor_event.schema.json 校验数据的测试工具。

响应体校验用 JSON Schema 2020-12（OpenAPI 3.1 的 schema 方言是它的超集）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from support import CONTRACTS_DIR, REPO_ROOT

OPENAPI_URI = "https://ai-tutor.invalid/contracts/openapi.yaml"
HTTP_METHODS = ("get", "put", "post", "delete", "patch")
API_PREFIX = "/api/v1"

_FORMAT_CHECKER = FormatChecker()


@lru_cache(maxsize=1)
def load_openapi() -> dict[str, Any]:
    return yaml.safe_load((CONTRACTS_DIR / "openapi.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_event_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "tutor_event.schema.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_visual_registry() -> dict[str, Any]:
    path = REPO_ROOT / "packages" / "visual_templates" / "registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resource = Resource.from_contents(load_openapi(), default_specification=DRAFT202012)
    return Registry().with_resource(uri=OPENAPI_URI, resource=resource)


def iter_operations() -> Iterator[tuple[str, str, dict[str, Any]]]:
    """逐个给出 (路径模板, 方法, 操作对象)。"""
    for path, item in load_openapi()["paths"].items():
        for method in HTTP_METHODS:
            if method in item:
                yield path, method, item[method]


def operations_by_id() -> dict[str, tuple[str, str, dict[str, Any]]]:
    return {op["operationId"]: (path, method, op) for path, method, op in iter_operations()}


def resolve(node: dict[str, Any]) -> dict[str, Any]:
    """解开文档内的 $ref（只支持 #/ 开头的本地引用）。"""
    while "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/"), f"只支持本地引用：{ref}"
        target: Any = load_openapi()
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


def _pointer(*parts: str) -> str:
    return "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def _path_regex(template: str) -> re.Pattern[str]:
    pattern = re.sub(r"\{[^/}]+\}", r"[^/]+", template)
    return re.compile(f"^{pattern}$")


def find_operation(method: str, url_path: str) -> tuple[str, dict[str, Any]]:
    """把实际请求路径匹配到契约里的路径模板。"""
    assert url_path.startswith(API_PREFIX), f"路径不在 {API_PREFIX} 下：{url_path}"
    relative = url_path[len(API_PREFIX) :] or "/"
    candidates = [
        (path, op)
        for path, m, op in iter_operations()
        if m == method.lower() and _path_regex(path).match(relative)
    ]
    assert candidates, f"契约中没有 {method.upper()} {relative}"
    # 字面量路径优先于带参数的模板（/reviews/due 优先于 /reviews/{id}）
    candidates.sort(key=lambda c: c[0].count("{"))
    return candidates[0]


def validate_event(event: dict[str, Any]) -> None:
    """按教学事件 Schema 校验一个事件，失败时抛 AssertionError。"""
    validator = Draft202012Validator(load_event_schema(), format_checker=_FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(event), key=lambda e: list(e.absolute_path))
    assert not errors, "教学事件不符合 Schema：" + "; ".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:5]
    )


def _walk_events(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if {"seq_no", "type", "payload", "meta"} <= node.keys():
            yield node
        for value in node.values():
            yield from _walk_events(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_events(value)


def validate_response(method: str, url_path: str, status: int, body: Any) -> None:
    """校验一次真实响应是否符合契约：状态码必须已声明，响应体必须过 schema。"""
    template, op = find_operation(method, url_path)
    responses = op["responses"]
    key = str(status)
    assert key in responses, (
        f"{op['operationId']} 返回了契约未声明的状态码 {status}（已声明：{sorted(responses)}）；"
        f"响应体：{body!r}"
    )
    declared = resolve(responses[key])
    content = declared.get("content")
    if not content:
        assert body in (None, "", b""), f"{op['operationId']} {status} 不应有响应体"
        return

    if "$ref" in responses[key]:
        pointer = (
            responses[key]["$ref"][2:] + "/" + _pointer("content", "application/json", "schema")
        )
    else:
        pointer = _pointer(
            "paths",
            template,
            method.lower(),
            "responses",
            key,
            "content",
            "application/json",
            "schema",
        )
    schema = {"$ref": f"{OPENAPI_URI}#/{pointer}"}
    validator = Draft202012Validator(schema, registry=_registry(), format_checker=_FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    assert not errors, f"{op['operationId']} {status} 响应不符合契约：" + "; ".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:5]
    )
    for event in _walk_events(body):
        validate_event(event)
