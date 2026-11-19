import base64
import hashlib
import io
import json
import zipfile

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select

from support.contract import _FORMAT_CHECKER, OPENAPI_URI, _registry
from support.documents import png_image
from tutor_api.db import new_id
from tutor_api.scan_models import ScanRecord

EXPORT_PATH = "/profile/learning-export"
MEDIA_EXPORT_PATH = "/profile/media-export"


def unpack_media_export(data):
    raw = base64.b64decode(data["archive_base64"], validate=True)
    assert len(raw) == data["size_bytes"]
    assert hashlib.sha256(raw).hexdigest() == data["sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files.pop("manifest.json"))
    Draft202012Validator(
        {"$ref": f"{OPENAPI_URI}#/components/schemas/StudentMediaArchiveManifest"},
        registry=_registry(),
        format_checker=_FORMAT_CHECKER,
    ).validate(manifest)
    assert manifest["owner_id"] == data["owner_id"]
    assert manifest["history_complete"] is False
    assert manifest["consistent_snapshot"] is False
    return manifest, files


def test_media_export_downloads_only_owned_student_files_and_preserves_unuploaded_states(
    onboarded, scans, new_student, clock, monkeypatch
):
    from datetime import timedelta

    own = uploaded(onboarded)
    other = new_student()
    foreign = uploaded(other)
    store = scans.state.media_store
    image = png_image()
    reserved = onboarded.data(
        "POST",
        "/scans/uploads",
        json=dict(
            purpose="scan",
            mime="image/png",
            size_bytes=len(image),
            sha256=hashlib.sha256(image).hexdigest(),
        ),
        expect=201,
    )["media_id"]
    pending = store.stage(
        owner=onboarded.user_id,
        purpose="handwriting",
        data=b"draft",
        now=clock.now(),
        expires_at=clock.now() + timedelta(minutes=1),
    )
    review = store.stage(
        owner=onboarded.user_id,
        purpose="question_attachment",
        data=b"private-review",
        now=clock.now(),
        expires_at=clock.now() + timedelta(minutes=1),
    )
    store.confirm(review.id, owner=onboarded.user_id, sha256=review.sha256, now=clock.now())
    expired = store.stage(
        owner=onboarded.user_id,
        purpose="ocr_source",
        data=b"expired",
        now=clock.now() - timedelta(minutes=2),
        expires_at=clock.now() - timedelta(minutes=1),
    )
    deleted = store.stage(
        owner=onboarded.user_id,
        purpose="ocr_source",
        data=b"deleted",
        now=clock.now(),
        expires_at=clock.now() + timedelta(minutes=1),
    )
    store.delete(deleted.id, owner=onboarded.user_id, now=clock.now())
    before = {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()}

    def forbidden(**kwargs):
        pytest.fail("Export must not clean storage")

    monkeypatch.setattr(store, "cleanup", forbidden)
    response = onboarded.get(MEDIA_EXPORT_PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["scope"] == "server_current_student_media"
    assert data["owner_id"] == onboarded.user_id
    assert data["objects_count"] == 3 and data["files_count"] == 1
    manifest, files = unpack_media_export(data)
    assert files == {f"media/{own}.png": image}
    by_id = {row["media_id"]: row for row in manifest["objects"]}
    assert set(by_id) == {own, reserved, pending.id}
    assert by_id[own]["availability"] == "included"
    assert by_id[reserved]["availability"] == "not_uploaded"
    assert by_id[pending.id]["availability"] == "awaiting_confirmation"
    assert by_id[reserved]["file_name"] is None
    raw = json.dumps(manifest)
    assert all(
        secret not in raw
        for secret in (
            foreign,
            other.user_id,
            review.id,
            expired.id,
            deleted.id,
            onboarded.token,
            "object_key",
            "upload_url",
            str(store.root),
        )
    )
    assert {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()} == before


def test_media_export_disabled_is_not_false_empty(student):
    assert student.get(MEDIA_EXPORT_PATH).status_code == 501


def test_media_export_enabled_empty_contains_explicit_scope(student, scans):
    data = student.data("GET", MEDIA_EXPORT_PATH)
    manifest, files = unpack_media_export(data)
    assert data["objects_count"] == data["files_count"] == 0
    assert manifest["objects"] == [] and files == {}


def test_media_export_role_precedes_query_and_storage_checks(student, parent, reviewer, client):
    assert client.get("/api/v1" + MEDIA_EXPORT_PATH).status_code == 401
    for actor in (parent, reviewer):
        response = actor.get(MEDIA_EXPORT_PATH, params={"student_id": student.user_id})
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
    assert student.get(MEDIA_EXPORT_PATH, params={"owner": student.user_id}).status_code == 422


@pytest.mark.parametrize("damage", ["bytes", "gone", "storage"])
def test_media_export_read_failure_is_whole_file_failure_without_private_error(
    onboarded, scans, monkeypatch, damage
):
    from tutor_api.blob_store import BlobNotFound, BlobStorageUnavailable

    uploaded(onboarded)
    store = scans.state.media_store
    before = {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()}

    def broken(*args, **kwargs):
        if damage == "bytes":
            return b"private-invalid-bytes"
        raise (BlobNotFound if damage == "gone" else BlobStorageUnavailable)(
            "private-storage-error"
        )

    monkeypatch.setattr(store, "read", broken)
    response = onboarded.get(MEDIA_EXPORT_PATH)
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert "data" not in response.json() and "private-" not in response.text
    assert {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()} == before


def test_media_export_rechecks_expiry_after_listing(onboarded, scans, monkeypatch, clock):
    uploaded(onboarded)
    store = scans.state.media_store
    original = store.list_owned

    def delayed(**kwargs):
        result = original(**kwargs)
        clock.advance(seconds=7201)
        return result

    monkeypatch.setattr(store, "list_owned", delayed)
    response = onboarded.get(MEDIA_EXPORT_PATH)
    assert response.status_code == 503 and "data" not in response.json()


@pytest.mark.parametrize("limit", ["archive", "objects"])
def test_media_export_limits_never_return_partial_archive(onboarded, scans, monkeypatch, limit):
    from tutor_api.services import student_media_export

    uploaded(onboarded)
    uploaded(onboarded)
    monkeypatch.setattr(
        student_media_export, "MAX_ARCHIVE_BYTES" if limit == "archive" else "MAX_OBJECTS", 1
    )
    response = onboarded.get(MEDIA_EXPORT_PATH)
    assert response.status_code == 413 and "data" not in response.json()


@pytest.mark.parametrize("damage", ["owner", "path", "state", "duplicate", "metadata"])
def test_media_export_rejects_invalid_listing_before_creating_archive(
    onboarded, scans, monkeypatch, damage
):
    from dataclasses import replace

    uploaded(onboarded)
    store = scans.state.media_store
    blob, state = store.list_owned(owner=onboarded.user_id, now=scans.state.clock(), limit=10)[0]
    if damage == "owner":
        blob = replace(blob, owner="private-other-owner")
        state = "reserved"
    elif damage == "path":
        blob = replace(blob, id="../private-path")
    elif damage == "state":
        state = "private-invalid-state"
    elif damage == "metadata":
        blob, state = replace(blob, mime={"private-secret": "invalid-mime"}), "reserved"
    rows = [(blob, state)] * (2 if damage == "duplicate" else 1)
    monkeypatch.setattr(store, "list_owned", lambda **kwargs: rows)
    response = onboarded.get(MEDIA_EXPORT_PATH)
    assert response.status_code == 503 and "data" not in response.json()
    assert "private-" not in response.text


def test_media_export_manifest_bytes_count_toward_archive_limit(student, scans, monkeypatch):
    from tutor_api.services import student_media_export

    monkeypatch.setattr(student_media_export, "MAX_ARCHIVE_BYTES", 1)
    assert student.get(MEDIA_EXPORT_PATH).status_code == 413


def test_media_export_rejects_file_bytes_before_zip_write(onboarded, scans, monkeypatch):
    from tutor_api.services import student_media_export

    uploaded(onboarded)
    monkeypatch.setattr(student_media_export, "MAX_ARCHIVE_BYTES", 1)
    original = zipfile.ZipFile.writestr
    media_writes = []

    def bounded(self, name, data, *args, **kwargs):
        if name != "manifest.json":
            media_writes.append(name)
        return original(self, name, data, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", bounded)
    assert onboarded.get(MEDIA_EXPORT_PATH).status_code == 413
    assert not media_writes, "Oversized media reached ZIP before the byte limit check"


def test_stored_scan_export_is_owned_whitelisted_and_independent_of_expired_images(
    onboarded, scans, new_student, db, clock, monkeypatch
):
    from tutor_api.services import scan_service

    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    onboarded.data(
        "POST",
        f"/scans/{scan['id']}/confirm",
        json={
            "stem_text": "自编拍题文字保留",
            "expressions": [{"span_id": "s1", "latex": "2x+1", "confidence": None}],
        },
    )
    other = new_student()
    foreign = other.data("POST", "/scans", json={"media_id": uploaded(other)}, expect=202)
    row = db.get(ScanRecord, scan["id"])
    payload = dict(row.payload, api_key="private-scan-key", object_key="private-storage-path")
    payload.pop("mock_notice")
    payload["expressions"][0]["raw_prompt"] = "private-expression-prompt"
    row.payload = payload
    db.commit()
    before = [(r.id, r.media_id, r.expires_at, r.payload) for r in db.scalars(select(ScanRecord))]
    original_store = scans.state.media_store
    files = {p.name: p.read_bytes() for p in original_store.root.iterdir() if p.is_file()}
    clock.advance(seconds=7201)
    scans.state.settings.scan_mock_enabled = False
    scans.state.media_store = None

    def forbidden(*args, **kwargs):
        pytest.fail("Export must not clean, commit or require image storage")

    monkeypatch.setattr(scan_service, "store", forbidden)
    monkeypatch.setattr(scan_service, "cleanup", forbidden)
    result = onboarded.data("GET", EXPORT_PATH)["stored_scan_records"]
    assert len(result) == 1 and result[0]["scan"]["id"] == scan["id"]
    assert result[0]["scan"]["status"] == "confirmed"
    assert result[0]["scan"]["stem_text"] == "自编拍题文字保留"
    assert "mock_notice" not in result[0]["scan"]
    import json

    raw = json.dumps(result)
    assert all(
        s not in raw
        for s in (
            other.user_id,
            foreign["id"],
            "private-scan-key",
            "private-storage-path",
            "private-expression-prompt",
            "api_key",
            "object_key",
            "raw_prompt",
        )
    )
    db.expire_all()
    assert [
        (r.id, r.media_id, r.expires_at, r.payload) for r in db.scalars(select(ScanRecord))
    ] == before
    assert {p.name: p.read_bytes() for p in original_store.root.iterdir() if p.is_file()} == files


@pytest.mark.parametrize("damage", ["id", "status", "missing", "media_id", "confidence", "flag"])
def test_corrupt_scan_fails_whole_export_without_leaking_or_deleting(onboarded, scans, db, damage):
    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    row = db.get(ScanRecord, scan["id"])
    value = dict(row.payload)
    if damage == "id":
        value["id"] = new_id()
    elif damage == "status":
        value["status"] = "private-corrupt-status"
    elif damage == "missing":
        del value["confidence"]
    elif damage == "confidence":
        value["confidence"] = 2.0
    elif damage == "flag":
        value["low_confidence"] = "true"
    else:
        row.media_id = "private-invalid-media-path"
    row.payload = value
    db.commit()
    response = onboarded.get(EXPORT_PATH)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "export_unavailable"
    assert "data" not in response.json()
    assert "private-" not in response.text
    db.expire_all()
    assert db.get(ScanRecord, scan["id"]).payload == value


def test_stored_scans_count_toward_export_limit(onboarded, scans, monkeypatch):
    from tutor_api.services import student_learning_export

    for _ in range(2):
        onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    monkeypatch.setattr(student_learning_export, "MAX_RECORDS", 1)
    assert onboarded.get(EXPORT_PATH).status_code == 413


def test_local_empty_scan_range_is_provided_even_when_scan_feature_is_disabled(student):
    assert student.data("GET", EXPORT_PATH)["stored_scan_records"] == []


@pytest.fixture
def scans(app, tmp_path):
    from tutor_api.blob_store import FilesystemBlobStore

    app.state.settings.scan_mock_enabled = True
    app.state.media_store = FilesystemBlobStore(tmp_path / "scan-blobs", max_bytes=10485760)
    return app


def uploaded(who):
    data = png_image()
    media = who.data(
        "POST",
        "/scans/uploads",
        json={
            "purpose": "scan",
            "mime": "image/png",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        expect=201,
    )
    who.data(
        "PUT",
        f"/scans/uploads/{media['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
    )
    return media["media_id"]


def test_scan_export_uses_original_snapshot_during_concurrent_confirmation(onboarded, scans):
    from sqlalchemy import event

    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    changed = []
    engine = scans.state.session_factory.kw["bind"]

    def another_device(connection, cursor, sql, parameters, context, many):
        if changed or "FROM study_sessions" not in sql:
            return
        changed.append(True)
        onboarded.data(
            "POST",
            f"/scans/{scan['id']}/confirm",
            json={"stem_text": "自编并发确认文字", "expressions": []},
        )

    event.listen(engine, "after_cursor_execute", another_device)
    try:
        records = onboarded.data("GET", EXPORT_PATH)["stored_scan_records"]
    finally:
        event.remove(engine, "after_cursor_execute", another_device)
    assert changed
    assert records[0]["scan"]["status"] == "needs_confirmation"
    assert records[0]["scan"]["stem_text"] == ""
    current = onboarded.data("GET", EXPORT_PATH)["stored_scan_records"]
    assert current[0]["scan"]["status"] == "confirmed"
    assert current[0]["scan"]["stem_text"] == "自编并发确认文字"


def test_empty_mock_confirm_and_expiry(onboarded, new_student, scans, clock):
    who = onboarded
    media_id = uploaded(who)
    scan = who.data("POST", "/scans", json={"media_id": media_id}, expect=202)
    assert scan["stem_text"] == "" and scan["confidence"] is None
    assert "未实际识别" in scan["mock_notice"]
    assert scan["matched_question_id"] is None
    other = new_student()
    other.error("GET", f"/scans/{scan['id']}", expect=404)
    result = who.data(
        "POST",
        f"/scans/{scan['id']}/confirm",
        json={"stem_text": "不存在的自编题", "expressions": []},
    )
    assert result["question_id"] is None and result["draft_question_id"] is None
    clock.advance(seconds=7201)
    who.error("GET", f"/scans/{scan['id']}", expect=404)
    assert not list(scans.state.media_store.root.glob("*.bin"))


def test_student_upload_does_not_open_review_media(onboarded, scans):
    onboarded.error(
        "POST",
        "/media/uploads",
        json={"purpose": "scan", "mime": "image/png", "size_bytes": 1, "sha256": "0" * 64},
        expect=403,
    )


def test_scan_default_disabled(onboarded):
    onboarded.error(
        "POST", "/scans", json={"media_id": "00000000-0000-0000-0000-000000000000"}, expect=501
    )


def test_unique_published_match_and_replay(onboarded, scans):
    from sqlalchemy import select

    from tutor_api.models import Question, QuestionVersion

    with scans.state.session_factory() as db:
        question = db.scalar(
            select(Question).where(
                Question.status == "published", Question.source_type == "self_authored"
            )
        )
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == question.id,
                QuestionVersion.version == question.version,
            )
        )
        stem, expected = version.content_json["stem"], question.id
    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    body = {"stem_text": stem, "expressions": []}
    path = f"/scans/{scan['id']}/confirm"
    first = onboarded.data("POST", path, json=body, key="confirm-replay")
    assert first["question_id"] == expected
    assert onboarded.data("POST", path, json=body, key="confirm-replay") == first
    onboarded.error(
        "POST", path, json={**body, "stem_text": "different"}, key="confirm-replay", expect=409
    )
    with scans.state.session_factory() as db:
        row = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id != expected))
        question = db.get(Question, row.question_id)
        question.status = "published"
        row = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == question.id,
                QuestionVersion.version == question.version,
            )
        )
        row.content_json = {**row.content_json, "stem": stem}
        db.commit()
    second = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    assert (
        onboarded.data("POST", f"/scans/{second['id']}/confirm", json=body)["question_id"] is None
    )


def test_scan_upload_permissions_and_incomplete(onboarded, reviewer, new_student, scans):
    data = png_image()
    body = {
        "purpose": "scan",
        "mime": "image/png",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    reviewer.error("POST", "/scans/uploads", json=body, expect=403)
    media = onboarded.data("POST", "/scans/uploads", json=body, expect=201, key="reserve-replay")
    assert (
        onboarded.data("POST", "/scans/uploads", json=body, expect=201, key="reserve-replay")
        == media
    )
    onboarded.error("POST", "/scans", json={"media_id": media["media_id"]}, expect=404)
    new_student().error(
        "PUT",
        f"/scans/uploads/{media['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
        expect=404,
    )
    onboarded.error(
        "POST", "/scans/uploads", json={**body, "purpose": "question_attachment"}, expect=422
    )


def test_confirm_once_and_original_expiry(onboarded, scans, clock):
    from sqlalchemy import select

    from tutor_api.scan_models import ScanRecord

    media_id = uploaded(onboarded)
    clock.advance(seconds=7000)
    scan = onboarded.data(
        "POST", "/scans", json={"media_id": media_id}, expect=202, key="original-scan"
    )
    path = f"/scans/{scan['id']}/confirm"
    body = {"stem_text": "学生手工录入", "expressions": []}
    onboarded.data("POST", path, json=body, key="first-confirm")
    onboarded.error("POST", path, json=body, key="second-confirm", expect=409)
    clock.advance(seconds=201)
    onboarded.error("POST", path, json=body, key="first-confirm", expect=404)
    onboarded.error("POST", "/scans", json={"media_id": media_id}, key="original-scan", expect=404)
    with scans.state.session_factory() as db:
        assert db.scalar(select(ScanRecord)) is None
    assert not list(scans.state.media_store.root.glob("*.json"))


def test_expressions_disable_automatic_match(onboarded, scans):
    from sqlalchemy import select

    from tutor_api.models import Question, QuestionVersion

    with scans.state.session_factory() as db:
        stem = db.scalar(
            select(QuestionVersion)
            .join(
                Question,
                (Question.id == QuestionVersion.question_id)
                & (Question.version == QuestionVersion.version),
            )
            .where(Question.status == "published", Question.source_type == "self_authored")
        ).content_json["stem"]
    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    result = onboarded.data(
        "POST",
        f"/scans/{scan['id']}/confirm",
        json={
            "stem_text": stem,
            "expressions": [{"span_id": "manual", "latex": "x=999", "confidence": None}],
        },
    )
    assert result["question_id"] is None


def test_startup_physically_cleans_expired_scans(onboarded, scans, clock):
    from sqlalchemy import select
    from starlette.testclient import TestClient

    from support.api import LOOPBACK
    from tutor_api.main import create_app
    from tutor_api.scan_models import ScanRecord

    uploaded_id = uploaded(onboarded)
    onboarded.data("POST", "/scans", json={"media_id": uploaded_id}, expect=202)
    clock.advance(seconds=7201)
    restarted = create_app(
        scans.state.settings, clock=clock.now, media_store=scans.state.media_store
    )
    with TestClient(restarted, client=LOOPBACK):
        with restarted.state.session_factory() as db:
            assert db.scalar(select(ScanRecord)) is None
        assert not list(scans.state.media_store.root.glob("*.json"))


def test_stale_confirmation_cannot_overwrite_first(onboarded, scans, monkeypatch):
    from tutor_api.scan_models import ScanRecord
    from tutor_api.services import scan_service

    scan = onboarded.data("POST", "/scans", json={"media_id": uploaded(onboarded)}, expect=202)
    with scans.state.session_factory() as db:
        stale = db.get(ScanRecord, scan["id"])
        db.expunge(stale)
    path = f"/scans/{scan['id']}/confirm"
    onboarded.data("POST", path, json={"stem_text": "先确认的题干", "expressions": []})
    with monkeypatch.context() as scoped:
        scoped.setattr(scan_service, "owned", lambda ctx, id: stale)
        onboarded.error(
            "POST", path, json={"stem_text": "延迟提交的旧读取", "expressions": []}, expect=409
        )
    assert onboarded.data("GET", f"/scans/{scan['id']}")["stem_text"] == "先确认的题干"


def test_temporary_read_never_unlocks_review_attachments(tmp_path):
    from datetime import UTC, datetime, timedelta

    from tutor_api.blob_store import BlobNotFound, FilesystemBlobStore, InMemoryBlobStore

    now = datetime(2026, 11, 16, tzinfo=UTC)
    for store in [
        InMemoryBlobStore(max_bytes=1024),
        FilesystemBlobStore(tmp_path / "blobs", max_bytes=1024),
    ]:
        for purpose in ["ocr_source", "question_attachment"]:
            item = store.reserve(
                owner="student",
                purpose=purpose,
                mime="image/png",
                size_bytes=1,
                sha256=hashlib.sha256(b"x").hexdigest(),
                expires_at=now + timedelta(seconds=60),
                now=now,
            )
            store.put(item.id, owner="student", data=b"x", now=now)
            with pytest.raises(BlobNotFound):
                store.read(item.id, owner="student", now=now)
            if purpose == "ocr_source":
                assert store.read(item.id, owner="student", now=now, temporary=True) == b"x"
                with pytest.raises(BlobNotFound):
                    store.read(
                        item.id, owner="student", now=now + timedelta(seconds=60), temporary=True
                    )
            else:
                with pytest.raises(BlobNotFound):
                    store.read(item.id, owner="student", now=now, temporary=True)


def test_memory_temporary_read_rejects_corrupt_payload():
    from datetime import UTC, datetime, timedelta

    from tutor_api.blob_store import BlobNotFound, InMemoryBlobStore

    now = datetime(2026, 11, 16, tzinfo=UTC)
    store = InMemoryBlobStore(max_bytes=1024)
    item = store.reserve(
        owner="student",
        purpose="ocr_source",
        mime="image/png",
        size_bytes=1,
        sha256=hashlib.sha256(b"x").hexdigest(),
        expires_at=now + timedelta(seconds=60),
        now=now,
    )
    with pytest.raises(BlobNotFound):
        store.read(item.id, owner="student", now=now, temporary=True)
    store.put(item.id, owner="student", data=b"x", now=now)
    store._entries[item.id] = (item, b"y", "pending")
    with pytest.raises(BlobNotFound):
        store.read(item.id, owner="student", now=now, temporary=True)


@pytest.mark.parametrize("kind", ["memory", "filesystem"])
def test_api_rejects_unuploaded_or_invalid_image(onboarded, scans, kind):
    from tutor_api.blob_store import InMemoryBlobStore

    if kind == "memory":
        scans.state.media_store = InMemoryBlobStore(max_bytes=10485760)
    data = png_image()
    media = onboarded.data(
        "POST",
        "/scans/uploads",
        expect=201,
        json={
            "purpose": "scan",
            "mime": "image/png",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    onboarded.error("POST", "/scans", json={"media_id": media["media_id"]}, expect=404)
    onboarded.error(
        "PUT",
        f"/scans/uploads/{media['media_id']}/content",
        json={"content_base64": base64.b64encode(data + b"corruption").decode()},
        expect=422,
    )
    onboarded.error("POST", "/scans", json={"media_id": media["media_id"]}, expect=404)


def test_private_scan_headers_include_errors_and_replay(onboarded, scans):
    media_id = uploaded(onboarded)
    for _ in range(2):
        response = onboarded.request(
            "POST", "/scans", json={"media_id": media_id}, key="scan-headers"
        )
        assert response.status_code == 202
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
    response = onboarded.request("POST", "/scans", json={})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    scans.state.settings.scan_mock_enabled = False
    response = onboarded.request("POST", "/scans", json={})
    assert response.status_code == 501
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("kind", ["memory", "filesystem"])
def test_upload_expiring_after_image_validation_returns_private_404(
    onboarded, scans, clock, monkeypatch, kind
):
    from tutor_api.blob_store import InMemoryBlobStore
    from tutor_api.services import media_service

    if kind == "memory":
        scans.state.media_store = InMemoryBlobStore(max_bytes=10485760)
    data = png_image()
    media = onboarded.data(
        "POST",
        "/scans/uploads",
        expect=201,
        json={
            "purpose": "scan",
            "mime": "image/png",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    validate = media_service.validate_static_image

    def expire_after_validation(*args):
        validate(*args)
        clock.advance(seconds=7201)

    monkeypatch.setattr(media_service, "validate_static_image", expire_after_validation)
    response = onboarded.request(
        "PUT",
        f"/scans/uploads/{media['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
