import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from threading import Lock
from types import SimpleNamespace

import pytest

from tutor_api.blob_store import BlobNotFound
from tutor_api.s3_blob_store import (
    BlobStorageUnavailable,
    BlobWriteConflict,
    S3BlobStore,
    local_s3_client,
)


class S3Error(Exception):
    def __init__(self, status):
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__("PRIVATE-SDK-ERROR")


class FakeS3:
    def __init__(self, *, conditional=True):
        self.objects = {}
        self.lock = Lock()
        self.sequence = 0
        self.conditional = conditional

    def put_object(self, *, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **kwargs):
        with self.lock:
            prior = self.objects.get(Key)
            if self.conditional and (
                (IfMatch is not None and (prior is None or prior[1] != IfMatch))
                or (IfNoneMatch == "*" and prior is not None)
            ):
                raise S3Error(412)
            self.sequence += 1
            tag = f'"{self.sequence}"'
            self.objects[Key] = (Body, tag)
            return {"ETag": tag}

    def get_object(self, *, Bucket, Key):
        with self.lock:
            if Key not in self.objects:
                raise S3Error(404)
            body, tag = self.objects[Key]
            return {"Body": io.BytesIO(body), "ContentLength": len(body), "ETag": tag}

    def delete_object(self, *, Bucket, Key, IfMatch=None):
        with self.lock:
            prior = self.objects.get(Key)
            if self.conditional and IfMatch is not None and (prior is None or prior[1] != IfMatch):
                raise S3Error(412)
            self.objects.pop(Key, None)
            return {}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, **kwargs):
        return {
            "Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)][
                :MaxKeys
            ],
            "IsTruncated": False,
        }


NOW = datetime(2026, 11, 17, tzinfo=UTC)


def store(client=None, prefix="test-media/"):
    return S3BlobStore(client or FakeS3(), bucket="engineering-test", prefix=prefix, max_bytes=100)


def local_client_metadata(client):
    handlers = {}
    client.meta = SimpleNamespace(
        endpoint_url="http://127.0.0.1:18333",
        config=SimpleNamespace(
            connect_timeout=3,
            read_timeout=15,
            retries={"total_max_attempts": 1},
            proxies={},
        ),
        events=SimpleNamespace(
            register=lambda event, handler, *, unique_id: handlers.__setitem__(unique_id, handler)
        ),
    )
    return handlers


def test_local_readiness_only_lists_one_scoped_key_without_probing_writes(monkeypatch):
    client = FakeS3()
    handlers = local_client_metadata(client)
    current = store(client)
    calls = []

    def listed(**kwargs):
        calls.append(kwargs)
        return {"Contents": [{"Key": current.prefix + "existing.json"}], "IsTruncated": True}

    def forbidden(**kwargs):
        raise AssertionError("readiness must not read, write or delete objects")

    monkeypatch.setattr(client, "list_objects_v2", listed)
    for operation in ("get_object", "put_object", "delete_object"):
        monkeypatch.setattr(client, operation, forbidden)
    for _ in range(2):
        assert current.ping() is True
    assert calls == [dict(Bucket=current.bucket, Prefix=current.prefix, MaxKeys=1)] * 2
    assert len(handlers) == 1
    guard = next(iter(handlers.values()))
    guard(SimpleNamespace(url="http://127.0.0.1:18333/bucket/key"))
    for url in ("https://127.0.0.1:18333/key", "http://example.com/key"):
        with pytest.raises(ValueError, match="redirect"):
            guard(SimpleNamespace(url=url))


@pytest.mark.parametrize(
    "page",
    [
        None,
        {},
        {"IsTruncated": 1},
        {"IsTruncated": False, "Contents": {}},
        {"IsTruncated": False, "Contents": [{"Key": "foreign/key"}]},
        {"IsTruncated": False, "Contents": [{"Key": "test-media/a"}] * 2},
    ],
)
def test_local_readiness_rejects_malformed_or_unscoped_page(monkeypatch, page):
    client = FakeS3()
    local_client_metadata(client)
    current = store(client)
    monkeypatch.setattr(client, "list_objects_v2", lambda **kwargs: page)
    with pytest.raises(BlobStorageUnavailable, match="readiness"):
        current.ping()


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint_url", "https://example.com:443"),
        ("connect_timeout", None),
        ("read_timeout", 16),
        ("read_timeout", float("inf")),
        ("connect_timeout", True),
        ("proxies", None),
        ("proxies", {"http": "http://example.com"}),
        ("retries", {"total_max_attempts": 2}),
        ("retries", {"total_max_attempts": True}),
    ],
)
def test_local_readiness_rechecks_bounded_loopback_configuration_before_io(
    monkeypatch, field, value
):
    client = FakeS3()
    local_client_metadata(client)
    current = store(client)
    setattr(client.meta if field == "endpoint_url" else client.meta.config, field, value)
    calls = []
    monkeypatch.setattr(client, "list_objects_v2", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(BlobStorageUnavailable, match="readiness"):
        current.ping()
    assert calls == []


def test_missing_owner_is_never_a_public_cleanup_bypass():
    current = store()
    blob = current.stage(
        owner="a",
        purpose="ocr_source",
        data=b"sample",
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    with pytest.raises(BlobNotFound):
        current.read(blob.id, owner=None, now=NOW, temporary=True)


def test_restart_owner_integrity_confirmation_and_delete():
    client = FakeS3()
    first = store(client)
    data = b"self-authored"
    blob = first.reserve(
        owner="a",
        purpose="question_attachment",
        mime="image/png",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    with pytest.raises(BlobNotFound):
        first.read(blob.id, owner="a", now=NOW)
    with pytest.raises(ValueError):
        first.put(blob.id, owner="a", data=b"wrong", now=NOW)
    first.put(blob.id, owner="a", data=data, now=NOW)
    second = store(client)
    with pytest.raises(BlobNotFound):
        second.confirm(blob.id, owner="b", sha256=blob.sha256, now=NOW)
    second.confirm(blob.id, owner="a", sha256=blob.sha256, now=NOW)
    assert first.read(blob.id, owner="a", now=NOW) == data
    second.delete(blob.id, owner="a", now=NOW)
    first.delete(blob.id, owner="a", now=NOW)
    with pytest.raises(BlobNotFound):
        first.put(blob.id, owner="a", data=data, now=NOW)


def test_temp_expiry_and_cleanup_stay_in_namespace():
    client = FakeS3()
    current, foreign = store(client), store(client, "other-media/")
    args = dict(
        owner="a",
        purpose="ocr_source",
        data=b"self-authored",
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
    )
    blob, other = current.stage(**args), foreign.stage(**args)
    assert current.read(blob.id, owner="a", now=NOW, temporary=True) == args["data"]
    assert current.cleanup(now=NOW + timedelta(seconds=1)) == 1
    assert foreign.read(other.id, owner="a", now=NOW, temporary=True) == args["data"]


def test_unsupported_conditions_and_sdk_errors_fail_closed():
    with pytest.raises(BlobStorageUnavailable):
        store(FakeS3(conditional=False))
    client = FakeS3()
    current = store(client)
    client.get_object = lambda **kwargs: (_ for _ in ()).throw(S3Error(503))
    with pytest.raises(BlobStorageUnavailable) as error:
        current.stat("00000000-0000-0000-0000-000000000001", owner="a", now=NOW)
    assert "PRIVATE" not in str(error.value)


def test_conditional_failure_never_overwrites_newer_state():
    client = FakeS3()
    current = store(client)
    blob = current.stage(
        owner="a",
        purpose="ocr_source",
        data=b"sample",
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    original = client.put_object

    def raced(**kwargs):
        if kwargs["Key"].endswith(blob.id + ".json"):
            body, _ = client.objects[kwargs["Key"]]
            client.sequence += 1
            client.objects[kwargs["Key"]] = (body, f'"{client.sequence}"')
        return original(**kwargs)

    client.put_object = raced
    with pytest.raises(BlobWriteConflict):
        current.confirm(blob.id, owner="a", sha256=blob.sha256, now=NOW)
    assert current.read(blob.id, owner="a", now=NOW, temporary=True) == b"sample"


@pytest.mark.parametrize(
    "field,value",
    [
        ("v", True),
        ("state", "unknown"),
        ("revision", "invalid"),
        ("data", "not-base64!"),
        ("data", "d3Jvbmc="),
        ("blob.owner", "another-owner"),
        ("blob.size_bytes", True),
        ("blob.sha256", "0" * 64),
        ("blob.expires_at", "2026-11-17T00:00:00"),
        ("blob.purpose", "unknown"),
        ("extra", "unexpected"),
        ("duplicate", None),
    ],
)
def test_corrupt_object_never_returns_bytes(field, value):
    client = FakeS3()
    current = store(client)
    blob = current.stage(
        owner="a",
        purpose="ocr_source",
        data=b"sample",
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    key = current._key(blob.id)
    raw, tag = client.objects[key]
    envelope = json.loads(raw)
    if field == "duplicate":
        raw = b'{"v":1,' + raw[1:]
    else:
        target = envelope["blob"] if field.startswith("blob.") else envelope
        target[field.rsplit(".", 1)[-1]] = value
        raw = json.dumps(envelope).encode()
    client.objects[key] = (raw, tag)
    with pytest.raises(BlobNotFound):
        current.read(blob.id, owner="a", now=NOW, temporary=True)


def test_oversized_remote_body_is_closed_without_reading(monkeypatch):
    client = FakeS3()
    current = store(client)

    class Unreadable(io.BytesIO):
        def read(self, *args):
            raise AssertionError("Oversized response must not be read")

    stream = Unreadable()
    monkeypatch.setattr(
        client,
        "get_object",
        lambda **kwargs: {
            "Body": stream,
            "ContentLength": current._body_limit + 1,
            "ETag": '"tag"',
        },
    )
    with pytest.raises(BlobNotFound):
        current.stat("00000000-0000-0000-0000-000000000001", owner="a", now=NOW)
    assert stream.closed


@pytest.mark.parametrize("prefix", ["", "/", "../", "media/../", "media"])
def test_invalid_namespace_rejected_before_writes(prefix):
    client = FakeS3()
    with pytest.raises(ValueError):
        store(client, prefix)
    assert client.objects == {}


def test_local_client_uses_explicit_credentials_bounded_wait_and_no_redirect(monkeypatch):
    import sys

    options, handlers = {}, {}
    result = SimpleNamespace()

    def client(service, **kwargs):
        assert service == "s3"
        options.update(kwargs)
        result.meta = SimpleNamespace(
            endpoint_url=kwargs["endpoint_url"],
            config=SimpleNamespace(**kwargs["config"]),
            events=SimpleNamespace(
                register=lambda event, handler, *, unique_id: handlers.__setitem__(event, handler)
            ),
        )
        return result

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=dict))
    assert (
        local_s3_client(
            endpoint="http://127.0.0.1:18333",
            region="local-test",
            access_key="test-access",
            secret_key="test-secret",
        )
        is result
    )
    assert options["aws_access_key_id"] == "test-access"
    assert options["aws_secret_access_key"] == "test-secret"
    assert options["config"] == {
        "signature_version": "s3v4",
        "connect_timeout": 3,
        "read_timeout": 15,
        "retries": {"total_max_attempts": 1},
        "proxies": {},
        "s3": {"addressing_style": "path"},
    }
    guard = handlers["before-send.s3"]
    guard(SimpleNamespace(url="http://127.0.0.1:18333/bucket/key"))
    with pytest.raises(ValueError, match="redirect"):
        guard(SimpleNamespace(url="http://example.com/bucket/key"))


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://localhost:18333",
        "http://127.0.0.1",
        "http://127.0.0.1:18333/other",
        "http://user@127.0.0.1:18333",
        "http://127.0.0.1:18333?secret=x",
        "http://127.0.0.1:18333#x",
    ],
)
def test_local_client_rejects_nonlocal_or_ambiguous_endpoints(endpoint):
    with pytest.raises(ValueError, match="loopback"):
        local_s3_client(endpoint=endpoint, region="test", access_key="a", secret_key="b")
