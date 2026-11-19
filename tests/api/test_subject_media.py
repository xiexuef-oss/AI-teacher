"""SUBJECT301: static images only and independent per-version declarations."""

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from test_media import body, upload
from test_media import enabled as enabled

from support.documents import png_image


def animated(kind):
    stream = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(
        stream,
        format=kind,
        save_all=True,
        append_images=[Image.new("RGB", (32, 32), "black")],
        duration=100,
        loop=0,
    )
    return stream.getvalue()


@pytest.mark.parametrize("kind,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animation_is_rejected_instead_of_silently_using_first_frame(reviewer, enabled, kind, mime):
    data = animated(kind)
    created = reviewer.data("POST", "/media/uploads", json={**body(data), "mime": mime}, expect=201)
    reviewer.error(
        "PUT",
        f"/media/{created['media_id']}/content",
        json={"content_base64": base64.b64encode(data).decode()},
        expect=422,
    )


def attached(reviewer):
    data = png_image()
    id = upload(reviewer, data)
    sha = hashlib.sha256(data).hexdigest()
    reviewer.data("POST", f"/media/{id}/confirm", json={"sha256": sha})
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    payload["question"]["content"]["attachments"] = [
        {"kind": "image", "media_id": id, "alt": "自编低风险题面示意图"}
    ]
    q = reviewer.data("POST", "/admin/question-imports", json=payload, expect=201)
    return q, id, sha


def declare(who, q, id, sha, **extra):
    return who.data(
        "POST",
        f"/admin/questions/{q['id']}/media/{id}/review-confirmations",
        json={"expected_version": q["version"], "sha256": sha, "confirmed": True, **extra},
    )


def test_student_read_requires_publication_current_reference_and_independent_declaration(
    reviewer, new_reviewer, onboarded, enabled
):
    q, id, sha = attached(reviewer)
    other = new_reviewer()
    path = f"/questions/{q['id']}/media/{id}/content"
    onboarded.error("GET", path, expect=404)
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
        expect=422,
    )
    reviewer.error(
        "POST",
        f"/admin/questions/{q['id']}/media/{id}/review-confirmations",
        json={"expected_version": 1, "sha256": sha, "confirmed": True},
        expect=403,
    )
    declaration = declare(other, q, id, sha)
    assert declaration["actor_id"] == other.user_id
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
    )
    onboarded.error("GET", path, expect=404)  # reviewed is not published.
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": (1) + 1, "expected_version": 1, "decision": "publish"},
    )
    assert onboarded.data("GET", path)["media_id"] == id
    onboarded.error("GET", f"/media/{id}/content", expect=403)
    reviewer.data("POST", f"/media/{id}/delete", json={})
    onboarded.error("GET", path, expect=404)


def test_version_expiry_and_role_changes_do_not_reuse_old_image_declarations(
    reviewer, new_reviewer, onboarded, parent, enabled, clock
):
    from support.admin import edit_body

    q, id, sha = attached(reviewer)
    other = new_reviewer()
    declare(other, q, id, sha)
    saved = reviewer.data(
        "POST",
        f"/admin/questions/{q['id']}/versions",
        json=edit_body(q, title=q["title"] + " v2"),
        expect=201,
    )
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/media/{id}/review-confirmations",
        json={"expected_version": 1, "sha256": sha, "confirmed": True},
        expect=409,
    )
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 2, "expected_version": 2, "decision": "approve"},
        expect=422,
    )
    declare(other, saved, id, sha)
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 2, "expected_version": 2, "decision": "approve"},
    )
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": (2) + 1, "expected_version": 2, "decision": "publish"},
    )
    path = f"/questions/{q['id']}/media/{id}/content"
    assert onboarded.data("GET", path)["media_id"] == id
    parent.error("GET", path, expect=403)
    other.error("GET", path, expect=403)
    clock.advance(hours=3)
    onboarded.error("GET", path, expect=404)


def test_publisher_declaration_cannot_replace_independent_reviewed_by_record(
    reviewer, new_reviewer, onboarded, enabled, app
):
    from tutor_api.models import Question

    q, id, sha = attached(reviewer)
    approver = new_reviewer()
    publisher = new_reviewer()
    declare(publisher, q, id, sha)
    with app.state.session_factory() as db:
        row = db.get(Question, q["id"])
        row.status = "published"
        row.reviewed_by = approver.user_id
        db.commit()
    onboarded.error("GET", f"/questions/{q['id']}/media/{id}/content", expect=404)
    # No retroactive confirmation on a published legacy item.
    publisher.error(
        "POST",
        f"/admin/questions/{q['id']}/media/{id}/review-confirmations",
        json={"expected_version": 1, "sha256": sha, "confirmed": True},
        expect=409,
    )


def test_digest_change_invalidates_statement_and_old_animated_files_are_unavailable(
    reviewer, new_reviewer, enabled, app
):
    from datetime import timedelta

    from tutor_api.media_models import MediaAsset

    q, id, sha = attached(reviewer)
    other = new_reviewer()
    declare(other, q, id, sha)
    with app.state.session_factory() as db:
        db.get(MediaAsset, id).sha256 = "0" * 64
        db.commit()
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
        expect=422,
    )
    reviewer.error("GET", f"/media/{id}/content", expect=404)
    data = animated("PNG")
    digest = hashlib.sha256(data).hexdigest()
    now = app.state.clock()
    blob = app.state.media_store.reserve(
        owner=reviewer.user_id,
        purpose="question_attachment",
        mime="image/png",
        size_bytes=len(data),
        sha256=digest,
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    app.state.media_store.put(blob.id, owner=reviewer.user_id, data=data, now=now)
    app.state.media_store.confirm(blob.id, owner=reviewer.user_id, sha256=digest, now=now)
    with app.state.session_factory() as db:
        db.add(
            MediaAsset(
                id=blob.id,
                owner_id=reviewer.user_id,
                object_key=blob.id,
                mime="image/png",
                sha256=digest,
                size_bytes=len(data),
                purpose="question_attachment",
                created_at=now,
                deleted_at=None,
            )
        )
        db.commit()
    reviewer.error("GET", f"/media/{blob.id}/content", expect=404)


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_media_declaration_requires_explicit_boolean_true(
    reviewer, new_reviewer, enabled, confirmed
):
    q, id, sha = attached(reviewer)
    other = new_reviewer()
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/media/{id}/review-confirmations",
        json={"expected_version": 1, "sha256": sha, "confirmed": confirmed},
        expect=422,
    )


def test_declaration_audit_and_receipt_roll_back_together(reviewer, new_reviewer, enabled):
    from sqlalchemy import event

    from tutor_api.models import AuditLog

    q, id, sha = attached(reviewer)
    other = new_reviewer()
    path = f"/admin/questions/{q['id']}/media/{id}/review-confirmations"
    body = {"expected_version": 1, "sha256": sha, "confirmed": True}

    def fail(mapper, connection, target):
        if target.action == "media.review_confirmed":
            raise RuntimeError("audit unavailable")

    event.listen(AuditLog, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            other.request("POST", path, json=body, key="media-review-retry")
    finally:
        event.remove(AuditLog, "before_insert", fail)
    other.error(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
        expect=422,
    )
    first = other.data("POST", path, json=body, key="media-review-retry")
    assert other.data("POST", path, json=body, key="media-review-retry") == first


def test_batch_confirmation_does_not_forge_per_image_declarations(reviewer, new_reviewer, enabled):
    q, id, sha = attached(reviewer)
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    plain = reviewer.data("POST", "/admin/question-imports", json=payload, expect=201)
    other = new_reviewer()
    batch = other.data(
        "POST",
        "/admin/question-reviews/batch",
        json={
            "items": [
                {"expected_review_revision": 1, 
                    "question_id": item["id"],
                    "expected_version": 1,
                    "decision": "approve",
                    "confirmed": True,
                }
                for item in (q, plain)
            ]
        },
    )
    assert [item["status"] for item in batch["items"]] == ["failed", "succeeded"]
    assert batch["items"][0]["error"]["code"] == "media_review_required"


def test_cross_question_resource_and_noncurrent_references_are_uniform_not_found(
    reviewer, new_reviewer, onboarded, enabled
):
    from support.admin import edit_body

    q, id, sha = attached(reviewer)
    other = new_reviewer()
    declare(other, q, id, sha)
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
    )
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": (1) + 1, "expected_version": 1, "decision": "publish"},
    )
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    plain = reviewer.data("POST", "/admin/question-imports", json=payload, expect=201)
    other.data(
        "POST",
        f"/admin/questions/{plain['id']}/review",
        json={"expected_review_revision": 1, "expected_version": 1, "decision": "approve"},
    )
    other.data(
        "POST",
        f"/admin/questions/{plain['id']}/review",
        json={"expected_review_revision": (1) + 1, "expected_version": 1, "decision": "publish"},
    )
    onboarded.error("GET", f"/questions/{plain['id']}/media/{id}/content", expect=404)
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": 3, "expected_version": 1, "decision": "withdraw", "comment": "重新编辑题面"},
    )
    onboarded.error("GET", f"/questions/{q['id']}/media/{id}/content", expect=404)
    detail = reviewer.data("GET", f"/admin/questions/{q['id']}")
    saved = reviewer.data(
        "POST",
        f"/admin/questions/{q['id']}/versions",
        json=edit_body(detail, content={**detail["content"], "attachments": []}),
        expect=201,
    )
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": saved["review_revision"], "expected_version": saved["version"], "decision": "approve"},
    )
    other.data(
        "POST",
        f"/admin/questions/{q['id']}/review",
        json={"expected_review_revision": saved["review_revision"] + 1, "expected_version": saved["version"], "decision": "publish"},
    )
    onboarded.error("GET", f"/questions/{q['id']}/media/{id}/content", expect=404)
