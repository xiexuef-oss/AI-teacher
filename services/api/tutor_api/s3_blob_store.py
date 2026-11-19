"""Opt-in S3 adapter. Single-object envelopes and conditional writes avoid split state."""

import base64
import hashlib
import json
import re
from contextlib import closing
from dataclasses import asdict, fields
from datetime import datetime
from uuid import UUID, uuid4

from tutor_api.blob_store import (
    LISTING_MAX_BYTES,
    Blob,
    BlobListingTooLarge,
    BlobNotFound,
    BlobStorageUnavailable,
    BlobWriteConflict,
    InMemoryBlobStore,
    _listing_scope,
    _listing_visible,
    _unique,
)


class S3BlobStore:
    def __init__(self, client, *, bucket, prefix, max_bytes):
        if (
            not bucket
            or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/", prefix)
            or len(prefix) > 128
            or type(max_bytes) is not int
            or not 0 < max_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("Invalid object storage configuration")
        self.client, self.bucket, self.prefix, self.max_bytes = client, bucket, prefix, max_bytes
        self._body_limit = 4 * ((max_bytes + 2) // 3) + 16_384
        self._cleanup_cursor = None
        self._probe_conditions()

    def ping(self):
        """Bounded loopback readiness: one namespace listing, never a CAS probe or cleanup."""
        try:
            validate_local_s3_client(self.client)
            page = self._call("list_objects_v2", Prefix=self.prefix, MaxKeys=1)
            if not isinstance(page, dict) or type(page.get("IsTruncated")) is not bool:
                raise ValueError()
            contents = page.get("Contents", [])
            if not isinstance(contents, list) or len(contents) > 1:
                raise ValueError()
            if any(
                not isinstance(item, dict)
                or not isinstance(item.get("Key"), str)
                or not item["Key"].startswith(self.prefix)
                for item in contents
            ):
                raise ValueError()
            return True
        except Exception:
            raise BlobStorageUnavailable("Local object storage readiness unavailable") from None

    def _call(self, operation, **kwargs):
        try:
            return getattr(self.client, operation)(Bucket=self.bucket, **kwargs)
        except Exception as error:
            response = getattr(error, "response", {})
            metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
            status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
            if status == 404:
                raise BlobNotFound() from None
            if status in {409, 412}:
                raise BlobWriteConflict("Object changed concurrently") from None
            raise BlobStorageUnavailable("Object storage unavailable") from None

    def _raw(self, key, *, max_bytes=None):
        response = self._call("get_object", Key=key)
        try:
            with closing(response["Body"]) as stream:
                length = response["ContentLength"]
                if type(length) is not int or not 0 <= length <= self._body_limit:
                    raise BlobNotFound()
                if max_bytes is not None and length > max_bytes:
                    raise BlobListingTooLarge("Media listing exceeds byte limit")
                read_limit = (
                    self._body_limit if max_bytes is None else min(self._body_limit, max_bytes)
                )
                raw = stream.read(read_limit + 1)
            tag = response["ETag"]
            if (
                len(raw) != length
                or not isinstance(tag, str)
                or not re.fullmatch(r'"[\x21\x23-\x7e]{1,200}"', tag)
            ):
                raise BlobNotFound()
            return raw, tag
        except (BlobNotFound, BlobListingTooLarge):
            raise
        except Exception:
            raise BlobStorageUnavailable("Object storage read unavailable") from None

    def _probe_conditions(self):
        # Reserved probe keys never overlap UUID media keys; no student content.
        key = self.prefix + "_probe/" + uuid4().hex
        try:
            try:
                self._call("put_object", Key=key, Body=b"probe", IfNoneMatch="*")
                for operation, arguments in (
                    ("put_object", {"Body": b"wrong", "IfNoneMatch": "*"}),
                    ("put_object", {"Body": b"wrong", "IfMatch": '"not-current"'}),
                    ("delete_object", {"IfMatch": '"not-current"'}),
                ):
                    try:
                        self._call(operation, Key=key, **arguments)
                    except BlobWriteConflict:
                        continue
                    raise BlobStorageUnavailable("Conditional object storage required")
                if self._raw(key)[0] != b"probe":
                    raise BlobStorageUnavailable("Conditional object storage required")
            finally:
                # Only this fresh, private probe has unconditional disposal.
                self._call("delete_object", Key=key)
        except Exception:
            raise BlobStorageUnavailable("Conditional object storage unavailable") from None

    def _key(self, blob_id):
        try:
            if str(UUID(blob_id)) != blob_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise BlobNotFound() from None
        return self.prefix + blob_id + ".json"

    def _load(self, blob_id, owner, now, *, deleted=False, expired=False):
        if owner is None and not (deleted and expired):
            raise BlobNotFound()
        if now.tzinfo is None:
            raise ValueError("Timezone required")
        return self._decode(
            blob_id, owner, now, *self._raw(self._key(blob_id)), deleted=deleted, expired=expired
        )

    def _decode(self, blob_id, owner, now, raw, tag, *, deleted=False, expired=False):
        try:
            value = json.loads(raw, object_pairs_hook=_unique)
            if (
                set(value) != {"v", "blob", "state", "data", "revision"}
                or type(value["v"]) is not int
                or value["v"] != 1
            ):
                raise ValueError()
            metadata = value["blob"]
            if set(metadata) != {field.name for field in fields(Blob)}:
                raise ValueError()
            metadata["expires_at"] = datetime.fromisoformat(metadata["expires_at"])
            blob = Blob(**metadata)
            state = value["state"]
            if (
                blob.id != blob_id
                or not isinstance(blob.owner, str)
                or not 0 < len(blob.owner) <= 256
                or (owner is not None and blob.owner != owner)
                or blob.expires_at.tzinfo is None
                or (not expired and blob.expires_at <= now)
                or blob.purpose
                not in {"ocr_source", "handwriting", "question_attachment", "school_material"}
                or type(blob.size_bytes) is not int
                or not 0 < blob.size_bytes <= self.max_bytes
                or not isinstance(blob.sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", blob.sha256)
                or (
                    blob.mime is not None
                    and (not isinstance(blob.mime, str) or len(blob.mime) > 256)
                )
                or state not in {"reserved", "pending", "ready", "deleted"}
                or (state == "deleted" and not deleted)
                or not isinstance(value["revision"], str)
                or not re.fullmatch(r"[0-9a-f]{32}", value["revision"])
                or not isinstance(value["data"], str)
            ):
                raise ValueError()
            data = base64.b64decode(value["data"], validate=True)
            if (state in {"reserved", "deleted"} and data) or (
                state in {"pending", "ready"}
                and (
                    len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.sha256
                )
            ):
                raise ValueError()
            return blob, state, data, tag
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise BlobNotFound() from None

    def list_owned(self, *, owner, now, limit):
        _listing_scope(owner, now, limit)
        result, scanned, remaining = [], 0, LISTING_MAX_BYTES
        token, tokens, keys = None, set(), set()
        try:
            # Independent traversal: cleanup's cursor is never an export boundary.
            while True:
                page = self._call(
                    "list_objects_v2",
                    Prefix=self.prefix,
                    MaxKeys=min(100, limit - scanned + 1),
                    **({"ContinuationToken": token} if token is not None else {}),
                )
                if not isinstance(page, dict) or type(page.get("IsTruncated")) is not bool:
                    raise ValueError()
                contents = page.get("Contents", [])
                if not isinstance(contents, list):
                    raise ValueError()
                for item in contents:
                    scanned += 1
                    if scanned > limit:
                        raise BlobListingTooLarge("Media listing exceeds limit")
                    key = item["Key"]
                    if not isinstance(key, str) or not key.startswith(self.prefix) or key in keys:
                        raise ValueError()
                    keys.add(key)
                    if key.startswith(self.prefix + "_probe/"):
                        continue
                    blob_id = key[len(self.prefix) : -5]
                    if self._key(blob_id) != key:
                        raise ValueError()
                    raw, tag = self._raw(key, max_bytes=remaining)
                    remaining -= len(raw)
                    blob, state, _, _ = self._decode(
                        blob_id, None, now, raw, tag, deleted=True, expired=True
                    )
                    if _listing_visible(blob, state, owner, now, self.max_bytes):
                        result.append((blob, state))
                if not page["IsTruncated"]:
                    return sorted(result, key=lambda row: row[0].id)
                token = page.get("NextContinuationToken")
                if (
                    not contents
                    or not isinstance(token, str)
                    or not 0 < len(token) <= 4096
                    or token in tokens
                ):
                    raise ValueError()
                tokens.add(token)
        except BlobListingTooLarge:
            raise
        except Exception:
            raise BlobStorageUnavailable("Media listing unavailable") from None

    def _write(self, blob, state, data, *, tag=None):
        if (
            not isinstance(blob.owner, str)
            or not 0 < len(blob.owner) <= 256
            or type(blob.size_bytes) is not int
            or (blob.mime is not None and (not isinstance(blob.mime, str) or len(blob.mime) > 256))
        ):
            raise ValueError("Invalid media metadata")
        metadata = asdict(blob)
        metadata["expires_at"] = blob.expires_at.isoformat()
        value = {
            "v": 1,
            "blob": metadata,
            "state": state,
            "data": base64.b64encode(data).decode("ascii"),
            "revision": uuid4().hex,
        }
        body = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
        if len(body) > self._body_limit:
            raise ValueError("Object exceeds limit")
        self._call(
            "put_object",
            Key=self._key(blob.id),
            Body=body,
            ContentType="application/json",
            **({"IfNoneMatch": "*"} if tag is None else {"IfMatch": tag}),
        )

    def reserve(self, **kwargs):
        blob = InMemoryBlobStore(max_bytes=self.max_bytes).reserve(**kwargs)
        self._write(blob, "reserved", b"")
        return blob

    def stage(self, **kwargs):
        blob = InMemoryBlobStore(max_bytes=self.max_bytes).stage(**kwargs)
        self._write(blob, "pending", kwargs["data"])
        return blob

    def stat(self, blob_id, *, owner, now):
        return self._load(blob_id, owner, now)[0]

    def put(self, blob_id, *, owner, data, now):
        blob, state, _, tag = self._load(blob_id, owner, now)
        if (
            not isinstance(data, bytes)
            or len(data) != blob.size_bytes
            or hashlib.sha256(data).hexdigest() != blob.sha256
        ):
            raise ValueError("Media bytes do not match")
        self._write(blob, "ready" if state == "ready" else "pending", data, tag=tag)
        return blob

    def confirm(self, blob_id, *, owner, sha256, now):
        blob, state, data, tag = self._load(blob_id, owner, now)
        if state not in {"pending", "ready"} or blob.sha256 != sha256:
            raise ValueError("Media is not ready or digest differs")
        self._write(blob, "ready", data, tag=tag)
        return blob

    def read(self, blob_id, *, owner, now, temporary=False):
        blob, state, data, _ = self._load(blob_id, owner, now)
        if state != "ready" and not (
            temporary and blob.purpose in {"ocr_source", "school_material"} and state == "pending"
        ):
            raise BlobNotFound()
        return data

    def delete(self, blob_id, *, owner, now):
        blob, state, _, tag = self._load(blob_id, owner, now, deleted=True)
        if state != "deleted":
            self._write(blob, "deleted", b"", tag=tag)

    def cleanup(self, *, now):
        # ponytail: scan one page per sweep; cursor is housekeeping, never authorization.
        arguments = {"ContinuationToken": self._cleanup_cursor} if self._cleanup_cursor else {}
        page = self._call("list_objects_v2", Prefix=self.prefix, MaxKeys=100, **arguments)
        removed = 0
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if not key.startswith(self.prefix) or not key.endswith(".json"):
                continue
            blob_id = key[len(self.prefix) : -5]
            try:
                blob, _, _, tag = self._load(blob_id, None, now, deleted=True, expired=True)
                if blob.expires_at <= now:
                    self._call("delete_object", Key=key, IfMatch=tag)
                    removed += 1
            except (BlobNotFound, BlobWriteConflict):
                continue
        self._cleanup_cursor = (
            page.get("NextContinuationToken") if page.get("IsTruncated") else None
        )
        return removed


def _local_s3_address(endpoint):
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    try:
        address = urlsplit(endpoint)
        valid = (
            address.scheme in {"http", "https"}
            and ip_address(address.hostname).is_loopback
            and address.port is not None
            and 0 < address.port < 65536
            and address.path in {"", "/"}
            and not address.query
            and not address.fragment
            and address.username is None
            and address.password is None
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Explicit loopback endpoint required")
    return address


def validate_local_s3_client(client):
    """Validate without IO and pin SDK requests to the configured loopback origin."""
    from urllib.parse import urlsplit

    try:
        address = _local_s3_address(client.meta.endpoint_url)
        config = client.meta.config
        if (
            any(
                type(wait) not in {int, float} or not 0 < wait <= 15
                for wait in (config.connect_timeout, config.read_timeout)
            )
            or not isinstance(config.retries, dict)
            or type(config.retries.get("total_max_attempts")) is not int
            or config.retries["total_max_attempts"] != 1
            or config.proxies != {}
        ):
            raise ValueError()

        def keep_local(request, **kwargs):
            destination = urlsplit(request.url)
            if (destination.scheme, destination.netloc.lower()) != (
                address.scheme,
                address.netloc.lower(),
            ):
                raise ValueError("Object storage redirect outside configured endpoint")

        client.meta.events.register("before-send.s3", keep_local, unique_id="tutor-loopback-origin")
    except Exception:
        raise ValueError("Bounded loopback S3 client required") from None


def local_s3_client(*, endpoint, region, access_key, secret_key):
    """Explicit loopback-only client for opt-in local compatibility tests."""
    _local_s3_address(endpoint)
    if not all(
        isinstance(value, str) and value.strip() for value in (region, access_key, secret_key)
    ):
        raise ValueError("Explicit loopback endpoint and test credentials required")
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            # Local S3 lock contention measured up to 6s with eight stale writers.
            read_timeout=15,
            retries={"total_max_attempts": 1},
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )

    validate_local_s3_client(client)
    return client
