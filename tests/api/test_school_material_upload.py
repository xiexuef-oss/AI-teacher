from base64 import b64decode, b64encode
from hashlib import sha256

import pytest

from support.documents import png_image, text_pdf
from tutor_api.blob_store import FilesystemBlobStore


@pytest.fixture
def media_store(app, tmp_path):
    app.state.media_store = FilesystemBlobStore(
        tmp_path / "school-materials", max_bytes=app.state.settings.media_max_bytes
    )
    app.state.settings.scan_mock_enabled = True
    return app.state.media_store


def test_school_material_upload_is_private_and_idempotent(
    student, new_student, media_store, clock, settings
):
    data = png_image((320, 80))
    meta = {"mime": "image/png", "size_bytes": len(data), "sha256": sha256(data).hexdigest()}
    path = "/school-materials/uploads"
    source = student.data("POST", path, json=meta, key="reserve-school", expect=201)
    assert student.data("POST", path, json=meta, key="reserve-school", expect=201) == source
    upload = f"{path}/{source['media_id']}/content"
    body = {"content_base64": b64encode(data).decode("ascii")}
    other = new_student()
    other.error("PUT", upload, json=body, expect=404)
    student.error("PUT", f"/scans/uploads/{source['media_id']}/content", json=body, expect=404)
    student.error("PUT", upload, json={"content_base64": "aW52YWxpZA=="}, expect=422)
    receipt = student.data("PUT", upload, json=body, key="upload-school")
    assert receipt == {
        **meta,
        "media_id": source["media_id"],
        "expires_at": source["expires_at"],
        "page_count": 1,
    }
    assert student.data("PUT", upload, json=body, key="upload-school") == receipt
    clock.advance(settings.media_temporary_ttl_seconds)
    student.error("PUT", upload, json=body, expect=404)


def test_school_pdf_checks_actual_page_count(student, settings, media_store):
    settings.import_max_pages = 2
    for pages, expected in [(2, 200), (3, 413)]:
        data = text_pdf(*["Engineering sample"] * pages)
        upload = student.data(
            "POST",
            "/school-materials/uploads",
            expect=201,
            json={
                "mime": "application/pdf",
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            },
        )
        path = f"/school-materials/uploads/{upload['media_id']}/content"
        body = {"content_base64": b64encode(data).decode("ascii")}
        if expected == 200:
            assert student.data("PUT", path, json=body)["page_count"] == pages
        else:
            student.error("PUT", path, json=body, expect=expected)


def test_submit_only_uploaded_owned_material_and_reuse_job(student, new_student, media_store):
    data = png_image()
    upload = student.data(
        "POST",
        "/school-materials/uploads",
        expect=201,
        json={"mime": "image/png", "size_bytes": len(data), "sha256": sha256(data).hexdigest()},
    )
    body = {"media_id": upload["media_id"]}
    path = "/school-materials"
    student.error("POST", path, json=body, expect=404)
    student.data(
        "PUT",
        f"{path}/uploads/{upload['media_id']}/content",
        json={"content_base64": b64encode(data).decode("ascii")},
    )
    other = new_student()
    other.error("POST", path, json=body, expect=404)
    job = student.data("POST", path, json=body, key="submit-school", expect=202)
    assert job["status"] == "queued"
    assert student.data("POST", path, json=body, key="submit-school", expect=202) == job
    assert student.data("POST", path, json=body, expect=202) == job
    status = f"/learning/jobs/{job['id']}"
    assert student.data("GET", status) == job
    other.error("GET", status, expect=404)


@pytest.mark.parametrize(
    ("ocr_mode", "external_route", "expected_calls"),
    [("mock", False, 1), ("mock", True, 0), ("configured", True, 0)],
)
def test_worker_lists_private_pdf_text_and_marks_blank_pages(
    student,
    new_student,
    app,
    settings,
    clock,
    media_store,
    ocr_mode,
    external_route,
    expected_calls,
):
    from tutor_api.models import SchoolMaterialCorrection, SchoolMaterialResult
    from tutor_api.services.school_material_worker import process_one, purge_expired_results

    data = text_pdf("First page", "")
    root = "/school-materials"
    source = student.data(
        "POST",
        f"{root}/uploads",
        expect=201,
        json={
            "mime": "application/pdf",
            "size_bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        },
    )["media_id"]
    student.data(
        "PUT",
        f"{root}/uploads/{source}/content",
        json={"content_base64": b64encode(data).decode("ascii")},
    )
    job = student.data("POST", root, expect=202, json={"media_id": source})
    path = f"{root}/{job['id']}/pages"
    student.error("GET", path, expect=409)
    new_student().error("GET", path, expect=404)
    calls = []

    class MockGateway:
        external_calls_possible = external_route

        def invoke(self, request):
            from types import SimpleNamespace

            calls.append(request)
            return SimpleNamespace(provider="mock", confidence=None)

    settings.import_ocr_mode = ocr_mode
    assert process_one(app.state.session_factory, clock.now, settings, media_store, MockGateway())
    assert len(calls) == expected_calls
    if calls:
        assert calls[0].input_parts[1].media_ref.startswith("data:image/png;base64,")
    assert student.data("GET", f"/learning/jobs/{job['id']}")["status"] == "succeeded"
    preview_path = f"{path}/1/preview"
    new_student().error("GET", preview_path, expect=404)
    preview = student.request("GET", preview_path)
    assert preview.status_code == 200
    assert "no-store" in preview.headers["Cache-Control"]
    assert b64decode(preview.json()["data"]["content_base64"]).startswith(b"\x89PNG\r\n\x1a\n")
    student.error("GET", f"{path}/3/preview", expect=404)
    assert student.data("GET", path)["pages"] == [
        {"page_number": 1, "text": "First page", "needs_ocr": False},
        {"page_number": 2, "text": "", "needs_ocr": True},
    ]
    candidates = f"{root}/{job['id']}/candidates"
    new_student().error("GET", candidates, expect=404)
    edit = f"{path}/2/correction"
    body = {"expected_revision": 0, "text": "Student transcription"}
    new_student().error("PUT", edit, json=body, expect=404)
    receipt = student.data("PUT", edit, json=body, key="material-correction")
    assert receipt == {"page_number": 2, "revision": 1}
    assert student.data("PUT", edit, json=body, key="material-correction") == receipt
    student.error("PUT", edit, json=body, expect=409)
    assert student.data("GET", path)["pages"][1] == {
        "page_number": 2,
        "text": body["text"],
        "needs_ocr": False,
        "revision": 1,
    }
    assert (
        student.data("PUT", edit, json={"expected_revision": 1, "text": "Second transcription"})[
            "revision"
        ]
        == 2
    )
    assert student.data("GET", path)["pages"][1]["text"] == "Second transcription"
    text = "1. First question\n2. Second question\n参考答案\n1. A"
    student.data("PUT", edit, json={"expected_revision": 2, "text": text})
    suggestion = student.data("GET", candidates)
    items = suggestion["items"]
    assert [item["text"] for item in items] == [
        "First page",
        "1. First question",
        "2. Second question",
    ]
    assert items[2]["locations"] == [{"page": 2, "block": 2}]
    confirm = f"{root}/{job['id']}/confirmation"
    payload = {
        "source_revision": suggestion["source_revision"],
        "items": [{"text": "Merged question", "pages": [1, 2]}],
    }
    new_student().error("PUT", confirm, json=payload, expect=404)
    receipt = student.data("PUT", confirm, json=payload, key="confirm-material")
    assert receipt == {"source_revision": payload["source_revision"], "item_count": 1}
    assert student.data("PUT", confirm, json=payload, key="confirm-material") == receipt
    assert student.data("GET", candidates)["confirmed_items"] == payload["items"]
    student.data("PUT", edit, json={"expected_revision": 3, "text": "Updated text"})
    student.error("PUT", confirm, json=payload, expect=409)
    assert "confirmed_items" not in student.data("GET", candidates)
    with app.state.session_factory() as session:
        assert session.get_one(SchoolMaterialResult, job["id"]).pages_json[1]["text"] == ""
        assert session.get_one(SchoolMaterialCorrection, (job["id"], 2, 1)).text == body["text"]
    clock.advance(settings.media_temporary_ttl_seconds)
    student.error("GET", path, expect=404)
    student.error("GET", preview_path, expect=404)
    student.error("PUT", edit, json={**body, "expected_revision": 1}, expect=404)
    purge_expired_results(app.state.session_factory, clock.now())
    with app.state.session_factory() as session:
        assert session.get(SchoolMaterialResult, job["id"]) is None
        assert session.get(SchoolMaterialCorrection, (job["id"], 2, 1)) is None


def test_school_material_resumes_after_worker_lease_expires(
    student, app, settings, clock, media_store
):
    from tutor_api.models import SchoolMaterialResult
    from tutor_api.services.learning_jobs import LEASE, claim
    from tutor_api.services.school_material_worker import process_one

    data = png_image()
    root = "/school-materials"
    source = student.data(
        "POST",
        f"{root}/uploads",
        expect=201,
        json={"mime": "image/png", "size_bytes": len(data), "sha256": sha256(data).hexdigest()},
    )["media_id"]
    student.data(
        "PUT",
        f"{root}/uploads/{source}/content",
        json={"content_base64": b64encode(data).decode("ascii")},
    )
    job = student.data("POST", root, expect=202, json={"media_id": source})
    sessions = app.state.session_factory
    with sessions.begin() as db:
        assert claim(db, job["id"], clock.now())
    assert not process_one(sessions, clock.now, settings, media_store)
    with sessions() as db:
        assert db.get(SchoolMaterialResult, job["id"]) is None
    clock.advance(LEASE.total_seconds())
    assert process_one(sessions, clock.now, settings, media_store)
    assert student.data("GET", f"/learning/jobs/{job['id']}") == {
        "id": job["id"],
        "status": "succeeded",
        "attempts": 2,
    }
    assert student.data("GET", f"{root}/{job['id']}/pages")["pages"] == [
        {"page_number": 1, "text": "", "needs_ocr": True},
    ]
    assert not process_one(sessions, clock.now, settings, media_store)


def test_cancelled_school_material_never_publishes_in_flight_parse(
    student, app, settings, clock, media_store, monkeypatch
):
    from tutor_api.models import SchoolMaterialResult
    from tutor_api.services import school_material_worker as worker

    data = text_pdf("1. Example question.")
    root = "/school-materials"
    source = student.data(
        "POST",
        f"{root}/uploads",
        expect=201,
        json={
            "mime": "application/pdf",
            "size_bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        },
    )["media_id"]
    student.data(
        "PUT",
        f"{root}/uploads/{source}/content",
        json={"content_base64": b64encode(data).decode("ascii")},
    )
    job = student.data("POST", root, expect=202, json={"media_id": source})["id"]
    status = f"/learning/jobs/{job}"
    parse = worker.parse_isolated

    def cancel_after_parse(*args):
        result = parse(*args)
        assert student.data("GET", status)["status"] == "running"
        assert student.data("POST", f"{status}/cancel")["status"] == "cancelled"
        return result

    monkeypatch.setattr(worker, "parse_isolated", cancel_after_parse)
    sessions = app.state.session_factory
    assert worker.process_one(sessions, clock.now, settings, media_store)
    assert student.data("GET", status)["status"] == "cancelled"
    student.error("GET", f"{root}/{job}/pages", expect=409)
    with sessions() as db:
        assert db.get(SchoolMaterialResult, job) is None
    assert not worker.process_one(sessions, clock.now, settings, media_store)


def test_expired_school_source_does_not_retry(student, app, settings, clock, media_store):
    from tutor_api.services.school_material_worker import process_one

    data = png_image()
    root = "/school-materials"
    source = student.data(
        "POST",
        f"{root}/uploads",
        expect=201,
        json={"mime": "image/png", "size_bytes": len(data), "sha256": sha256(data).hexdigest()},
    )["media_id"]
    student.data(
        "PUT",
        f"{root}/uploads/{source}/content",
        json={"content_base64": b64encode(data).decode("ascii")},
    )
    job = student.data("POST", root, expect=202, json={"media_id": source})["id"]
    clock.advance(settings.media_temporary_ttl_seconds)
    assert process_one(app.state.session_factory, clock.now, settings, media_store)
    assert student.data("GET", f"/learning/jobs/{job}")["status"] == "failed"
