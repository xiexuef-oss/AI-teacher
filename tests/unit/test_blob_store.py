import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from tutor_api.blob_store import BlobNotFound, InMemoryBlobStore


def test_staging_confirmation_owner_isolation_and_idempotent_delete():
    now = datetime(2026, 11, 15, tzinfo=UTC)
    store = InMemoryBlobStore(max_bytes=100)
    blob = store.stage(
        owner="student-a",
        purpose="ocr_source",
        data=b"self authored",
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    with pytest.raises(BlobNotFound):
        store.read(blob.id, owner="student-a", now=now)
    with pytest.raises(BlobNotFound):
        store.confirm(blob.id, owner="student-b", sha256=blob.sha256, now=now)
    with pytest.raises(ValueError):
        store.confirm(blob.id, owner="student-a", sha256="0" * 64, now=now)
    assert (
        store.confirm(blob.id, owner="student-a", sha256=blob.sha256, now=now).sha256
        == hashlib.sha256(b"self authored").hexdigest()
    )
    assert store.read(blob.id, owner="student-a", now=now) == b"self authored"
    store.delete(blob.id, owner="student-a", now=now)
    store.delete(blob.id, owner="student-a", now=now)
    with pytest.raises(BlobNotFound):
        store.read(blob.id, owner="student-a", now=now)


def test_expiry_cleanup_and_input_bounds():
    now = datetime(2026, 11, 15, tzinfo=UTC)
    store = InMemoryBlobStore(max_bytes=4)
    with pytest.raises(ValueError):
        store.stage(
            owner="a",
            purpose="ocr_source",
            data=b"large",
            expires_at=now + timedelta(seconds=1),
            now=now,
        )
    blob = store.stage(
        owner="a",
        purpose="ocr_source",
        data=b"test",
        expires_at=now + timedelta(seconds=1),
        now=now,
    )
    with pytest.raises(BlobNotFound):
        store.confirm(blob.id, owner="a", sha256=blob.sha256, now=now + timedelta(seconds=1))
    assert store.cleanup(now=now + timedelta(seconds=1)) == 1
