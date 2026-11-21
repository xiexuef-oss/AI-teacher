from base64 import b64decode, b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Barrier, Event

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
    settings.import_isolation_mode = "linux_bwrap"
    student.error("PUT", upload, json=body, expect=503)
    settings.import_isolation_mode = "process"
    pixel_limit = settings.media_max_pixels
    settings.media_max_pixels = 1024
    student.error("PUT", upload, json=body, expect=422)
    settings.media_max_pixels = pixel_limit
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
            return SimpleNamespace(
                provider="mock",
                confidence=0.36,
                validated_output={"stem_text": "2. x = -3\n教师红笔：扣 2 分"},
                review_required=True,
            )

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
    before_correction = student.data("GET", candidates)
    assert [item["text"] for item in before_correction["items"]] == ["First page", ""]
    assert before_correction["items"][1]["locations"] == [{"page": 2, "block": None}]
    assert "confirmed_items" not in before_correction
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
    teacher_region = {
        "page": 1,
        "kind": "teacher_mark",
        "left": 0.5,
        "top": 0.75,
        "right": 1,
        "bottom": 1,
    }
    payload = {
        "source_revision": suggestion["source_revision"],
        "items": [
            {
                "text": "Merged question",
                "pages": [1, 2],
                "teacher_marks": "Check the sign",
                "teacher_score": 2.5,
                "regions": [teacher_region],
            },
            {"text": "Another question", "pages": [2], "teacher_marks": "No score visible"},
        ],
    }
    new_student().error("PUT", confirm, json=payload, expect=404)
    excessive = {**payload["items"][0], "max_score": 2}
    student.error("PUT", confirm, json={**payload, "items": [excessive]}, expect=422)
    for invalid in ({"page": 3}, {"top": 1}, {"right": 1.01}):
        item = {**payload["items"][0], "regions": [{**teacher_region, **invalid}]}
        student.error("PUT", confirm, json={**payload, "items": [item]}, expect=422)
    other_page = {**payload["items"][1], "regions": [teacher_region]}
    student.error("PUT", confirm, json={**payload, "items": [other_page]}, expect=422)
    receipt = student.data("PUT", confirm, json=payload, key="confirm-material")
    assert receipt == {"source_revision": payload["source_revision"], "item_count": 2}
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


def test_twenty_page_material_keeps_continuation_page_in_confirmation(
    student, app, settings, clock, media_store
):
    from json import dumps

    from sqlalchemy import select

    from tutor_api.db import new_id
    from tutor_api.models import AuditLog
    from tutor_api.proto_models import IdempotencyRecord
    from tutor_api.services.school_material_worker import process_one

    texts = [f"{n}. Original engineering question" for n in range(1, 20)]
    texts.append("Continuation: explain the last result.")
    data = text_pdf(*texts)
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
    assert process_one(app.state.session_factory, clock.now, settings, media_store, None)
    pages = f"{root}/{job}/pages"
    extracted = student.data("GET", pages)["pages"]
    assert [page["page_number"] for page in extracted] == list(range(1, 21))
    assert [page["text"] for page in extracted] == texts
    assert not any(page["needs_ocr"] for page in extracted)
    assert student.request("GET", f"{pages}/20/preview").status_code == 200
    student.error("GET", f"{pages}/21/preview", expect=404)
    barrier = Barrier(2)

    def correct(text):
        barrier.wait(timeout=5)
        response = student.request(
            "PUT",
            f"{pages}/20/correction",
            json={"expected_revision": 0, "text": text},
        )
        return response.status_code, text

    with ThreadPoolExecutor(max_workers=2) as pool:
        corrections = list(pool.map(correct, ["First amended page", "Second amended page"]))
    assert sorted(status for status, _ in corrections) == [200, 409]
    winner = next(text for status, text in corrections if status == 200)
    assert student.data("GET", pages)["pages"][-1] == {
        "page_number": 20,
        "text": winner,
        "needs_ocr": False,
        "revision": 1,
    }
    with app.state.session_factory() as session:
        events = session.scalars(
            select(AuditLog).where(
                AuditLog.target_id == job, AuditLog.action == "school_material.page_corrected"
            )
        ).all()
    assert len(events) == 1
    assert events[0].actor_id == student.user_id
    assert events[0].detail_json == {"page_number": 20, "revision": 1}
    candidate_path = f"{root}/{job}/candidates"
    candidates = student.data("GET", candidate_path)
    assert "confirmed_items" not in candidates
    merged = {"text": "\n".join([texts[-2], winner]), "pages": [19, 20]}
    confirmation_path = f"{root}/{job}/confirmation"
    payload = {"source_revision": candidates["source_revision"], "items": [merged]}
    confirmation = student.data(
        "PUT",
        confirmation_path,
        json=payload,
    )
    assert confirmation["item_count"] == 1
    assert student.data("GET", candidate_path)["confirmed_items"] == [merged]
    legacy_key = "legacy-confirmation-replay"
    legacy_body = dumps(
        {"m": "PUT", "p": f"/api/v1{confirmation_path}", "b": payload},
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    with app.state.session_factory.begin() as session:
        session.add(
            IdempotencyRecord(
                id=new_id(),
                user_id=student.user_id,
                idempotency_key=legacy_key,
                fingerprint=sha256(legacy_body).hexdigest(),
                status_code=200,
                response_json={"data": confirmation},
                created_at=clock.now(),
            )
        )
    replay = student.request("PUT", confirmation_path, key=legacy_key, json=payload)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["data"] == confirmation
    changed = {**payload, "items": [{**merged, "teacher_score": 0}]}
    assert (
        student.error("PUT", confirmation_path, key=legacy_key, json=changed, expect=409)["code"]
        == "idempotency_key_conflict"
    )


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


def test_standalone_worker_removes_expired_private_originals(app, settings, tmp_path):
    from tutor_api.services.learning_pack_worker import LearningPackWorker

    cleaned = Event()

    class ObservedStore(FilesystemBlobStore):
        def cleanup(self, *, now):
            removed = super().cleanup(now=now)
            cleaned.set()
            return removed

    now = datetime(2026, 11, 21, tzinfo=UTC)
    data = b"private original"
    store = ObservedStore(tmp_path / "media", max_bytes=1024)
    for lifetime in (1, 3):
        blob = store.reserve(
            owner="student",
            purpose="school_material",
            mime="application/pdf",
            size_bytes=len(data),
            sha256=sha256(data).hexdigest(),
            expires_at=now + timedelta(minutes=lifetime),
            now=now,
        )
        store.put(blob.id, owner="student", data=data, now=now)
    assert len(list(store.root.glob("*.bin"))) == 2
    sweep_at = now + timedelta(minutes=2)
    worker = LearningPackWorker(
        app.state.session_factory, lambda: sweep_at, settings, media_store=store
    )
    worker.start()
    try:
        assert cleaned.wait(timeout=5)
    finally:
        worker.close()
    assert list(store.root.glob("*.bin")) == [store.root / f"{blob.id}.bin"]
    assert list(store.root.glob("*.json")) == [store.root / f"{blob.id}.json"]
    assert store.read(blob.id, owner="student", now=sweep_at, temporary=True) == data
