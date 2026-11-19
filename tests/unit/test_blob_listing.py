import copy
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_s3_blob_store import FakeS3, S3Error

from tutor_api.blob_store import BlobStorageUnavailable, FilesystemBlobStore, InMemoryBlobStore
from tutor_api.s3_blob_store import S3BlobStore

NOW = datetime(2026, 11, 17, tzinfo=UTC)


class TrackedBody(io.BytesIO):
    reads = 0

    def read(self, size=-1):
        self.reads += 1
        return super().read(size)


class PagedS3(FakeS3):
    def __init__(self):
        super().__init__()
        self.pages = []
        self.streams = []

    def get_object(self, **kwargs):
        result = super().get_object(**kwargs)
        original = result["Body"]
        result["Body"] = TrackedBody(original.getvalue())
        original.close()
        self.streams.append(result["Body"])
        return result

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, **kwargs):
        self.pages.append(dict(kwargs))
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(kwargs.get("ContinuationToken", "0"))
        end = min(start + min(MaxKeys, 2), len(keys))
        return dict(
            Contents=[{"Key": k} for k in keys[start:end]],
            IsTruncated=end < len(keys),
            **({"NextContinuationToken": str(end)} if end < len(keys) else {}),
        )


@pytest.fixture(params=["memory", "filesystem", "s3"])
def listing_store(request, tmp_path):
    if request.param == "memory":
        return InMemoryBlobStore(max_bytes=100)
    if request.param == "filesystem":
        return FilesystemBlobStore(tmp_path, max_bytes=100)
    return S3BlobStore(PagedS3(), bucket="engineering-test", prefix="media/", max_bytes=100)


def staged(store, owner="alice", *, now=NOW, expires=None):
    return store.stage(
        owner=owner,
        purpose="ocr_source",
        data=b"self-authored",
        now=now,
        expires_at=expires or now + timedelta(minutes=1),
    )


def snapshot(store):
    if isinstance(store, InMemoryBlobStore):
        return copy.deepcopy(store._entries)
    if isinstance(store, FilesystemBlobStore):
        return {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()}
    return copy.deepcopy(store.client.objects)


def test_listing_is_complete_owned_read_only_and_preserves_saved_states(listing_store):
    s = listing_store
    pending = staged(s)
    ready = staged(s)
    s.confirm(ready.id, owner="alice", sha256=ready.sha256, now=NOW)
    reserved = s.reserve(
        owner="alice",
        purpose="handwriting",
        mime="image/png",
        size_bytes=1,
        sha256="0" * 64,
        now=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    staged(s, "bob")
    staged(s, now=NOW - timedelta(minutes=2), expires=NOW - timedelta(minutes=1))
    deleted = staged(s)
    s.delete(deleted.id, owner="alice", now=NOW)
    before = snapshot(s)
    if isinstance(s, S3BlobStore):
        s._cleanup_cursor = "not-an-export-cursor"
    result = s.list_owned(owner="alice", now=NOW, limit=20)
    assert result == sorted(
        [(pending, "pending"), (ready, "ready"), (reserved, "reserved")], key=lambda row: row[0].id
    )
    assert snapshot(s) == before
    assert s.list_owned(owner="alice", now=NOW, limit=20) == result
    if isinstance(s, S3BlobStore):
        assert len(s.client.pages) == 6 and s.client.pages[0] == s.client.pages[3] == {}
        assert s._cleanup_cursor == "not-an-export-cursor"
        assert all(stream.closed for stream in s.client.streams)


def test_listing_limit_counts_foreign_entries_instead_of_returning_false_empty(listing_store):
    for _ in range(3):
        staged(listing_store, "bob")
    before = snapshot(listing_store)
    with pytest.raises(BlobStorageUnavailable, match="limit"):
        listing_store.list_owned(owner="alice", now=NOW, limit=2)
    assert snapshot(listing_store) == before


@pytest.mark.parametrize(
    "arguments",
    [
        dict(owner=None),
        dict(owner=""),
        dict(owner="a" * 257),
        dict(limit=0),
        dict(limit=True),
        dict(limit=10001),
        dict(now=NOW.replace(tzinfo=None)),
    ],
)
def test_listing_rejects_invalid_scope_and_bounds_before_storage(listing_store, arguments):
    with pytest.raises(ValueError):
        listing_store.list_owned(**(dict(owner="alice", now=NOW, limit=10) | arguments))


def test_empty_listing_is_read_only_without_cleanup(listing_store, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Listing must not clean or write")

    monkeypatch.setattr(listing_store, "cleanup", forbidden)
    assert listing_store.list_owned(owner="alice", now=NOW, limit=10) == []


def test_filesystem_bad_manifest_fails_whole_listing_without_leaking_or_deleting(tmp_path):
    s = FilesystemBlobStore(tmp_path, max_bytes=100)
    blob = staged(s, "bob")
    path = tmp_path / f"{blob.id}.json"
    path.write_text('{"private-secret":"broken"}', encoding="utf-8")
    before = snapshot(s)
    with pytest.raises(BlobStorageUnavailable) as caught:
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert "private-secret" not in str(caught.value)
    assert snapshot(s) == before


def test_filesystem_listing_bounds_metadata_bytes(tmp_path, monkeypatch):
    import tutor_api.blob_store as module

    s = FilesystemBlobStore(tmp_path, max_bytes=100)
    staged(s)
    monkeypatch.setattr(module, "LISTING_MAX_BYTES", 1)
    with pytest.raises(BlobStorageUnavailable, match="limit"):
        s.list_owned(owner="alice", now=NOW, limit=10)


@pytest.mark.parametrize(
    "damage", ["state", "size", "boolean", "mime", "id", "expiry", "duplicate"]
)
def test_filesystem_listing_rejects_invalid_metadata_instead_of_skipping(tmp_path, damage):
    s = FilesystemBlobStore(tmp_path, max_bytes=100)
    blob = staged(s)
    path = tmp_path / f"{blob.id}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if damage == "state":
        value["state"] = "unknown"
    elif damage == "size":
        value["blob"]["size_bytes"] = 0
    elif damage == "boolean":
        value["blob"]["size_bytes"] = True
    elif damage == "mime":
        value["blob"]["mime"] = {"private-secret": "not-a-mime"}
    elif damage == "id":
        value["blob"]["id"] = "not-a-uuid"
    elif damage == "expiry":
        value["blob"]["expires_at"] = NOW.replace(tzinfo=None).isoformat()
    raw = json.dumps(value)
    if damage == "duplicate":
        raw = raw[:-1] + ',"state":"ready"}'
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(BlobStorageUnavailable):
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert path.read_text(encoding="utf-8") == raw


def test_s3_listing_bounds_bytes_before_reading_body_and_closes_stream(monkeypatch):
    import tutor_api.s3_blob_store as module

    s = S3BlobStore(PagedS3(), bucket="engineering-test", prefix="media/", max_bytes=100)
    staged(s)
    monkeypatch.setattr(module, "LISTING_MAX_BYTES", 1)
    with pytest.raises(BlobStorageUnavailable, match="limit"):
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert s.client.streams[-1].closed
    assert s.client.streams[-1].reads == 0


@pytest.mark.parametrize(
    "page",
    [
        None,
        {"IsTruncated": True},
        {"Contents": [], "IsTruncated": "false"},
        {"Contents": [{"Key": "outside/private-secret.json"}], "IsTruncated": False},
    ],
)
def test_s3_invalid_listing_page_is_not_empty_success(page, monkeypatch):
    s = S3BlobStore(PagedS3(), bucket="engineering-test", prefix="media/", max_bytes=100)
    monkeypatch.setattr(s.client, "list_objects_v2", lambda **kwargs: page)
    with pytest.raises(BlobStorageUnavailable) as caught:
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert "private-secret" not in str(caught.value)


@pytest.mark.parametrize("damage", ["corrupt", "gone", "sdk_error"])
def test_s3_disappeared_or_corrupt_object_fails_whole_listing(monkeypatch, damage):
    s = S3BlobStore(PagedS3(), bucket="engineering-test", prefix="media/", max_bytes=100)
    blob = staged(s)
    if damage == "corrupt":
        s.client.objects[s._key(blob.id)] = (b'{"private-secret":"invalid"}', '"tag"')
    else:

        def unavailable(**kwargs):
            raise S3Error(404 if damage == "gone" else 503)

        monkeypatch.setattr(s.client, "get_object", unavailable)
    with pytest.raises(BlobStorageUnavailable) as caught:
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert "private-secret" not in str(caught.value)


@pytest.mark.parametrize("damage", ["cycle", "duplicate", "missing_token"])
def test_s3_pagination_anomalies_fail_without_looping_or_partial_success(monkeypatch, damage):
    s = S3BlobStore(PagedS3(), bucket="engineering-test", prefix="media/", max_bytes=100)
    first, second = staged(s), staged(s)
    pages = [dict(Contents=[{"Key": s._key(first.id)}], IsTruncated=True)]
    if damage != "missing_token":
        pages[0]["NextContinuationToken"] = "repeat"
        pages.append(
            dict(
                Contents=[{"Key": s._key(first.id if damage == "duplicate" else second.id)}],
                IsTruncated=damage == "cycle",
                NextContinuationToken="repeat",
            )
        )
    calls = []

    def listing(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= len(pages), "Pagination must terminate"
        return pages[len(calls) - 1]

    monkeypatch.setattr(s.client, "list_objects_v2", listing)
    with pytest.raises(BlobStorageUnavailable):
        s.list_owned(owner="alice", now=NOW, limit=10)
    assert len(calls) == len(pages)
