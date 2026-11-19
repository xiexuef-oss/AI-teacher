import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from tutor_api.blob_store import BlobNotFound, FilesystemBlobStore


def test_filesystem_restart_staging_integrity_owner_and_delete(tmp_path):
    now = datetime(2026, 11, 15, tzinfo=UTC)
    data = b"self-authored-test"
    digest = hashlib.sha256(data).hexdigest()
    store = FilesystemBlobStore(tmp_path, max_bytes=100)
    blob = store.reserve(
        owner="a",
        purpose="question_attachment",
        mime="image/png",
        size_bytes=len(data),
        sha256=digest,
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    with pytest.raises(BlobNotFound):
        store.read(blob.id, owner="a", now=now)
    with pytest.raises(ValueError):
        store.confirm(blob.id, owner="a", sha256=digest, now=now)
    with pytest.raises(ValueError):
        store.put(blob.id, owner="a", data=b"wrong", now=now)
    store.put(blob.id, owner="a", data=data, now=now)
    restarted = FilesystemBlobStore(tmp_path, max_bytes=100)
    with pytest.raises(BlobNotFound):
        restarted.confirm(blob.id, owner="b", sha256=digest, now=now)
    restarted.confirm(blob.id, owner="a", sha256=digest, now=now)
    assert restarted.read(blob.id, owner="a", now=now) == data
    restarted.delete(blob.id, owner="a", now=now)
    restarted.delete(blob.id, owner="a", now=now)
    with pytest.raises(BlobNotFound):
        store.read(blob.id, owner="a", now=now)
    assert store.cleanup(now=now + timedelta(minutes=1)) == 1


def test_filesystem_paths_expiry_and_orphan_recovery(tmp_path):
    now = datetime(2026, 11, 15, tzinfo=UTC)
    store = FilesystemBlobStore(tmp_path, max_bytes=4)
    store.stage(
        owner="a",
        purpose="question_attachment",
        data=b"test",
        expires_at=now + timedelta(seconds=1),
        now=now,
    )
    with pytest.raises(BlobNotFound):
        store.stat("../escape", owner="a", now=now)
    restarted = FilesystemBlobStore(tmp_path, max_bytes=4)
    assert restarted.cleanup(now=now + timedelta(seconds=1)) == 1
    assert not list(tmp_path.glob("*.bin"))


def test_cleanup_only_removes_controlled_orphans_and_old_atomic_temps(tmp_path):
    import os
    from uuid import uuid4

    now = datetime(2026, 11, 15, tzinfo=UTC)
    store = FilesystemBlobStore(tmp_path, max_bytes=100, temporary_ttl_seconds=60)
    orphan = tmp_path / f"{uuid4()}.bin"
    temporary = tmp_path / ".media-interrupted"
    unrelated = tmp_path / "other.bin"
    for path in (orphan, temporary, unrelated):
        path.write_bytes(b"orphan")
        os.utime(path, (now.timestamp() - 120, now.timestamp() - 120))
    store.cleanup(now=now)
    assert not orphan.exists() and not temporary.exists()
    assert unrelated.exists()


def test_two_store_instances_share_deletion_state_under_thread_contention(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    now = datetime(2026, 11, 15, tzinfo=UTC)
    first = FilesystemBlobStore(tmp_path, max_bytes=100)
    second = FilesystemBlobStore(tmp_path, max_bytes=100)
    blob = first.stage(
        owner="a",
        purpose="question_attachment",
        data=b"fixture",
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    first.confirm(blob.id, owner="a", sha256=blob.sha256, now=now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda store: store.delete(blob.id, owner="a", now=now), (first, second)))
    with pytest.raises(BlobNotFound):
        first.read(blob.id, owner="a", now=now)
