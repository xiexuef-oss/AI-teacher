"""Dart 契约包与 Flutter 端测试共用的响应样例（tools/export_dart_fixtures.py 导出）。

样例里的 ID 每次导出都不同，所以这里不比对内容，只确认：每个样例仍然符合当前的契约，
并且覆盖了客户端要处理的各类教学事件与错误。
"""

from __future__ import annotations

import json

import pytest

from support import REPO_ROOT
from support.contract import find_operation, load_event_schema, validate_response

FIXTURE_DIR = REPO_ROOT / "packages" / "contracts" / "dart" / "test" / "fixtures"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _events(node):
    if isinstance(node, dict):
        if {"seq_no", "type", "payload", "meta"} <= node.keys():
            yield node
        for value in node.values():
            yield from _events(value)
    elif isinstance(node, list):
        for value in node:
            yield from _events(value)


def test_fixtures_have_been_exported():
    assert len(FIXTURES) >= 35, "请先运行 uv run python tools/export_dart_fixtures.py"


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture_still_matches_the_contract(path):
    fixture = _load(path)
    assert fixture["name"] == path.stem
    find_operation(fixture["method"], fixture["path"])
    validate_response(fixture["method"], fixture["path"], fixture["status"], fixture["body"])
    expected = fixture["body"] if "error" in fixture["body"] else fixture["body"]["data"]
    assert fixture["value"] == expected


def test_fixtures_cover_every_tutor_event_type():
    seen = {event["type"] for path in FIXTURES for event in _events(_load(path)["body"])}
    assert seen == set(load_event_schema()["$defs"]["EventType"]["enum"])


def test_fixtures_cover_the_error_cases_the_client_handles():
    codes = {
        _load(path)["body"]["error"]["code"] for path in FIXTURES if "error" in _load(path)["body"]
    }
    assert {
        "unauthenticated",
        "validation_error",
        "not_found",
        "not_implemented",
        "draft_revision_conflict",
        "independent_attempt_in_progress",
        "idempotency_key_conflict",
        "idempotency_key_required",
    } <= codes


def test_fixtures_cover_every_evaluation_state_the_ui_renders():
    states = {
        (evaluation["state"], evaluation["outcome"])
        for path in FIXTURES
        for evaluation in [_load(path)["body"].get("data", {}).get("evaluation")]
        if evaluation
    }
    assert {
        ("verified", "correct"),
        ("verified", "incorrect"),
        ("uncertain", "undetermined"),
    } <= states
