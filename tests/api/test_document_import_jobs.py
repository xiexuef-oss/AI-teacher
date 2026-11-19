"""文档导入任务：角色、归属、上传限额、幂等和持久化队列。"""

import base64
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from support.api import LOOPBACK, ApiClient
from tutor_api.main import create_app
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob, IdempotencyRecord
from tutor_api.services.document_import_service import cleanup_expired

PATH = "/admin/import-jobs"


def job_body():
    return {
        "title": "自编文档导入测试",
        "defaults": {
            "subject": "math",
            "answer_mode": "written",
            "source": {
                "source_type": "self_authored",
                "source_category": "foundation",
                "source_name": "自编工程样题",
                "source_year": None,
                "source_license": "internal-engineering-sample",
                "source_url": None,
            },
        },
    }


def create_job(who, **kwargs):
    payload = {
        **job_body(),
        "creation_deadline": who.data("GET", "/admin/import-options")["creation_deadline"],
    }
    return who.data("POST", PATH, json=payload, expect=201, **kwargs)


def upload_body(revision=1, *, filename="sample.json", data=None):
    if data is None:
        data = Path("apps/admin_web/public/examples/question-import.json").read_bytes()
    return {
        "expected_revision": revision,
        "filename": filename,
        "content_base64": base64.b64encode(data).decode(),
    }


def test_create_list_and_read_job(reviewer):
    created = create_job(reviewer)
    assert created["status"] == "uploading" and created["revision"] == 1
    assert created["file_count"] == 0
    page = reviewer.data("GET", PATH)
    assert [item["id"] for item in page["items"]] == [created["id"]]
    detail = reviewer.data("GET", f"{PATH}/{created['id']}")
    assert detail["job"] == created and detail["files"] == detail["candidates"] == []
    assert detail["defaults"] == job_body()["defaults"]


def test_create_and_upload_replay_do_not_duplicate(reviewer):
    job = create_job(reviewer, key="doc-create-retry")
    assert create_job(reviewer, key="doc-create-retry") == job
    path = f"{PATH}/{job['id']}/files"
    first = reviewer.data("POST", path, json=upload_body(), expect=201, key="doc-upload-retry")
    second = reviewer.data("POST", path, json=upload_body(), expect=201, key="doc-upload-retry")
    assert first == second
    assert first["job"]["revision"] == 2 and first["file"]["kind"] == "json"
    detail = reviewer.data("GET", f"{PATH}/{job['id']}")
    assert len(detail["files"]) == 1
    assert "content_base64" not in json.dumps(detail)
    original = reviewer.data("GET", f"{path}/{first['file']['id']}/content")
    assert original["content_base64"] == upload_body()["content_base64"]


def test_role_check_precedes_body_validation(student):
    student.error("POST", PATH, json={"invalid": True}, expect=403)
    student.error("POST", f"{PATH}/{uuid4()}/files", json={"invalid": True}, expect=403)


def test_another_reviewer_cannot_read_mutate_or_download(reviewer, new_reviewer):
    other = new_reviewer()
    job = create_job(reviewer)
    accepted = reviewer.data("POST", f"{PATH}/{job['id']}/files", json=upload_body(), expect=201)
    assert other.data("GET", PATH)["items"] == []
    for suffix in ["", f"/files/{accepted['file']['id']}/content"]:
        assert other.error("GET", f"{PATH}/{job['id']}{suffix}", expect=404)["code"] == "not_found"
    other.error("POST", f"{PATH}/{job['id']}/files", json=upload_body(2), expect=404)


@pytest.mark.parametrize(
    "change",
    [{"filename": "../bad.json"}, {"filename": "bad.png"}, {"content_base64": "not/base64%%%"}],
)
def test_invalid_upload_does_not_advance_revision(reviewer, change):
    job = create_job(reviewer)
    body = {**upload_body(), **change}
    reviewer.error("POST", f"{PATH}/{job['id']}/files", json=body, expect=422)
    detail = reviewer.data("GET", f"{PATH}/{job['id']}")
    assert detail["job"]["revision"] == 1 and detail["files"] == []


def test_oversize_file_is_rejected_without_saving(reviewer, app):
    app.state.settings.import_max_file_bytes = 1024
    job = create_job(reviewer)
    reviewer.error(
        "POST",
        f"{PATH}/{job['id']}/files",
        json=upload_body(data=b"{" + b"a" * 2048 + b"}"),
        expect=422,
    )
    assert reviewer.data("GET", f"{PATH}/{job['id']}")["files"] == []


def test_queue_and_cancel_enforce_revision_and_preserve_no_students_visibility(reviewer):
    job = create_job(reviewer)
    reviewer.data("POST", f"{PATH}/{job['id']}/files", json=upload_body(), expect=201)
    reviewer.error("POST", f"{PATH}/{job['id']}/process", json={"expected_revision": 1}, expect=409)
    queued = reviewer.data("POST", f"{PATH}/{job['id']}/process", json={"expected_revision": 2})
    assert queued["status"] == "queued"
    cancelled = reviewer.data("POST", f"{PATH}/{job['id']}/cancel", json={"expected_revision": 3})
    assert cancelled["status"] == "cancelled"
    reviewer.error("POST", f"{PATH}/{job['id']}/files", json=upload_body(4), expect=409)


def test_empty_job_cannot_be_processed(reviewer):
    job = create_job(reviewer)
    reviewer.error("POST", f"{PATH}/{job['id']}/process", json={"expected_revision": 1}, expect=422)


def test_queue_and_original_file_survive_app_restart(reviewer, settings, clock):
    job = create_job(reviewer)
    uploaded = reviewer.data("POST", f"{PATH}/{job['id']}/files", json=upload_body(), expect=201)
    reviewer.data("POST", f"{PATH}/{job['id']}/process", json={"expected_revision": 2})
    with TestClient(create_app(settings, clock=clock.now), client=LOOPBACK) as raw:
        again = ApiClient(raw, token=reviewer.token, user_id=reviewer.user_id)
        detail = again.data("GET", f"{PATH}/{job['id']}")
        assert detail["job"]["status"] == "queued"
        assert detail["files"][0]["sha256"] == uploaded["file"]["sha256"]


def test_expired_job_is_invisible_and_cleanup_removes_original(reviewer, clock, db):
    job = create_job(reviewer)
    uploaded = reviewer.data("POST", f"{PATH}/{job['id']}/files", json=upload_body(), expect=201)
    clock.advance(hours=3)
    reviewer.error("GET", f"{PATH}/{job['id']}", expect=404)
    reviewer.error("GET", f"{PATH}/{job['id']}/files/{uploaded['file']['id']}/content", expect=404)
    assert reviewer.data("GET", PATH)["items"] == []
    assert cleanup_expired(db, clock.now()) == 1
    db.commit()
    assert db.get(DocumentImportJob, job["id"]) is None
    assert db.get(DocumentImportFile, uploaded["file"]["id"]) is None
    assert not any(
        job["id"] in json.dumps(record.response_json)
        for record in db.scalars(select(IdempotencyRecord))
    )
