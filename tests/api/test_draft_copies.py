import json

import pytest
from sqlalchemy import func, select

from support.admin import decide, detail_of, edit, edit_body
from support.flows import CORRECT, INK, begin, choice, submit, tutor
from support.seeds import qid
from tutor_api.models import Attempt, StudySession, TutorEventRow

KEY = "math-mono-quadratic"


def body(revision=0, answer=None):
    return {
        "source_revision": revision,
        "answer": choice("A") if answer is None else answer,
        "strokes": INK,
    }


def copy(student, attempt_id, payload=None, **kwargs):
    return student.data(
        "POST", f"/attempts/{attempt_id}/copies", json=payload or body(), expect=201, **kwargs
    )


def test_copy_preserves_source_and_full_snapshot_without_submitting(onboarded, db):
    session, original = begin(onboarded, KEY)
    path = f"/attempts/{original['id']}/draft"
    source = onboarded.data(
        "PUT", path, json={"base_revision": 0, "answer": choice("B"), "strokes": INK}
    )
    full = {
        **choice("A"),
        "blanks": [{"key": "a", "value": "本机填空"}],
        "parts": [{"key": "1", "text": "未完成的小问"}],
        "cells": [{"table": "t1", "row": "r1", "col": "x", "value": "草稿数据"}],
        "steps": [{"text": "", "reason": ""}, {"text": "本机一步", "reason": "待补依据"}],
    }
    result = copy(onboarded, original["id"], body(1, full))
    new = result["attempt"]
    assert new["id"] != original["id"] and new["session_id"] == session["id"]
    assert new["attempt_no"] == 2 and new["submission_no"] is None
    assert new["copied_from_attempt_id"] == original["id"]
    assert new["copied_from_revision"] == 1
    assert new["status"] == "draft" and new["evaluation"] is None
    assert new["independent"] is None and new["assisted"] is False
    assert result["draft"]["revision"] == 1
    assert result["draft"]["answer"] == full and result["draft"]["strokes"] == INK
    assert onboarded.data("GET", path) == source
    assert result["session"]["active_attempt_id"] == original["id"]
    assert result["session"]["submitted_attempts"] == 0
    assert db.scalar(select(func.count()).select_from(StudySession)) == 1
    assert db.scalar(select(func.count()).select_from(Attempt)) == 2
    assert db.scalar(select(func.count()).select_from(TutorEventRow)) == 0


def test_copy_replays_even_after_source_changes_and_submits(onboarded):
    _, original = begin(onboarded, KEY)
    payload = body()
    first = copy(onboarded, original["id"], payload, key="copy-lost-response")
    onboarded.data(
        "PUT", f"/attempts/{original['id']}/draft", json={"base_revision": 0, "answer": choice("B")}
    )
    submit(onboarded, original["id"], CORRECT[KEY])
    assert copy(onboarded, original["id"], payload, key="copy-lost-response") == first
    onboarded.error(
        "POST",
        f"/attempts/{original['id']}/copies",
        json=body(answer=choice("C")),
        key="copy-lost-response",
        expect=409,
    )


def test_copy_checks_current_revision_and_changes_neither_side(onboarded, db):
    _, original = begin(onboarded, KEY)
    current = onboarded.data(
        "PUT", f"/attempts/{original['id']}/draft", json={"base_revision": 0, "answer": choice("B")}
    )
    error = onboarded.error("POST", f"/attempts/{original['id']}/copies", json=body(), expect=409)
    assert error["details"]["server_draft"] == current
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1


def test_copy_uses_owner_and_role_not_request_student_id(onboarded, new_student, reviewer):
    _, original = begin(onboarded, KEY)
    path = f"/attempts/{original['id']}/copies"
    new_student().error("POST", path, json=body(), expect=404)
    reviewer.error("POST", path, json=body(), expect=403)
    onboarded.error("POST", path, json={**body(), "student_id": onboarded.user_id}, expect=422)
    onboarded.error("POST", path, json=body(), key=False, expect=400)


def test_both_drafts_share_help_and_can_finish_separately(onboarded):
    session, original = begin(onboarded, KEY)
    saved = copy(onboarded, original["id"])
    tutor(onboarded, session["id"], "request_hint")
    first = submit(onboarded, saved["attempt"]["id"], CORRECT[KEY])
    assert first["evaluation"]["assisted"] is True
    assert first["attempt"]["submission_no"] == 1
    finished = tutor(onboarded, session["id"], "mark_understood")
    assert finished["session"]["state"] != "DONE"
    assert finished["session"]["active_attempt_id"] == original["id"]
    second = submit(onboarded, original["id"], CORRECT[KEY])
    assert second["evaluation"]["independent"] is False
    assert second["attempt"]["submission_no"] == 2
    assert tutor(onboarded, session["id"], "mark_understood")["session"]["state"] == "DONE"


def test_draft_discovery_is_private_paginated_and_contains_no_content(onboarded, new_student):
    session, original = begin(onboarded, KEY)
    copies = [copy(onboarded, original["id"])["attempt"]["id"] for _ in range(3)]
    path = f"/questions/{qid(KEY)}/drafts"
    first = onboarded.data("GET", path, params={"limit": 2})
    second = onboarded.data("GET", path, params={"limit": 2, "cursor": first["next_cursor"]})
    items = first["items"] + second["items"]
    assert {item["attempt_id"] for item in items} == {original["id"], *copies}
    assert {item["session_id"] for item in items} == {session["id"]}
    assert second["next_cursor"] is None
    assert all(not {"answer", "strokes", "stem", "teaching"}.intersection(item) for item in items)
    assert new_student().data("GET", path)["items"] == []
    onboarded.error("GET", path, params={"cursor": "invalid"}, expect=400)


def test_copy_responses_and_replay_are_not_cached(onboarded):
    _, original = begin(onboarded, KEY)
    path = f"/attempts/{original['id']}/copies"
    for _ in range(2):
        response = onboarded.post(path, json=body(), key="private-copy-replay")
        assert response.status_code == 201
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Pragma"] == "no-cache"
    invalid = onboarded.post(path, json={**body(), "used_solution": False})
    assert invalid.status_code == 422 and invalid.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("revision", [True, "0", -1])
def test_copy_revision_requires_a_nonnegative_integer(onboarded, revision):
    _, original = begin(onboarded, KEY)
    onboarded.error("POST", f"/attempts/{original['id']}/copies", json=body(revision), expect=422)


def test_copy_failure_rolls_back_both_rows_and_allows_same_key_retry(onboarded, db, monkeypatch):
    from tutor_api.errors import conflict
    from tutor_api.models import HandwritingDraft
    from tutor_api.services import session_service

    _, original = begin(onboarded, KEY)
    append = session_service._append_attempt

    def failing_append(*args, **kwargs):
        append(*args, **kwargs)
        raise conflict("copy_save_failed", "验证复制中断回滚")

    with monkeypatch.context() as scoped:
        scoped.setattr(session_service, "_append_attempt", failing_append)
        onboarded.error(
            "POST",
            f"/attempts/{original['id']}/copies",
            json=body(),
            key="copy-transaction-retry",
            expect=409,
        )
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1
    assert db.scalar(select(func.count()).select_from(HandwritingDraft)) == 1
    saved = copy(onboarded, original["id"], key="copy-transaction-retry")
    assert saved["attempt"]["copied_from_attempt_id"] == original["id"]
    assert db.scalar(select(func.count()).select_from(Attempt)) == 2


@pytest.mark.parametrize("role", ["parent", "reviewer", "admin"])
def test_private_copy_routes_are_student_only(onboarded, new_reviewer, role):
    session, original = begin(onboarded, KEY)
    other_role = new_reviewer(role)
    other_role.error("POST", f"/attempts/{original['id']}/copies", json=body(), expect=403)
    other_role.error("GET", f"/questions/{qid(KEY)}/drafts", expect=403)
    other_role.error("GET", f"/sessions/{session['id']}/question", expect=403)


def test_copy_body_limit_keeps_source_and_creates_nothing(onboarded, app, db):
    _, original = begin(onboarded, KEY)
    oversized = body(answer={"text": "x" * app.state.settings.max_draft_bytes})
    onboarded.error("POST", f"/attempts/{original['id']}/copies", json=oversized, expect=413)
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1


def test_new_copy_of_submitted_source_is_rejected(onboarded):
    _, original = begin(onboarded, KEY)
    submit(onboarded, original["id"], CORRECT[KEY])
    error = onboarded.error("POST", f"/attempts/{original['id']}/copies", json=body(), expect=409)
    assert error["code"] == "attempt_already_submitted"


def test_session_question_is_owned_pinned_and_without_answers(onboarded, new_student, new_reviewer):
    session, _ = begin(onboarded, KEY)
    before = onboarded.data("GET", f"/questions/{qid(KEY)}")
    publisher = new_reviewer()
    decide(publisher, qid(KEY), "withdraw", comment="验证固定版本题面")
    detail = detail_of(publisher, qid(KEY))
    edit(
        new_reviewer(),
        qid(KEY),
        edit_body(
            detail,
            title="新版工程题面",
            difficulty=5,
            teaching={**detail["teaching"], "reference_links": []},
            content={**detail["content"], "stem": detail["content"]["stem"] + "（新版）"},
        ),
    )
    decide(publisher, qid(KEY), "approve", version=2)
    decide(publisher, qid(KEY), "publish", version=2)
    path = f"/sessions/{session['id']}/question"
    pinned = onboarded.data("GET", path)
    assert pinned["version"] == 1 and pinned["content"] == before["content"]
    assert pinned["difficulty"] == before["difficulty"] and pinned["title"] == before["title"]
    assert not {"answer", "rubric", "teaching", "solutions"}.intersection(pinned)
    assert "新版" not in json.dumps(pinned, ensure_ascii=False)
    new_student().error("GET", path, expect=404)
    decide(publisher, qid(KEY), "withdraw", version=2, comment="验证下线后拒绝读取")
    onboarded.error("GET", path, expect=404)
