"""Authenticated picture bytes and unavailable responses must not be cached."""

import hashlib
from uuid import uuid4

from test_media import enabled as enabled
from test_media import upload

from support.documents import png_image


def test_private_media_success_and_missing_responses_are_no_store(reviewer, enabled):
    data = png_image()
    id = upload(reviewer, data)
    reviewer.data("POST", f"/media/{id}/confirm", json={"sha256": hashlib.sha256(data).hexdigest()})
    for path, expected in [(f"/media/{id}/content", 200), (f"/media/{uuid4()}/content", 404)]:
        response = reviewer.request("GET", path)
        assert response.status_code == expected
        assert response.headers.get("Cache-Control") == "no-store"


def test_student_current_picture_and_deleted_fallback_are_no_store(
    reviewer, new_reviewer, onboarded, enabled
):
    from test_subject_media import attached, declare

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
    path = f"/questions/{q['id']}/media/{id}/content"
    response = onboarded.request("GET", path)
    assert response.status_code == 200 and response.headers.get("Cache-Control") == "no-store"
    reviewer.data("POST", f"/media/{id}/delete", json={})
    response = onboarded.request("GET", path)
    assert response.status_code == 404 and response.headers.get("Cache-Control") == "no-store"
