import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from support.flows import begin, events, tutor
from support.seeds import qid
from tutor_api.models import Question, QuestionVersion, StudySession
from tutor_api.services.content_references import catalog, resolve_proposals


def payload():
    value = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    text = value["question"]["content"]["stem"]
    value["question"]["teaching"]["reference_links"] = [
        {
            "target_block_id": "hint:1",
            "source_span": {
                "block_id": "stem",
                "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start": 0,
                "end": 2,
            },
            "independent_safe": True,
        }
    ]
    return value


def test_review_import_preserves_exact_span(reviewer):
    value = payload()
    result = reviewer.data("POST", "/admin/question-imports", json=value, expect=201)
    assert result["teaching"]["reference_links"] == value["question"]["teaching"]["reference_links"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", True),
        ("start", 0.5),
        ("end", 9999),
        ("block_sha256", "0" * 64),
        ("block_id", "hint:999"),
    ],
)
def test_review_import_rejects_bad_span(reviewer, field, value):
    data = payload()
    data["question"]["teaching"]["reference_links"][0]["source_span"][field] = value
    assert reviewer.request("POST", "/admin/question-imports", json=data).status_code == 422


def test_review_edit_changed_text_requires_reference_reaudit(reviewer):
    value = payload()
    first = reviewer.data("POST", "/admin/question-imports", json=value, expect=201)
    edit = {
        **value["question"],
        "expected_version": first["version"],
        "expected_review_revision": first["review_revision"],
    }
    edit["content"]["stem"] += " changed"
    assert (
        reviewer.request("POST", f"/admin/questions/{first['id']}/versions", json=edit).status_code
        == 422
    )


def test_hint_reviewed_rephrase_standard_emit_real_span_and_persist(onboarded, db):
    session, _ = begin(onboarded, "math-mono-quadratic")
    for action, extra in [
        ("request_hint", {}),
        ("mark_confused", {}),
        ("request_standard", {"confirm_end_independent": True}),
    ]:
        event = tutor(onboarded, session["id"], action, **extra)["events"][0]
        ref = event["references"][0]
        assert ref["block_id"] == "stem" and ref["start"] == 0 and ref["end"] == 2
        assert ref["end"] < len(ref["block_text"])
        assert ref["block_sha256"] == hashlib.sha256(ref["block_text"].encode()).hexdigest()
    stored = events(onboarded, session["id"])
    assert any(e.get("references") for e in stored)


def test_mock_rephrase_uses_exact_catalog_span(onboarded, db):
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == qid("math-mono-quadratic"), QuestionVersion.version == 1
        )
    )
    version.teaching_json = {**version.teaching_json, "concept_rephrase": None}
    db.commit()
    session, _ = begin(onboarded, "math-mono-quadratic")
    event = tutor(onboarded, session["id"], "mark_confused")["events"][0]
    assert event["meta"]["source"] == "model"
    assert event["references"][0]["end"] == 2


@pytest.mark.parametrize(
    "change", ["hidden_hint", "option", "unsafe_context", "not_declared_safe", "retest"]
)
def test_reference_catalog_filters_independent_visibility(onboarded, db, change):
    session, _ = begin(onboarded, "math-mono-quadratic")
    record = db.get(StudySession, session["id"])
    question = db.get(Question, record.question_id)
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == record.question_id, QuestionVersion.version == 1
        )
    )
    teaching = json.loads(json.dumps(version.teaching_json))
    link = teaching["reference_links"][0]
    if change in ("hidden_hint", "option"):
        block = "hint:3" if change == "hidden_hint" else "option:1"
        from tutor_api.services.content_references import version_blocks

        text = version_blocks(db, version)[block]
        link["source_span"] = {
            "block_id": block,
            "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "start": 0,
            "end": 2,
        }
    elif change == "unsafe_context":
        teaching["leak_markers"] = [version.content_json["stem"][-3:]]
    elif change == "not_declared_safe":
        link["independent_safe"] = False
    else:
        record.origin = "review"
    teaching["reference_links"] = [link]
    turn = SimpleNamespace(
        tc=SimpleNamespace(db=db),
        session=record,
        question=question,
        version=version,
        teaching=teaching,
        submitted=0,
    )
    assert catalog(turn, ["hint:1"]) == []


def test_model_exact_tuple_intersection_and_dedup():
    text = "甲😀é\n公式 $x^2$"
    span = {
        "block_id": "stem",
        "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "start": 1,
        "end": 3,
        "block_text": text,
        "label": "stem",
    }
    proposal = {k: span[k] for k in ("block_id", "block_sha256", "start", "end")}
    assert resolve_proposals([proposal, proposal], [span], [span]) == [span]
    with pytest.raises(ValueError):
        resolve_proposals([proposal], [span], [])
    with pytest.raises(ValueError):
        resolve_proposals([{**proposal, "end": 4}], [span], [span])


@pytest.mark.parametrize("count", [2, 9])
def test_duplicate_or_over_target_limit_rejected(reviewer, count):
    value = payload()
    link = value["question"]["teaching"]["reference_links"][0]
    value["question"]["teaching"]["reference_links"] = [
        {
            **link,
            "source_span": {
                **link["source_span"],
                "start": i if count == 9 else 0,
                "end": i + 1 if count == 9 else 2,
            },
        }
        for i in range(count)
    ]
    assert reviewer.request("POST", "/admin/question-imports", json=value).status_code == 422


def test_session_reference_uses_fixed_v1_not_latest_v2(onboarded, db, clock):
    session, _ = begin(onboarded, "math-mono-quadratic")
    original = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == qid("math-mono-quadratic"), QuestionVersion.version == 1
        )
    )
    content = {**original.content_json, "stem": "Different latest condition"}
    db.add(
        QuestionVersion(
            id="content-ref-v2",
            question_id=original.question_id,
            version=2,
            content_json=content,
            answer_json=original.answer_json,
            teaching_json=original.teaching_json,
            created_by=original.created_by,
            created_at=clock.now(),
        )
    )
    db.get(Question, original.question_id).version = 2
    db.commit()
    event = tutor(onboarded, session["id"], "request_hint")["events"][0]
    assert event["meta"]["question_version"] == 1
    assert event["references"][0]["block_text"] == original.content_json["stem"]


def test_standard_action_does_not_unlock_fast_reference(onboarded, db):
    from tutor_api.services.content_references import version_blocks

    session, _ = begin(onboarded, "math-mono-quadratic")
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == qid("math-mono-quadratic"), QuestionVersion.version == 1
        )
    )
    text = version_blocks(db, version)["solution:fast:step:1"]
    teaching = json.loads(json.dumps(version.teaching_json))
    teaching["reference_links"] = [
        {
            "target_block_id": "solution:standard:step:1",
            "source_span": {
                "block_id": "solution:fast:step:1",
                "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start": 0,
                "end": 2,
            },
            "independent_safe": False,
        }
    ]
    version.teaching_json = teaching
    db.commit()
    event = tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)[
        "events"
    ][0]
    assert "references" not in event


def test_subjective_rubric_requires_actual_submission(onboarded, db):
    from tutor_api.models import Rubric

    session, _ = begin(onboarded, "math-mono-quadratic")
    record = db.get(StudySession, session["id"])
    question = db.get(Question, record.question_id)
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == record.question_id, QuestionVersion.version == 1
        )
    )
    rubric = db.scalar(
        select(Rubric).where(Rubric.question_id == record.question_id, Rubric.version == 1)
    )
    rubric.rubric_json = {"points": [{"key": "p1", "text": "Check your reasoning"}]}
    text = "Check your reasoning"
    teaching = {
        **version.teaching_json,
        "reference_links": [
            {
                "target_block_id": "rephrase",
                "source_span": {
                    "block_id": "rubric:point:1",
                    "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "start": 0,
                    "end": 5,
                },
                "independent_safe": False,
            }
        ],
    }
    turn = SimpleNamespace(
        tc=SimpleNamespace(db=db),
        session=record,
        question=question,
        version=version,
        teaching=teaching,
        submitted=0,
    )
    question.answer_mode = "written"
    assert catalog(turn, ["rephrase"]) == []
    turn.submitted = 1
    assert catalog(turn, ["rephrase"])[0]["block_text"] == text
    question.answer_mode = "single_choice"
    assert catalog(turn, ["rephrase"]) == []


def test_gateway_return_cannot_restore_revoked_reference_permission(custom_student):
    from ai_gateway import ProviderResult
    from support.gateway_fakes import hint_ok

    class Adapter:
        callback = None

        def invoke(self, *, model, request, timeout_s):
            span = request.constraints.reference_catalog[0].model_dump()
            self.callback()
            return ProviderResult(
                output={
                    **hint_ok(),
                    "references": [
                        {k: span[k] for k in ("block_id", "block_sha256", "start", "end")}
                    ],
                }
            )

    adapter = Adapter()
    app, learner = custom_student(gateway_adapters={"mock": adapter})
    with app.state.session_factory() as db:
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == qid("math-mono-quadratic"),
                QuestionVersion.version == 1,
            )
        )
        version.teaching_json = {**version.teaching_json, "concept_rephrase": None}
        db.commit()

    def revoke():
        with app.state.session_factory() as db:
            version = db.scalar(
                select(QuestionVersion).where(
                    QuestionVersion.question_id == qid("math-mono-quadratic"),
                    QuestionVersion.version == 1,
                )
            )
            version.teaching_json = {**version.teaching_json, "reference_links": []}
            db.commit()

    adapter.callback = revoke
    session, _ = begin(learner, "math-mono-quadratic")
    event = tutor(learner, session["id"], "mark_confused")["events"][0]
    assert event["type"] == "fallback" and event["payload"]["reason_code"] == "SCHEMA_INVALID"
    assert not event.get("references")


def _catalog_turn(onboarded, db):
    session, _ = begin(onboarded, "math-mono-quadratic")
    record = db.get(StudySession, session["id"])
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == record.question_id, QuestionVersion.version == 1
        )
    )
    return SimpleNamespace(
        tc=SimpleNamespace(db=db),
        session=record,
        question=db.get(Question, record.question_id),
        version=version,
        teaching=json.loads(json.dumps(version.teaching_json)),
        submitted=0,
    )


def test_submission_does_not_bypass_full_context_leak_check(onboarded, db):
    turn = _catalog_turn(onboarded, db)
    turn.submitted = 1
    turn.teaching["leak_markers"] = [turn.version.content_json["stem"][-3:]]
    assert catalog(turn, ["hint:1"]) == []


def test_standard_multiple_steps_never_exceeds_event_reference_limit(onboarded, db):
    turn = _catalog_turn(onboarded, db)
    span = turn.teaching["reference_links"][0]["source_span"]
    links = []
    for i in range(9):
        links.append(
            {
                "target_block_id": "solution:standard:step:" + ("1" if i < 8 else "2"),
                "source_span": {**span, "start": i, "end": i + 1},
                "independent_safe": False,
            }
        )
    turn.version.teaching_json = {**turn.teaching, "reference_links": links}
    db.commit()
    event = tutor(onboarded, turn.session.id, "request_standard", confirm_end_independent=True)[
        "events"
    ][0]
    assert len(event["references"]) == 8


def test_reference_cells_directory_only_contains_actual_blanks():
    from tutor_api.services.content_references import blocks

    content = {
        "data_tables": [
            {
                "key": "t",
                "columns": [{"key": "c"}],
                "rows": [{"key": "r", "cells": [{"col": "c", "text": "visible given"}]}],
            }
        ]
    }
    assert "reference_cell:1:1:1" not in blocks(
        content, {}, {}, answer={"value": {"t.r.c": "reference"}}
    )
    content["data_tables"][0]["rows"][0]["cells"][0]["text"] = None
    assert (
        blocks(content, {}, {}, answer={"value": {"t.r.c": "reference"}})["reference_cell:1:1:1"]
        == "reference"
    )


def test_written_does_not_unlock_proof_reference_steps(onboarded, db):
    turn = _catalog_turn(onboarded, db)
    text = "Private proof step"
    turn.version.answer_json = {"value": {"steps": [{"text": text, "reason": "Proof reason"}]}}
    turn.question.answer_mode = "written"
    turn.submitted = 1
    turn.teaching["reference_links"] = [
        {
            "target_block_id": "rephrase",
            "source_span": {
                "block_id": "reference_step:1:text",
                "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start": 0,
                "end": 2,
            },
            "independent_safe": False,
        }
    ]
    assert catalog(turn, ["rephrase"]) == []


@pytest.mark.parametrize("kind", ["option", "visual"])
def test_only_actually_revealed_option_and_visual_sources(onboarded, db, kind):
    from tutor_api.services.content_references import version_blocks

    turn = _catalog_turn(onboarded, db)
    block = "option:1" if kind == "option" else "visual:caption"
    text = version_blocks(db, turn.version)[block]
    turn.teaching["reference_links"] = [
        {
            "target_block_id": "rephrase",
            "source_span": {
                "block_id": block,
                "block_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start": 0,
                "end": 2,
            },
            "independent_safe": True,
        }
    ]
    assert catalog(turn, ["rephrase"]) == []
    tutor(onboarded, turn.session.id, "request_fast", confirm_end_independent=True)
    db.refresh(turn.session)
    assert catalog(turn, ["rephrase"]) == []
    tutor(onboarded, turn.session.id, "request_standard")
    db.refresh(turn.session)
    if kind == "visual":
        assert catalog(turn, ["rephrase"]) == []
        tutor(onboarded, turn.session.id, "request_visual")
        db.refresh(turn.session)
    assert catalog(turn, ["rephrase"])[0]["block_id"] == block
