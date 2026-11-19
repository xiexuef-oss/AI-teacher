import json
from pathlib import Path

from test_document_import_jobs import PATH
from test_document_import_worker import queued

from support.documents import text_pdf
from tutor_api.services.document_import_worker import process_next


def workspace(reviewer, app, clock):
    job_id = queued(reviewer, [("sample.pdf", text_pdf("1. Question"))])
    process_next(app.state.session_factory, app.state.settings, clock.now)
    return reviewer.data("GET", f"{PATH}/{job_id}")


def editable(candidate):
    return {
        key: candidate[key] for key in ("id", "title", "text", "locations", "payload", "confirmed")
    }


def test_save_split_merge_order_and_confirm_is_idempotent(reviewer, app, clock):
    detail = workspace(reviewer, app, clock)
    item = editable(detail["candidates"][0])
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    item.update(payload=payload, text=payload["question"]["content"]["stem"], confirmed=True)
    path = f"{PATH}/{detail['job']['id']}/candidates"
    body = {"expected_revision": detail["job"]["revision"], "items": [item]}
    saved = reviewer.data("POST", path, json=body, key="candidate-save-key")
    assert saved["candidates"][0]["confirmed_by"] == reviewer.user_id
    assert reviewer.data("POST", path, json=body, key="candidate-save-key") == saved
    assert reviewer.request("POST", path, json=body).status_code == 409
    second = {**item, "id": None, "confirmed": False}
    split = reviewer.data(
        "POST", path, json={"expected_revision": saved["job"]["revision"], "items": [second, item]}
    )
    assert len(split["candidates"]) == 2
    assert split["candidates"][1]["id"] == item["id"]


def test_confirmation_requires_payload_and_consistent_stem(reviewer, app, clock):
    detail = workspace(reviewer, app, clock)
    item = editable(detail["candidates"][0])
    item["confirmed"] = True
    response = reviewer.request(
        "POST",
        f"{PATH}/{detail['job']['id']}/candidates",
        json={"expected_revision": detail["job"]["revision"], "items": [item]},
    )
    assert response.status_code == 422


def test_cannot_reference_another_jobs_candidate_or_file(reviewer, app, clock):
    first, second = workspace(reviewer, app, clock), workspace(reviewer, app, clock)
    item = editable(second["candidates"][0])
    path = f"{PATH}/{first['job']['id']}/candidates"
    assert (
        reviewer.request(
            "POST", path, json={"expected_revision": first["job"]["revision"], "items": [item]}
        ).status_code
        == 422
    )
    item["id"] = None
    assert (
        reviewer.request(
            "POST", path, json={"expected_revision": first["job"]["revision"], "items": [item]}
        ).status_code
        == 422
    )
