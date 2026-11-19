"""Storage failure is retryable and never an invalid-image verdict."""

import base64
import hashlib

import pytest

from support.documents import png_image
from tutor_api.blob_store import FilesystemBlobStore
from tutor_api.s3_blob_store import BlobStorageUnavailable, BlobWriteConflict


@pytest.mark.parametrize("operation", ["reserve", "put", "confirm", "read", "delete"])
@pytest.mark.parametrize(
    "error_type,status,code",
    [
        (BlobWriteConflict, 409, "storage_conflict"),
        (BlobStorageUnavailable, 503, "storage_unavailable"),
    ],
)
def test_storage_failure_is_private_and_original_key_can_retry(
    operation, error_type, status, code, app, reviewer, tmp_path, monkeypatch
):
    store = FilesystemBlobStore(tmp_path / "blobs", max_bytes=10485760)
    app.state.media_store = store
    data = png_image()
    body = {
        "purpose": "question_attachment",
        "mime": "image/png",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    method, path, payload = "POST", "/media/uploads", body
    if operation != "reserve":
        created = reviewer.data("POST", path, json=body, expect=201)
        media_id = created["media_id"]
        method, path, payload = (
            "PUT",
            f"/media/{media_id}/content",
            {"content_base64": base64.b64encode(data).decode()},
        )
        if operation != "put":
            reviewer.data(method, path, json=payload)
            method, path, payload = "POST", f"/media/{media_id}/confirm", {"sha256": body["sha256"]}
            if operation != "confirm":
                reviewer.data(method, path, json=payload)
                method, path, payload = (
                    ("GET", f"/media/{media_id}/content", None)
                    if operation == "read"
                    else ("POST", f"/media/{media_id}/delete", {})
                )
    original = getattr(store, operation)

    def fail(*args, **kwargs):
        raise error_type("PRIVATE-SDK-CREDENTIAL-AND-ENDPOINT")

    monkeypatch.setattr(store, operation, fail)
    response = reviewer.request(method, path, json=payload, key="storage-retry-key")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"] == {}
    assert "PRIVATE" not in response.text
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(store, operation, original)
    result = reviewer.request(method, path, json=payload, key="storage-retry-key")
    assert result.status_code == (201 if operation == "reserve" else 200)
    if operation == "delete":
        assert result.headers["idempotency-replayed"] == "true"
        reviewer.error("GET", f"/media/{media_id}/content", expect=404)
