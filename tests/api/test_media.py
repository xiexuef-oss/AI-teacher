import base64
import hashlib

import pytest

from support.documents import png_image

PATH = "/media/uploads"


def body(data):
    return {
        "purpose": "question_attachment",
        "mime": "image/png",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def upload(who, data):
    created = who.data("POST", PATH, json=body(data), expect=201)
    id = created["media_id"]
    who.data(
        "PUT", f"/media/{id}/content", json={"content_base64": base64.b64encode(data).decode()}
    )
    return id


@pytest.fixture
def enabled(app, tmp_path):
    from tutor_api.blob_store import FilesystemBlobStore

    app.state.media_store = FilesystemBlobStore(tmp_path / "blobs", max_bytes=10485760)
    return app


def test_upload_confirm_owner_and_logical_delete(reviewer, new_reviewer, onboarded, enabled):
    data = png_image()
    id = upload(reviewer, data)
    other = new_reviewer()
    reviewer.error("GET", f"/media/{id}/content", expect=404)
    other.error(
        "POST",
        f"/media/{id}/confirm",
        json={"sha256": hashlib.sha256(data).hexdigest()},
        expect=404,
    )
    reviewer.data(
        "POST",
        f"/media/{id}/confirm",
        json={"sha256": hashlib.sha256(data).hexdigest()},
        key="confirm-media-key",
    )
    assert (
        reviewer.data("GET", f"/media/{id}/content")["content_base64"]
        == base64.b64encode(data).decode()
    )
    other.error("GET", f"/media/{id}/content", expect=404)
    onboarded.error("GET", f"/media/{id}/content", expect=403)
    reviewer.data("POST", f"/media/{id}/delete", json={}, key="delete-media-key")
    reviewer.data("POST", f"/media/{id}/delete", json={}, key="delete-media-key")
    reviewer.error("GET", f"/media/{id}/content", expect=404)


def test_mime_size_hash_and_expiry_are_enforced(reviewer, enabled, clock):
    data = b"not-an-image"
    created = reviewer.data("POST", PATH, json=body(data), expect=201)
    reviewer.error(
        "PUT",
        f"/media/{created['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
        expect=422,
    )
    clock.advance(hours=3)
    reviewer.error(
        "POST",
        f"/media/{created['media_id']}/confirm",
        json={"sha256": hashlib.sha256(data).hexdigest()},
        expect=404,
    )


def test_question_context_preview_cannot_be_unlocked_by_guessing_attachment_uuid(
    reviewer, new_reviewer, enabled
):
    import json
    from pathlib import Path

    from support.admin import edit_body

    data = png_image()
    id = upload(reviewer, data)
    reviewer.data("POST", f"/media/{id}/confirm", json={"sha256": hashlib.sha256(data).hexdigest()})
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    payload["question"]["content"]["attachments"] = [
        {"kind": "image", "media_id": id, "alt": "自编示意图"}
    ]
    other = new_reviewer()
    other.error("POST", "/admin/question-imports", json=payload, expect=422)
    own = reviewer.data("POST", "/admin/question-imports", json=payload, expect=201)
    assert other.data("GET", f"/admin/questions/{own['id']}/media/{id}/content")["media_id"] == id
    other.error("GET", f"/media/{id}/content", expect=404)
    copied = json.loads(json.dumps(payload))
    copied["question"]["content"]["attachments"] = []
    unrelated = other.data("POST", "/admin/question-imports", json=copied, expect=201)
    other.error("GET", f"/admin/questions/{unrelated['id']}/media/{id}/content", expect=404)
    other.error(
        "POST",
        f"/admin/questions/{unrelated['id']}/versions",
        json=edit_body(unrelated, content=payload["question"]["content"]),
        expect=422,
    )
    saved = other.data(
        "POST",
        f"/admin/questions/{own['id']}/versions",
        json=edit_body(own, title=own["title"] + " 校对"),
        expect=201,
    )
    assert saved["content"]["attachments"][0]["media_id"] == id
    # Removal from CURRENT version immediately revokes the review-context preview.
    other.data(
        "POST",
        f"/admin/questions/{own['id']}/versions",
        json=edit_body(saved, content={**saved["content"], "attachments": []}),
        expect=201,
    )
    other.error("GET", f"/admin/questions/{own['id']}/media/{id}/content", expect=404)


def test_disabled_media_and_non_reviewers_fail_closed(reviewer, onboarded, anon):
    reviewer.error("POST", PATH, json=body(png_image()), expect=501)
    onboarded.error("POST", PATH, json={}, expect=403)
    anon.error("POST", PATH, json={}, expect=401, auth=False)


def test_confirmation_rollback_never_exposes_ready_orphan_and_retry_recovers(reviewer, enabled):
    from sqlalchemy import event

    from tutor_api.media_models import MediaAsset

    data = png_image()
    id = upload(reviewer, data)

    def fail(*args):
        raise RuntimeError("metadata store unavailable")

    event.listen(MediaAsset, "after_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="metadata store unavailable"):
            reviewer.request(
                "POST",
                f"/media/{id}/confirm",
                json={"sha256": hashlib.sha256(data).hexdigest()},
                key="media-confirm-crash",
            )
    finally:
        event.remove(MediaAsset, "after_insert", fail)
    reviewer.error("GET", f"/media/{id}/content", expect=404)
    reviewer.data(
        "POST",
        f"/media/{id}/confirm",
        json={"sha256": hashlib.sha256(data).hexdigest()},
        key="media-confirm-crash",
    )
    assert reviewer.data("GET", f"/media/{id}/content")["media_id"] == id


def test_delete_rollback_keeps_bytes_and_restart_recovers_confirmed_asset(reviewer, enabled):
    from sqlalchemy import event

    from tutor_api.blob_store import FilesystemBlobStore
    from tutor_api.media_models import MediaAsset

    data = png_image()
    id = upload(reviewer, data)
    reviewer.data("POST", f"/media/{id}/confirm", json={"sha256": hashlib.sha256(data).hexdigest()})
    old = enabled.state.media_store
    enabled.state.media_store = FilesystemBlobStore(old.root, max_bytes=old.max_bytes)
    assert reviewer.data("GET", f"/media/{id}/content")["media_id"] == id

    def fail(*args):
        raise RuntimeError("delete transaction failed")

    event.listen(MediaAsset, "before_update", fail)
    try:
        with pytest.raises(RuntimeError, match="delete transaction failed"):
            reviewer.request("POST", f"/media/{id}/delete", json={}, key="media-delete-crash")
    finally:
        event.remove(MediaAsset, "before_update", fail)
    assert reviewer.data("GET", f"/media/{id}/content")["media_id"] == id
    reviewer.data("POST", f"/media/{id}/delete", json={}, key="media-delete-crash")
    assert not (old.root / f"{id}.bin").exists()


def test_cleanup_tombstones_expired_db_assets_and_removes_staged_orphans(reviewer, enabled, clock):
    from tutor_api.media_models import MediaAsset
    from tutor_api.services.media_service import cleanup

    data = png_image()
    id = upload(reviewer, data)
    reviewer.data("POST", f"/media/{id}/confirm", json={"sha256": hashlib.sha256(data).hexdigest()})
    orphan = reviewer.data("POST", PATH, json=body(data), expect=201)
    clock.advance(hours=3)
    assert cleanup(enabled.state.session_factory, enabled.state.media_store, clock.now()) == 2
    with enabled.state.session_factory() as db:
        assert db.get(MediaAsset, id).deleted_at is not None
    assert not (enabled.state.media_store.root / f"{orphan['media_id']}.json").exists()
    reviewer.error("GET", f"/media/{id}/content", expect=404)


@pytest.mark.parametrize(
    "change", [{"mime": "image/jpeg"}, {"sha256": "0" * 64}, {"size_bytes": 1}]
)
def test_valid_png_cannot_spoof_declared_mime_digest_or_size(reviewer, enabled, change):
    data = png_image()
    created = reviewer.data("POST", PATH, json={**body(data), **change}, expect=201)
    reviewer.error(
        "PUT",
        f"/media/{created['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
        expect=422,
    )


def test_declared_limits_and_pixel_limits_reject_before_confirm(reviewer, enabled):
    data = png_image()
    reviewer.error(
        "POST",
        PATH,
        json={**body(data), "size_bytes": enabled.state.settings.media_max_bytes + 1},
        expect=413,
    )
    enabled.state.settings = enabled.state.settings.model_copy(update={"media_max_pixels": 1024})
    created = reviewer.data("POST", PATH, json=body(data), expect=201)
    reviewer.error(
        "PUT",
        f"/media/{created['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
        expect=422,
    )


def test_disabling_store_prevents_old_upload_receipt_replay(reviewer, enabled):
    request = body(png_image())
    reviewer.data("POST", PATH, json=request, expect=201, key="enabled-media-key")
    enabled.state.media_store = None
    reviewer.error("POST", PATH, json=request, expect=501, key="enabled-media-key")
