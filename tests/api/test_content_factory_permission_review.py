from base64 import b64encode
from datetime import timedelta
from hashlib import sha256

from support.documents import text_pdf
from tutor_api.db import new_id
from tutor_api.models import ContentFactoryJob, ContentFactorySourceOriginal, KnowledgeNode
from tutor_api.services import content_factory_jobs
from tutor_api.services.content_factory_jobs import process_one
from tutor_api.services.content_factory_sources import source_permits


def test_reviewer_cannot_self_review_and_revocation_survives_replay(
    admin, reviewer, new_reviewer, db, clock, app, monkeypatch
):
    other = new_reviewer()
    for user, role in ((reviewer, "editor"), (reviewer, "reviewer"), (other, "reviewer")):
        admin.data(
            "POST",
            "/admin/content-factory/role-assignments",
            json={"user_id": user.user_id, "role": role, "enabled": True},
        )
    original = text_pdf("Quadratic functions", "Multiquadratic functions")
    knowledge_id = new_id()
    with app.state.session_factory.begin() as session:
        session.add(
            KnowledgeNode(
                id=knowledge_id,
                subject="math",
                code="math.test-quadratic",
                title="Quadratic functions",
                created_at=clock.now(),
            )
        )
    digest = sha256(original).hexdigest()
    source = reviewer.data(
        "POST",
        "/admin/content-factory/sources",
        expect=201,
        json={"title": "自编样张", "source_class": "original", "sha256": digest},
    )["id"]
    now = clock.now()
    path = "/admin/content-factory/source-permissions"
    scope = {"source_id": source, "operation": "print_pdf", "region_code": "CN-51"}
    query = {"source_id": source}
    admin.error("GET", path, params=query, expect=403)
    assert other.data("GET", path, params=query) == {"items": []}
    grant = {
        **scope,
        "decision": "grant",
        "evidence_ref": "review-1",
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
    }
    reviewer.error("POST", path, json=grant, expect=403)
    admin.error("POST", path, json=grant, expect=403)
    other.error("POST", path, json={**grant, "evidence_ref": ""}, expect=422)
    assert other.data("POST", path, json=grant, key="cf-grant-license") == {"id": source}
    assert source_permits(db, source, "print_pdf", "CN-51", now)
    response = other.request("GET", path, params=query)
    assert response.headers["Cache-Control"] == "no-store"
    (record,) = response.json()["data"]["items"]
    assert (
        record["operation"],
        record["region_code"],
        record["status"],
        record["evidence_ref"],
    ) == (
        "print_pdf",
        "CN-51",
        "active",
        "review-1",
    )
    assert other.data("POST", path, json={**scope, "decision": "revoke"}) == {"id": source}
    assert other.data("POST", path, json=grant, key="cf-grant-license") == {"id": source}
    db.expire_all()
    assert not source_permits(db, source, "print_pdf", "CN-51", now)
    assert other.data("GET", path, params=query)["items"][0]["status"] == "revoked"

    jobs = "/admin/content-factory/jobs"
    job_body = {"kind": "analyze_source", "source_id": source, "region_code": "CN-51"}
    reviewer.error("POST", jobs, json=job_body, expect=403)
    analysis_grant = {**grant, "operation": "internal_analysis"}
    other.data("POST", path, json=analysis_grant)
    reviewer.error("POST", jobs, json={**job_body, "region_code": "CN-50"}, expect=403)
    job = reviewer.data("POST", jobs, json=job_body, key="cf-analyze-source", expect=202)
    assert job["status"] == "queued"
    assert reviewer.data("POST", jobs, json=job_body, key="cf-analyze-source", expect=202) == job
    admin.data(
        "POST",
        "/admin/content-factory/role-assignments",
        json={"user_id": other.user_id, "role": "editor", "enabled": True},
    )
    job_path = f"{jobs}/{job['id']}"
    assert reviewer.data("GET", job_path) == job
    other.error("GET", job_path, expect=404)
    upload = f"/admin/content-factory/sources/{source}/original"
    payload = {
        "filename": "sample.pdf",
        "content_base64": b64encode(original).decode(),
        "region_code": "CN-51",
    }
    reviewer.error("POST", upload, json=payload, expect=403)
    storage_grant = {**grant, "operation": "store_original"}
    other.data("POST", path, json=storage_grant)
    other.error("POST", upload, json=payload, expect=404)
    reviewer.error("POST", upload, json={**payload, "region_code": "CN-50"}, expect=403)
    receipt = reviewer.data("POST", upload, json=payload, key="cf-original-upload")
    assert receipt["source_id"] == source
    assert reviewer.data("POST", upload, json=payload, key="cf-original-upload") == receipt
    with app.state.session_factory() as session:
        assert session.get_one(ContentFactorySourceOriginal, (source, "CN-51")).content == original
    other.data("POST", path, json={**scope, "operation": "store_original", "decision": "revoke"})
    with app.state.session_factory() as session:
        assert session.get(ContentFactorySourceOriginal, (source, "CN-51")) is None
    other.error("POST", job_path + "/cancel", expect=404)
    cancelled = reviewer.data("POST", job_path + "/cancel", key="cf-cancel-job")
    assert cancelled["status"] == "cancelled"
    assert reviewer.data("POST", job_path + "/cancel", key="cf-cancel-job") == cancelled
    assert reviewer.data("GET", job_path) == cancelled
    analyzed = reviewer.data("POST", jobs, json=job_body, expect=202)
    pending = reviewer.data("POST", jobs, json=job_body, expect=202)
    other.data("POST", path, json=storage_grant)
    other.data("POST", path, json={**grant, "operation": "read"})
    reviewer.data("POST", upload, json=payload)
    assert process_one(
        app.state.session_factory, clock.now, app.state.settings, job_id=analyzed["id"]
    )
    analyzed_path = f"{jobs}/{analyzed['id']}"
    view = reviewer.data("GET", analyzed_path)
    assert view["status"] == "review_required"
    other.error("GET", analyzed_path, expect=404)
    with app.state.session_factory() as session:
        result = session.get_one(ContentFactoryJob, analyzed["id"]).result_json
        assert result == {
            "level": "metadata",
            "source_id": source,
            "title": "自编样张",
            "source_class": "original",
            "sha256": digest,
            "region_code": "CN-51",
            "document": {
                "pages": 2,
                "text_chars": len("Quadratic functions") + len("Multiquadratic functions"),
                "needs_ocr_pages": 0,
                "knowledge_suggestions": [
                    {
                        "knowledge_id": knowledge_id,
                        "title": "Quadratic functions",
                        "subject": "math",
                        "matched_pages": [1],
                    }
                ],
            },
        }
        assert view["result"] == result
    cancelled_during_parse = reviewer.data("POST", jobs, json=job_body, expect=202)
    during_path = f"{jobs}/{cancelled_during_parse['id']}"
    with monkeypatch.context() as patch:

        def cancel_during_parse(*args):
            assert reviewer.data("POST", during_path + "/cancel")["status"] == "cancelled"
            return {"pages": [{"text": "discard", "method": "text"}]}

        patch.setattr(content_factory_jobs, "parse_isolated", cancel_during_parse)
        assert not process_one(
            app.state.session_factory,
            clock.now,
            app.state.settings,
            job_id=cancelled_during_parse["id"],
        )
    assert "result" not in reviewer.data("GET", during_path)

    revoked_during_parse = reviewer.data("POST", jobs, json=job_body, expect=202)
    with monkeypatch.context() as patch:

        def revoke_during_parse(*args):
            other.data("POST", path, json={**scope, "operation": "read", "decision": "revoke"})
            return {"pages": [{"text": "discard", "method": "text"}]}

        patch.setattr(content_factory_jobs, "parse_isolated", revoke_during_parse)
        assert process_one(
            app.state.session_factory,
            clock.now,
            app.state.settings,
            job_id=revoked_during_parse["id"],
        )
    rejected = reviewer.data("GET", f"{jobs}/{revoked_during_parse['id']}")
    assert rejected["status"] == "failed" and "result" not in rejected
    with app.state.session_factory() as session:
        assert session.get(ContentFactorySourceOriginal, (source, "CN-51")) is not None
    assert "document" not in reviewer.data("GET", analyzed_path)["result"]
    clock.advance(days=1)
    assert "result" not in reviewer.data("GET", analyzed_path)
    assert process_one(app.state.session_factory, clock.now, job_id=pending["id"])
    assert reviewer.data("GET", f"{jobs}/{pending['id']}")["status"] == "failed"
    with app.state.session_factory() as session:
        assert session.get_one(ContentFactoryJob, pending["id"]).result_json is None
    reviewer.error("POST", jobs, json=job_body, expect=403)
