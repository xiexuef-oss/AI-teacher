"""Explicit, loopback-only S3 service tests. No production bucket is accepted implicitly."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from tutor_api.blob_store import BlobNotFound
from tutor_api.s3_blob_store import BlobWriteConflict, S3BlobStore, local_s3_client


@pytest.fixture
def storage():
    path = os.environ.get("TUTOR_S3_BLOB_TEST_CONFIG")
    if not path:
        pytest.skip("Explicit isolated S3 test configuration required")
    pytest.importorskip("boto3")
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    assert config.get("test_only") is True
    client = local_s3_client(
        **{key: config[key] for key in ("endpoint", "region", "access_key", "secret_key")}
    )
    prefix = "tutor-tests/" + uuid4().hex + "/"
    store = S3BlobStore(client, bucket=config["bucket"], prefix=prefix, max_bytes=4096)
    try:
        yield client, config["bucket"], prefix, store
    finally:
        page = client.list_objects_v2(Bucket=config["bucket"], Prefix=prefix)
        for item in page.get("Contents", []):
            assert item["Key"].startswith(prefix)
            client.delete_object(Bucket=config["bucket"], Key=item["Key"], IfMatch=item["ETag"])
        client.close()


def test_real_service_owner_confirmation_restart_instance_and_expiry(storage):
    client, bucket, prefix, first = storage
    now = datetime.now(UTC)
    blob = first.stage(
        owner="self-authored-owner",
        purpose="ocr_source",
        data=b"self-authored image stand-in",
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    second = S3BlobStore(client, bucket=bucket, prefix=prefix, max_bytes=4096)
    with pytest.raises(BlobNotFound):
        second.read(blob.id, owner="another-owner", now=now, temporary=True)
    assert (
        second.read(blob.id, owner="self-authored-owner", now=now, temporary=True)
        == b"self-authored image stand-in"
    )
    second.confirm(blob.id, owner="self-authored-owner", sha256=blob.sha256, now=now)
    assert (
        first.read(blob.id, owner="self-authored-owner", now=now) == b"self-authored image stand-in"
    )
    assert second.cleanup(now=now + timedelta(minutes=1)) == 1
    with pytest.raises(BlobNotFound):
        first.read(blob.id, owner="self-authored-owner", now=now)


def test_real_service_owned_listing_spans_pages_is_read_only_and_has_independent_cursor(storage):
    from tutor_api.blob_store import BlobListingTooLarge

    client, bucket, prefix, first = storage
    now = datetime.now(UTC)
    expected = {
        first.stage(
            owner="a",
            purpose="ocr_source",
            data=b"self-authored enumeration",
            expires_at=now + timedelta(minutes=5),
            now=now,
        ).id
        for _ in range(103)
    }
    first.stage(
        owner="b",
        purpose="ocr_source",
        data=b"other owner",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    before = {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix)["Contents"]
    }

    class ObservePages:
        def __init__(self):
            self.pages = []

        def __getattr__(self, name):
            return getattr(client, name)

        def list_objects_v2(self, **kwargs):
            self.pages.append(kwargs)
            return client.list_objects_v2(**kwargs)

    observer = ObservePages()
    restarted = S3BlobStore(observer, bucket=bucket, prefix=prefix, max_bytes=4096)
    restarted._cleanup_cursor = "not-an-export-cursor"
    rows = restarted.list_owned(owner="a", now=now, limit=110)
    assert {blob.id for blob, _ in rows} == expected
    assert {state for _, state in rows} == {"pending"}
    assert len(observer.pages) == 2
    assert "ContinuationToken" not in observer.pages[0]
    assert observer.pages[1]["ContinuationToken"]
    assert restarted._cleanup_cursor == "not-an-export-cursor"
    with pytest.raises(BlobListingTooLarge):
        restarted.list_owned(owner="a", now=now, limit=10)
    after = {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix)["Contents"]
    }
    assert before == after


def test_real_service_student_media_archive_uses_owned_s3_bytes_without_links(
    storage, app, student
):
    import base64
    import hashlib
    import io
    import zipfile

    from support.documents import png_image

    client, bucket, prefix, store = storage
    app.state.media_store = store
    now = app.state.clock()
    image = png_image()
    owned = store.reserve(
        owner=student.user_id,
        purpose="ocr_source",
        mime="image/png",
        size_bytes=len(image),
        sha256=hashlib.sha256(image).hexdigest(),
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    store.put(owned.id, owner=student.user_id, data=image, now=now)
    foreign = store.stage(
        owner="another-owner",
        purpose="ocr_source",
        data=b"private-other-image",
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    before = {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix)["Contents"]
    }
    result = student.data("GET", "/profile/media-export")
    content = base64.b64decode(result["archive_base64"], validate=True)
    assert hashlib.sha256(content).hexdigest() == result["sha256"]
    assert len(content) == result["size_bytes"]
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert set(archive.namelist()) == {"manifest.json", f"media/{owned.id}.png"}
        assert archive.read(f"media/{owned.id}.png") == image
        manifest = archive.read("manifest.json").decode()
        assert (
            foreign.id not in manifest and prefix not in manifest and "object_key" not in manifest
        )
    assert before == {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix)["Contents"]
    }


def test_real_service_eight_stale_writers_only_one_wins_and_delete_cannot_revive(storage):
    client, bucket, prefix, first = storage
    now = datetime.now(UTC)
    blob = first.stage(
        owner="a",
        purpose="ocr_source",
        data=b"self-authored concurrency",
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    barrier = Barrier(8)

    class GateClient:
        def __getattr__(self, name):
            return getattr(client, name)

        def put_object(self, **kwargs):
            if kwargs["Key"].endswith(blob.id + ".json") and "IfMatch" in kwargs:
                barrier.wait(timeout=15)
            return client.put_object(**kwargs)

    stores = [
        S3BlobStore(GateClient(), bucket=bucket, prefix=prefix, max_bytes=4096) for _ in range(8)
    ]

    def confirm(store):
        try:
            store.confirm(blob.id, owner="a", sha256=blob.sha256, now=now)
            return True
        except BlobWriteConflict:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(confirm, stores)).count(True) == 1
    first.delete(blob.id, owner="a", now=now)
    for store in stores:
        with pytest.raises(BlobNotFound):
            store.confirm(blob.id, owner="a", sha256=blob.sha256, now=now)


def test_real_service_http_injection_replay_and_application_restart(storage, settings, clock):
    import base64
    import hashlib

    from starlette.testclient import TestClient

    from support.api import LOOPBACK, ApiClient
    from support.documents import png_image
    from tutor_api.main import create_app

    client, bucket, prefix, store = storage
    app = create_app(settings, clock=clock.now, media_store=store)
    assert app.state.media_store is store
    data = png_image()
    digest = hashlib.sha256(data).hexdigest()
    with TestClient(app, client=LOOPBACK) as raw:
        identity = ApiClient(raw).data(
            "POST",
            "/dev/local-identities",
            params={"role": "reviewer"},
            expect=201,
            auth=False,
            key=False,
        )
        reviewer = ApiClient(raw, token=identity["access_token"])
        payload = {
            "purpose": "question_attachment",
            "mime": "image/png",
            "size_bytes": len(data),
            "sha256": digest,
        }
        created = reviewer.data(
            "POST", "/media/uploads", json=payload, key="real-s3-upload", expect=201
        )
        replay = reviewer.data(
            "POST", "/media/uploads", json=payload, key="real-s3-upload", expect=201
        )
        assert replay == created
        media_id = created["media_id"]
        reviewer.data(
            "PUT",
            f"/media/{media_id}/content",
            json={"content_base64": base64.b64encode(data).decode()},
        )
        reviewer.data(
            "POST", f"/media/{media_id}/confirm", json={"sha256": digest}, key="real-s3-confirm"
        )
        other = ApiClient(raw).data(
            "POST",
            "/dev/local-identities",
            params={"role": "reviewer"},
            expect=201,
            auth=False,
            key=False,
        )
        stranger = ApiClient(raw, token=other["access_token"])
        stranger.error("GET", f"/media/{media_id}/content", expect=404)
        stranger.error("POST", f"/media/{media_id}/confirm", json={"sha256": digest}, expect=404)
    restored = S3BlobStore(client, bucket=bucket, prefix=prefix, max_bytes=4096)
    app = create_app(settings, clock=clock.now, media_store=restored)
    with TestClient(app, client=LOOPBACK) as raw:
        reviewer = ApiClient(raw, token=identity["access_token"])
        assert reviewer.data("GET", f"/media/{media_id}/content")["content_base64"] == (
            base64.b64encode(data).decode()
        )
        reviewer.data(
            "POST", f"/media/{media_id}/confirm", json={"sha256": digest}, key="real-s3-confirm"
        )
        reviewer.data("POST", f"/media/{media_id}/delete", json={}, key="real-s3-delete")
        reviewer.data("POST", f"/media/{media_id}/delete", json={}, key="real-s3-delete")
        reviewer.error("GET", f"/media/{media_id}/content", expect=404)
