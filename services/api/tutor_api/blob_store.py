"""本地媒体适配：内存fake与受控文件系统；不联网，不表示生产对象存储接入。"""

import hashlib
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4


class BlobNotFound(LookupError):
    """不存在、非当前owner或过期使用同一错误。"""


class BlobWriteConflict(RuntimeError):
    """A conditional write did not replace the current object."""


class BlobStorageUnavailable(RuntimeError):
    """Storage outcome may be unknown; retry the original application intent."""


class BlobListingTooLarge(BlobStorageUnavailable):
    """A complete listing exceeded its work or byte limit; never return a partial list."""


LISTING_MAX_BYTES = 32 * 1024 * 1024


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate storage field")
        value[key] = item
    return value


def _listing_scope(owner, now, limit):
    if (
        not isinstance(owner, str)
        or not 0 < len(owner) <= 256
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or type(limit) is not int
        or not 1 <= limit <= 10_000
    ):
        raise ValueError("Explicit owner, timezone and bounded listing limit required")


def _listing_visible(blob, state, owner, now, max_bytes):
    try:
        valid = (
            str(UUID(blob.id)) == blob.id
            and isinstance(blob.owner, str)
            and 0 < len(blob.owner) <= 256
            and isinstance(blob.expires_at, datetime)
            and blob.expires_at.tzinfo is not None
            and blob.purpose
            in {"ocr_source", "handwriting", "question_attachment", "school_material"}
            and type(blob.size_bytes) is int
            and 0 < blob.size_bytes <= max_bytes
            and re.fullmatch(r"[0-9a-f]{64}", blob.sha256)
            and (blob.mime is None or isinstance(blob.mime, str) and len(blob.mime) <= 256)
            and state in {"reserved", "pending", "ready", "deleted"}
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise BlobStorageUnavailable("Invalid media manifest")
    return blob.owner == owner and blob.expires_at > now and state != "deleted"


@dataclass(frozen=True)
class Blob:
    id: str
    owner: str
    purpose: str
    size_bytes: int
    sha256: str
    expires_at: datetime
    mime: str | None = None


class BlobStore(Protocol):
    def list_owned(self, *, owner: str, now: datetime, limit: int) -> list[tuple[Blob, str]]:
        """Exhaust an owned metadata traversal or fail; limit counts all scanned objects.

        No cleanup, image read guarantee or cross-object S3 snapshot. No lifetime extension.
        """
        ...

    def reserve(
        self,
        *,
        owner: str,
        purpose: str,
        mime: str,
        size_bytes: int,
        sha256: str,
        expires_at: datetime,
        now: datetime,
    ) -> Blob: ...
    def put(self, blob_id: str, *, owner: str, data: bytes, now: datetime) -> Blob: ...
    def stat(self, blob_id: str, *, owner: str, now: datetime) -> Blob: ...
    def stage(
        self, *, owner: str, purpose: str, data: bytes, expires_at: datetime, now: datetime
    ) -> Blob: ...
    def confirm(self, blob_id: str, *, owner: str, sha256: str, now: datetime) -> Blob: ...
    def read(
        self, blob_id: str, *, owner: str, now: datetime, temporary: bool = False
    ) -> bytes: ...
    def delete(self, blob_id: str, *, owner: str, now: datetime) -> None: ...
    def cleanup(self, *, now: datetime) -> int: ...


class InMemoryBlobStore:
    def __init__(self, *, max_bytes: int):
        if max_bytes < 1:
            raise ValueError("max_bytes必须为正数")
        self.max_bytes = max_bytes
        self._entries = {}
        self._lock = RLock()

    def list_owned(self, *, owner, now, limit):
        _listing_scope(owner, now, limit)
        with self._lock:
            result = []
            for scanned, (blob, _, state) in enumerate(self._entries.values(), 1):
                if scanned > limit:
                    raise BlobListingTooLarge("Media listing exceeds limit")
                if _listing_visible(blob, state, owner, now, self.max_bytes):
                    result.append((blob, state))
            return sorted(result, key=lambda row: row[0].id)

    def reserve(self, *, owner, purpose, mime, size_bytes, sha256, expires_at, now):
        if (
            not owner
            or purpose
            not in {"question_attachment", "ocr_source", "handwriting", "school_material"}
            or not isinstance(size_bytes, int)
            or not 0 < size_bytes <= self.max_bytes
        ):
            raise ValueError("媒体归属、用途或大小无效")
        if (
            now.tzinfo is None
            or expires_at.tzinfo is None
            or expires_at <= now
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise ValueError("媒体有效期或摘要无效")
        blob = Blob(str(uuid4()), owner, purpose, size_bytes, sha256, expires_at, mime)
        with self._lock:
            self._entries[blob.id] = (blob, b"", "reserved")
        return blob

    def put(self, blob_id, *, owner, data, now):
        with self._lock:
            blob, _, state = self._owned(blob_id, owner, now)
            if state == "deleted":
                raise BlobNotFound()
            if (
                not isinstance(data, bytes)
                or len(data) != blob.size_bytes
                or hashlib.sha256(data).hexdigest() != blob.sha256
            ):
                raise ValueError("媒体大小或摘要不一致")
            self._entries[blob_id] = (blob, data, "ready" if state == "ready" else "pending")
            return blob

    def stat(self, blob_id, *, owner, now):
        with self._lock:
            blob, _, state = self._owned(blob_id, owner, now)
            if state == "deleted":
                raise BlobNotFound()
            return blob

    def stage(self, *, owner, purpose, data, expires_at, now):
        if now.tzinfo is None or expires_at.tzinfo is None or expires_at <= now:
            raise ValueError("必须明确有效期和时区")
        if not owner or purpose not in {
            "ocr_source",
            "handwriting",
            "question_attachment",
            "school_material",
        }:
            raise ValueError("owner或purpose无效")
        if not isinstance(data, bytes) or not data or len(data) > self.max_bytes:
            raise ValueError("媒体为空或超过大小上限")
        blob = Blob(
            str(uuid4()), owner, purpose, len(data), hashlib.sha256(data).hexdigest(), expires_at
        )
        with self._lock:
            self._entries[blob.id] = (blob, data, "pending")
        return blob

    def _owned(self, blob_id, owner, now):
        entry = self._entries.get(blob_id)
        if entry is None or entry[0].owner != owner or entry[0].expires_at <= now:
            raise BlobNotFound()
        return entry

    def confirm(self, blob_id, *, owner, sha256, now):
        with self._lock:
            blob, data, state = self._owned(blob_id, owner, now)
            if state == "deleted":
                raise BlobNotFound()
            if (
                state not in {"pending", "ready"}
                or len(data) != blob.size_bytes
                or sha256 != blob.sha256
            ):
                raise ValueError("媒体摘要不一致")
            self._entries[blob_id] = (blob, data, "ready")
            return blob

    def read(self, blob_id, *, owner, now, temporary=False):
        with self._lock:
            blob, data, state = self._owned(blob_id, owner, now)
            if state != "ready" and not (
                temporary
                and blob.purpose in {"ocr_source", "school_material"}
                and state == "pending"
            ):
                raise BlobNotFound()
            if len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.sha256:
                raise BlobNotFound()
            return data

    def delete(self, blob_id, *, owner, now):
        with self._lock:
            blob, _, _ = self._owned(blob_id, owner, now)
            self._entries[blob_id] = (blob, b"", "deleted")

    def cleanup(self, *, now):
        with self._lock:
            expired = [key for key, value in self._entries.items() if value[0].expires_at <= now]
            for key in expired:
                del self._entries[key]
            return len(expired)


class FilesystemBlobStore:
    """Local private files with durable manifests; no external storage calls."""

    def __init__(self, root, *, max_bytes, temporary_ttl_seconds=7200):
        from pathlib import Path

        if max_bytes < 1:
            raise ValueError("max_bytes必须为正数")
        root = Path(root)
        if root.is_symlink():
            raise ValueError("媒体目录不能为符号链接")
        if root.resolve() == Path(root.anchor or root.resolve().anchor):
            raise ValueError("媒体目录不能为文件系统根目录")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.temporary_ttl_seconds = temporary_ttl_seconds
        self._lock = RLock()

    def list_owned(self, *, owner, now, limit):
        import json

        _listing_scope(owner, now, limit)
        result, remaining = [], LISTING_MAX_BYTES
        try:
            with self._lock, self._disk_lock():
                # ponytail: bounded namespace scan; add an owner index if it outgrows this limit.
                for scanned, manifest in enumerate(self.root.glob("*.json"), 1):
                    if scanned > limit:
                        raise BlobListingTooLarge("Media listing exceeds limit")
                    self._paths(manifest.stem)
                    with manifest.open("rb") as stream:
                        raw = stream.read(min(8192, remaining) + 1)
                    if len(raw) > remaining:
                        raise BlobListingTooLarge("Media listing exceeds byte limit")
                    if len(raw) > 8192:
                        raise BlobStorageUnavailable("Invalid media manifest")
                    remaining -= len(raw)
                    value = json.loads(raw, object_pairs_hook=_unique)
                    if set(value) != {"blob", "state"}:
                        raise ValueError()
                    metadata = value["blob"]
                    metadata["expires_at"] = datetime.fromisoformat(metadata["expires_at"])
                    blob, state = Blob(**metadata), value["state"]
                    if blob.id != manifest.stem:
                        raise ValueError()
                    if _listing_visible(blob, state, owner, now, self.max_bytes):
                        result.append((blob, state))
            return sorted(result, key=lambda row: row[0].id)
        except BlobListingTooLarge:
            raise
        except Exception:
            raise BlobStorageUnavailable("Media listing unavailable") from None

    @contextmanager
    def _disk_lock(self):
        import os

        lock_path = self.root / ".lock"
        if lock_path.is_symlink():
            raise ValueError("媒体锁文件不能为符号链接")
        with lock_path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _paths(self, blob_id):
        from uuid import UUID

        try:
            if str(UUID(blob_id)) != blob_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise BlobNotFound() from None
        manifest, data = self.root / f"{blob_id}.json", self.root / f"{blob_id}.bin"
        if manifest.is_symlink() or data.is_symlink():
            raise BlobNotFound()
        return manifest, data

    def _atomic(self, path, content):
        import os
        import tempfile

        fd, temporary = tempfile.mkstemp(prefix=".media-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _save(self, blob, state):
        import json
        from dataclasses import asdict

        value = asdict(blob)
        value["expires_at"] = blob.expires_at.isoformat()
        self._atomic(self._paths(blob.id)[0], json.dumps({"blob": value, "state": state}).encode())

    def _load(self, blob_id, owner, now, *, deleted=False):
        import json

        path, data = self._paths(blob_id)
        try:
            if path.stat().st_size > 8192:
                raise BlobNotFound()
            value = json.loads(path.read_text(encoding="utf-8"))
            fields = value["blob"]
            fields["expires_at"] = datetime.fromisoformat(fields["expires_at"])
            blob = Blob(**fields)
            if (
                blob.id != blob_id
                or blob.owner != owner
                or blob.expires_at <= now
                or (value["state"] == "deleted" and not deleted)
            ):
                raise BlobNotFound()
            return blob, value["state"], data
        except (OSError, ValueError, KeyError, TypeError):
            raise BlobNotFound() from None

    def reserve(self, *, owner, purpose, mime, size_bytes, sha256, expires_at, now):
        if (
            not owner
            or purpose
            not in {"question_attachment", "ocr_source", "handwriting", "school_material"}
            or not isinstance(size_bytes, int)
            or not 0 < size_bytes <= self.max_bytes
        ):
            raise ValueError("媒体归属、用途或大小无效")
        if (
            now.tzinfo is None
            or expires_at.tzinfo is None
            or expires_at <= now
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise ValueError("媒体有效期或摘要无效")
        with self._lock, self._disk_lock():
            blob = Blob(str(uuid4()), owner, purpose, size_bytes, sha256, expires_at, mime)
            self._save(blob, "reserved")
            return blob

    def stage(self, *, owner, purpose, data, expires_at, now):
        blob = self.reserve(
            owner=owner,
            purpose=purpose,
            mime="application/octet-stream",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            expires_at=expires_at,
            now=now,
        )
        return self.put(blob.id, owner=owner, data=data, now=now)

    def stat(self, blob_id, *, owner, now):
        with self._lock, self._disk_lock():
            return self._load(blob_id, owner, now)[0]

    def put(self, blob_id, *, owner, data, now):
        with self._lock, self._disk_lock():
            blob, state, path = self._load(blob_id, owner, now)
            if (
                not isinstance(data, bytes)
                or len(data) != blob.size_bytes
                or len(data) > self.max_bytes
                or hashlib.sha256(data).hexdigest() != blob.sha256
            ):
                raise ValueError("媒体大小或摘要不一致")
            if state not in {"reserved", "pending", "ready"}:
                raise BlobNotFound()
            self._atomic(path, data)
            self._save(blob, "ready" if state == "ready" else "pending")
            return blob

    def confirm(self, blob_id, *, owner, sha256, now):
        with self._lock, self._disk_lock():
            blob, state, path = self._load(blob_id, owner, now)
            if state not in {"pending", "ready"} or not path.is_file() or sha256 != blob.sha256:
                raise ValueError("文件尚未上传或媒体摘要不一致")
            if path.stat().st_size != blob.size_bytes or blob.size_bytes > self.max_bytes:
                raise BlobNotFound()
            data = path.read_bytes()
            if len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.sha256:
                raise ValueError("媒体字节不完整")
            self._save(blob, "ready")
            return blob

    def read(self, blob_id, *, owner, now, temporary=False):
        with self._lock, self._disk_lock():
            blob, state, path = self._load(blob_id, owner, now)
            if state != "ready" and not (
                temporary
                and blob.purpose in {"ocr_source", "school_material"}
                and state == "pending"
            ):
                raise BlobNotFound()
            try:
                if path.stat().st_size != blob.size_bytes or blob.size_bytes > self.max_bytes:
                    raise BlobNotFound()
                data = path.read_bytes()
            except OSError:
                raise BlobNotFound() from None
            if len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.sha256:
                raise BlobNotFound()
            return data

    def delete(self, blob_id, *, owner, now):
        with self._lock, self._disk_lock():
            blob, _, path = self._load(blob_id, owner, now, deleted=True)
            self._save(blob, "deleted")
            path.unlink(missing_ok=True)

    def cleanup(self, *, now):
        import json

        removed = 0
        with self._lock, self._disk_lock():
            for manifest in self.root.glob("*.json"):
                if manifest.is_symlink():
                    continue
                try:
                    raw = json.loads(manifest.read_text(encoding="utf-8"))
                    expires = datetime.fromisoformat(raw["blob"]["expires_at"])
                    if expires > now:
                        continue
                    path, data = self._paths(raw["blob"]["id"])
                    if path != manifest:
                        continue
                    data.unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
                    removed += 1
                except (OSError, ValueError, KeyError, TypeError, BlobNotFound):
                    continue
            # Interrupted atomic writes and unattached bytes have no DB visibility.
            # Remove only old files under this controlled root, after the configured
            # local temporary lifetime; never follow directory entries outside it.
            for path in [*self.root.glob(".media-*"), *self.root.glob("*.bin")]:
                if path.is_symlink() or (
                    path.suffix == ".bin" and path.with_suffix(".json").exists()
                ):
                    continue
                if path.suffix == ".bin":
                    try:
                        self._paths(path.stem)
                    except BlobNotFound:
                        continue
                if now.timestamp() - path.stat().st_mtime >= self.temporary_ttl_seconds:
                    path.unlink(missing_ok=True)
        return removed
