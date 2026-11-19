import json
from pathlib import Path

import pytest
from test_document_import_candidates import editable
from test_document_import_jobs import PATH
from test_document_import_worker import queued

from tutor_api.proto_models import DocumentImportBatch
from tutor_api.services import document_import_batch
from tutor_api.services.document_import_service import cleanup_expired
from tutor_api.services.document_import_worker import process_next


def confirmed(reviewer, app, clock):
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    broken = json.loads(json.dumps(payload))
    broken["question"]["knowledge"] = ["missing-knowledge"]
    job_id = queued(reviewer, [("batch.json", json.dumps([payload, broken]).encode())])
    process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    items = [editable(item) for item in detail["candidates"]]
    for item in items:
        item["confirmed"] = True
    return reviewer.data(
        "POST",
        f"{PATH}/{job_id}/candidates",
        json={"expected_revision": detail["job"]["revision"], "items": items},
    )


def test_cleanup_between_item_commits_returns_not_found(reviewer, app, clock, monkeypatch):
    detail = confirmed(reviewer, app, clock)
    original, calls = document_import_batch.update, []

    def interleaved(model):
        if model is DocumentImportBatch:
            calls.append(1)
            if len(calls) == 2:
                clock.advance(hours=3)
                with app.state.session_factory() as db:
                    cleanup_expired(db, clock.now())
                    db.commit()
        return original(model)

    monkeypatch.setattr(document_import_batch, "update", interleaved)
    response = reviewer.request(
        "POST",
        f"{PATH}/{detail['job']['id']}/submit",
        json={
            "expected_revision": detail["job"]["revision"],
            "candidate_ids": [item["id"] for item in detail["candidates"]],
        },
    )
    assert response.status_code == 404


def test_same_request_completed_before_lock_replays_result(reviewer, app, clock, monkeypatch):
    detail = confirmed(reviewer, app, clock)
    path = f"{PATH}/{detail['job']['id']}/submit"
    body = {
        "expected_revision": detail["job"]["revision"],
        "candidate_ids": [item["id"] for item in detail["candidates"]],
    }
    original, winner = document_import_batch.workspace.advance, []

    def interleaved(ctx, job, revision):
        if not winner:
            winner.append(None)
            winner[0] = reviewer.data("POST", path, json=body, key="same-batch-race-key")
        return original(ctx, job, revision)

    monkeypatch.setattr(document_import_batch.workspace, "advance", interleaved)
    result = reviewer.data("POST", path, json=body, key="same-batch-race-key")
    assert result == winner[0]


def test_partial_batch_commits_success_and_retries_only_failed_item(reviewer, app, clock, student):
    detail = confirmed(reviewer, app, clock)
    path = f"{PATH}/{detail['job']['id']}/submit"
    body = {
        "expected_revision": detail["job"]["revision"],
        "candidate_ids": [item["id"] for item in detail["candidates"]],
    }
    result = reviewer.data("POST", path, json=body, key="batch-submit-key")
    assert [item["status"] for item in result["items"]] == ["imported", "failed"]
    assert reviewer.data("POST", path, json=body, key="batch-submit-key") == result
    question_id = result["items"][0]["question_id"]
    assert student.request("GET", f"/questions/{question_id}").status_code == 404
    current = reviewer.data("GET", f"{PATH}/{detail['job']['id']}")
    items = [editable(item) for item in current["candidates"]]
    items[1]["payload"]["question"]["knowledge"] = []
    saved = reviewer.data(
        "POST",
        f"{PATH}/{detail['job']['id']}/candidates",
        json={"expected_revision": current["job"]["revision"], "items": items},
    )
    result2 = reviewer.data(
        "POST", path, json={**body, "expected_revision": saved["job"]["revision"]}
    )
    assert [item["status"] for item in result2["items"]] == ["already_imported", "imported"]
    assert (
        result2["items"][0]["question_id"] == question_id
        and result2["job"]["status"] == "completed"
    )


def test_key_claimed_by_other_operation_before_batch_lock_has_no_side_effect(
    reviewer, app, clock, monkeypatch
):
    detail = confirmed(reviewer, app, clock)
    original = document_import_batch.workspace.advance
    used = []

    def interleaved(ctx, job, revision):
        if not used:
            used.append(True)
            response = reviewer.request(
                "POST",
                PATH,
                json={
                    "title": "competing",
                    "defaults": detail["defaults"],
                    "creation_deadline": reviewer.data("GET", "/admin/import-options")[
                        "creation_deadline"
                    ],
                },
                key="batch-competing-key",
            )
            assert response.status_code == 201
        return original(ctx, job, revision)

    monkeypatch.setattr(document_import_batch.workspace, "advance", interleaved)
    response = reviewer.request(
        "POST",
        f"{PATH}/{detail['job']['id']}/submit",
        json={
            "expected_revision": detail["job"]["revision"],
            "candidate_ids": [item["id"] for item in detail["candidates"]],
        },
        key="batch-competing-key",
    )
    assert response.status_code == 409
    current = reviewer.data("GET", f"{PATH}/{detail['job']['id']}")
    assert all(item["question_id"] is None for item in current["candidates"])


def test_unconfirmed_cannot_be_imported(reviewer, app, clock):
    job_id = queued(
        reviewer,
        [("sample.json", Path("apps/admin_web/public/examples/question-import.json").read_bytes())],
    )
    process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    result = reviewer.data(
        "POST",
        f"{PATH}/{job_id}/submit",
        json={
            "expected_revision": detail["job"]["revision"],
            "candidate_ids": [detail["candidates"][0]["id"]],
        },
    )
    assert result["items"][0]["status"] == "failed" and result["items"][0]["question_id"] is None


def test_crash_after_first_commit_resumes_with_original_key_and_revision(
    reviewer, app, clock, monkeypatch
):
    detail = confirmed(reviewer, app, clock)
    path = f"{PATH}/{detail['job']['id']}/submit"
    body = {
        "expected_revision": detail["job"]["revision"],
        "candidate_ids": [item["id"] for item in detail["candidates"]],
    }
    original, calls = document_import_batch.import_draft, []

    def interrupted(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated process interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(document_import_batch, "import_draft", interrupted)
    with pytest.raises(RuntimeError, match="simulated process"):
        reviewer.request("POST", path, json=body, key="batch-recover-key")
    current = reviewer.data("GET", f"{PATH}/{detail['job']['id']}")
    first_id = current["candidates"][0]["question_id"]
    assert first_id is not None and current["candidates"][1]["question_id"] is None
    assert (
        reviewer.request(
            "POST",
            PATH,
            json={
                "title": "different",
                "defaults": detail["defaults"],
                "creation_deadline": reviewer.data("GET", "/admin/import-options")[
                    "creation_deadline"
                ],
            },
            key="batch-recover-key",
        ).status_code
        == 409
    )
    monkeypatch.setattr(document_import_batch, "import_draft", original)
    result = reviewer.data("POST", path, json=body, key="batch-recover-key")
    assert result["items"][0]["question_id"] == first_id
    assert [item["status"] for item in result["items"]] == ["imported", "failed"]
