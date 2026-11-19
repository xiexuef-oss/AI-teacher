"""CONTENT303A self-authored document provenance: immutable metadata, never retained originals."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_document_import_candidates import editable
from test_document_import_jobs import PATH
from test_document_import_worker import queued

from support.admin import decide, edit, edit_body, snapshot
from support.documents import docx_document, png_image, text_pdf
from support.seeds import qid
from tutor_api.models import Question, QuestionVersion
from tutor_api.proto_models import DocumentImportCandidate, DocumentImportJob
from tutor_api.services.document_import_service import cleanup_expired
from tutor_api.services.document_import_worker import process_next


def prepare(reviewer, app, clock, *, multiple=False):
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    files = [("self-authored.json", json.dumps(payload).encode())]
    if multiple:
        files += [
            ("declared.pdf", text_pdf("Only engineering fixture")),
            (
                "fragments.docx",
                docx_document("<w:p><w:r><w:t>Engineering fragment</w:t></w:r></w:p>"),
            ),
            ("image.png", png_image()),
        ]
    job_id = queued(reviewer, files)
    process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    candidate = next(c for c in detail["candidates"] if c["payload"])
    row = editable(candidate)
    row["locations"] = [
        {"file_id": f["id"], "page": f["pages"][0]["number"], "block": 2} for f in detail["files"]
    ]
    row["confirmed"] = True
    saved = reviewer.data(
        "POST",
        f"{PATH}/{job_id}/candidates",
        json={"expected_revision": detail["job"]["revision"], "items": [row]},
    )
    return saved, dict(files)


def submit(reviewer, detail, key="provenance-submit"):
    body = {
        "expected_revision": detail["job"]["revision"],
        "candidate_ids": [detail["candidates"][0]["id"]],
    }
    result = reviewer.data("POST", f"{PATH}/{detail['job']['id']}/submit", json=body, key=key)
    return result, body


def test_origin_snapshot_survives_temporary_cleanup_without_retaining_document_access(
    reviewer, app, clock
):
    detail, files = prepare(reviewer, app, clock, multiple=True)
    result, body = submit(reviewer, detail)
    assert result["items"][0]["status"] == "imported"
    identifier = result["items"][0]["question_id"]
    formal = reviewer.data("GET", f"/admin/questions/{identifier}")
    provenance = formal.get("provenance")
    assert provenance is not None
    assert provenance["relation"] == "declared" and provenance["parent_version"] is None
    assert (
        provenance["access"] == "metadata_only"
        and provenance["source_snapshot"] == formal["source"]
    )
    locator = {
        "json": "json_fragment",
        "pdf": "pdf_page",
        "docx": "word_fragment",
        "png": "image_page",
    }
    assert {o["locator_kind"] for o in provenance["origins"]} == set(locator.values())
    for f in detail["files"]:
        assert {
            "file_sha256": hashlib.sha256(files[f["filename"]]).hexdigest(),
            "file_kind": f["kind"],
            "locator_kind": locator[f["kind"]],
            "index": 1,
            "declared_block": 2,
        } in provenance["origins"]
    assert (
        reviewer.data(
            "POST", f"{PATH}/{detail['job']['id']}/submit", json=body, key="provenance-submit"
        )
        == result
    )
    clock.advance(hours=3)
    with app.state.session_factory() as db:
        cleanup_expired(db, clock.now())
        db.commit()
        assert db.get(DocumentImportJob, detail["job"]["id"]) is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(QuestionVersion)
                .where(QuestionVersion.question_id == identifier)
            )
            == 1
        )
    assert reviewer.request("GET", f"{PATH}/{detail['job']['id']}").status_code == 404
    for file in detail["files"]:
        assert (
            reviewer.request(
                "GET", f"{PATH}/{detail['job']['id']}/files/{file['id']}/content"
            ).status_code
            == 404
        )
        assert file["id"] not in json.dumps(provenance)
        assert file["filename"] not in json.dumps(provenance)
    assert reviewer.data("GET", f"/admin/questions/{identifier}")["provenance"] == provenance


def test_versions_derive_metadata_without_rewriting_old_session_origin(
    reviewer, new_reviewer, onboarded, app, clock
):
    detail, _ = prepare(reviewer, app, clock)
    result, _ = submit(reviewer, detail)
    identifier = result["items"][0]["question_id"]
    first = reviewer.data("GET", f"/admin/questions/{identifier}")
    assert first.get("provenance") is not None
    publisher = new_reviewer()
    decide(publisher, identifier, "approve", solution_kinds=["standard", "fast"])
    decide(publisher, identifier, "publish")
    session = onboarded.data(
        "POST", "/sessions", expect=201, json={"question_id": identifier, "origin": "practice"}
    )
    decide(publisher, identifier, "withdraw", comment="self-authored revision")
    before = reviewer.data("GET", f"/admin/questions/{identifier}")
    second = edit(reviewer, identifier, edit_body(before, title="Derived title"))
    expected = {
        **copy.deepcopy(first["provenance"]),
        "relation": "derived_unverified",
        "parent_version": 1,
    }
    assert second["provenance"] == expected
    assert snapshot(reviewer, identifier, 1)["provenance"] == first["provenance"]
    assert snapshot(reviewer, identifier, 2)["provenance"] == expected
    decide(publisher, identifier, "approve", version=2, solution_kinds=["standard", "fast"])
    decide(publisher, identifier, "publish", version=2)
    assert (
        onboarded.data("GET", f"/sessions/{session['id']}/question")["provenance"]
        == first["provenance"]
    )
    assert onboarded.data("GET", f"/questions/{identifier}")["provenance"] == expected
    # A legacy historical row may be NULL while a later version has metadata.
    # Simulate that pre-existing shape directly; neither read may borrow latest.
    with app.state.session_factory() as db:
        old = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == identifier, QuestionVersion.version == 1
            )
        )
        old.provenance_json = None
        db.commit()
    assert snapshot(reviewer, identifier, 1)["provenance"] is None
    assert onboarded.data("GET", f"/sessions/{session['id']}/question")["provenance"] is None
    assert snapshot(reviewer, identifier, 2)["provenance"] == expected


def test_old_seed_and_manual_import_versions_do_not_invent_document_origin(reviewer):
    old = reviewer.data("GET", f"/admin/questions/{qid('math-mono-quadratic')}")
    assert old.get("provenance") is None
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    manual = reviewer.data("POST", "/admin/question-imports", json=payload, expect=201)
    assert manual.get("provenance") is None
    changed = edit(reviewer, manual["id"], edit_body(manual, title="Manual revision"))
    assert changed.get("provenance") is None


def test_foreign_job_location_revalidated_before_import_does_not_copy_foreign_hash(
    reviewer, new_reviewer, app, clock
):
    detail, _ = prepare(reviewer, app, clock)
    other, _ = prepare(new_reviewer(), app, clock)
    foreign = other["files"][0]
    with app.state.session_factory() as db:
        candidate = db.get(DocumentImportCandidate, detail["candidates"][0]["id"])
        candidate.locations_json = [{"file_id": foreign["id"], "page": 1, "block": None}]
        before = db.scalar(select(func.count()).select_from(Question))
        db.commit()
    result, _ = submit(reviewer, detail)
    assert result["items"][0]["status"] == "failed" and result["items"][0]["question_id"] is None
    assert foreign["sha256"] not in json.dumps(result)
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == before


@pytest.mark.parametrize(
    "location",
    [
        "foreign_same_owner",
        "missing_page",
        "invalid_block",
        "invalid_file_id",
        "missing_page_metadata",
    ],
)
def test_current_location_must_be_owned_current_file_and_declared_valid_index(
    reviewer, app, clock, location
):
    detail, _ = prepare(reviewer, app, clock)
    other, _ = prepare(reviewer, app, clock)
    with app.state.session_factory() as db:
        c = db.get(DocumentImportCandidate, detail["candidates"][0]["id"])
        if location == "foreign_same_owner":
            c.locations_json = [{"file_id": other["files"][0]["id"], "page": 1, "block": None}]
        elif location == "missing_page":
            c.locations_json = [{"file_id": detail["files"][0]["id"], "page": 999, "block": None}]
        elif location == "invalid_file_id":
            c.locations_json = [{"file_id": [], "page": 1, "block": None}]
        elif location == "missing_page_metadata":
            from tutor_api.proto_models import DocumentImportFile

            file = db.get(DocumentImportFile, detail["files"][0]["id"])
            file.pages_json = None
        else:
            c.locations_json = [{"file_id": detail["files"][0]["id"], "page": 1, "block": 0}]
        db.commit()
    result, _ = submit(reviewer, detail)
    assert result["items"][0]["status"] == "failed"
    assert result["items"][0]["question_id"] is None


def test_checkpoint_retry_preserves_single_version_and_single_origin_snapshot(
    reviewer, app, clock, monkeypatch
):
    from tutor_api.services import document_import_batch

    detail, _ = prepare(reviewer, app, clock)
    original = document_import_batch.workspace.audit
    seen = []

    def interrupt(ctx, job, action, metadata):
        if action == "submit_complete" and not seen:
            seen.append(True)
            raise RuntimeError("response lost after candidate checkpoint")
        return original(ctx, job, action, metadata)

    monkeypatch.setattr(document_import_batch.workspace, "audit", interrupt)
    with pytest.raises(RuntimeError, match="checkpoint"):
        submit(reviewer, detail, key="checkpoint-provenance")
    with app.state.session_factory() as db:
        c = db.get(DocumentImportCandidate, detail["candidates"][0]["id"])
        identifier = c.question_id
        assert identifier is not None
        version = db.scalar(
            select(QuestionVersion).where(QuestionVersion.question_id == identifier)
        )
        first = copy.deepcopy(version.provenance_json)
        assert first is not None
    result, _ = submit(reviewer, detail, key="checkpoint-provenance")
    assert result["items"][0]["question_id"] == identifier
    with app.state.session_factory() as db:
        versions = list(
            db.scalars(select(QuestionVersion).where(QuestionVersion.question_id == identifier))
        )
        assert len(versions) == 1 and versions[0].provenance_json == first


def test_public_import_and_edit_cannot_forge_provenance(reviewer, app, clock):
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    reviewer.error(
        "POST",
        "/admin/question-imports",
        json={**payload, "provenance": {"access": "metadata_only"}},
        expect=422,
    )
    detail, _ = prepare(reviewer, app, clock)
    result, _ = submit(reviewer, detail)
    identifier = result["items"][0]["question_id"]
    current = reviewer.data("GET", f"/admin/questions/{identifier}")
    reviewer.error(
        "POST",
        f"/admin/questions/{identifier}/versions",
        json={**edit_body(current, title="Client forged origin"), "provenance": None},
        expect=422,
    )
    assert reviewer.data("GET", f"/admin/questions/{identifier}")["version"] == 1


def test_legacy_receipt_and_response_models_allow_missing_optional_provenance(reviewer):
    from tutor_api.schemas import AdminQuestionDetail

    current = reviewer.data("GET", f"/admin/questions/{qid('math-mono-quadratic')}")
    current.pop("provenance", None)
    assert AdminQuestionDetail.model_validate(current).provenance is None
