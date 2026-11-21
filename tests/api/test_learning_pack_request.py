from base64 import b64decode
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from reportlab import __file__ as reportlab_path

from support.documents import png_image
from tutor_api.blob_store import FilesystemBlobStore
from tutor_api.models import LearningPackCommand, LearningPackPublication, LearningPackReturnPhotos
from tutor_api.services.learning_pack_evidence import paper_evidence
from tutor_api.services.learning_pack_worker import prepare_one
from tutor_api.services.weekly_snapshots import generate_due_snapshots


def test_pack_request_uses_saved_budget_and_replays(onboarded, app, clock, db):
    profile = onboarded.data("GET", "/profile")
    onboarded.save_profile(
        json={
            "region_code": profile["region_code"],
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 0, "weekdays": [1]},
        }
    )
    body = {"school_minutes": 20}
    first = onboarded.data("POST", "/learning/packs", expect=202, key="pack-request", json=body)
    assert first["status"] == "queued"
    assert (
        onboarded.data("POST", "/learning/packs", expect=202, key="pack-request", json=body)
        == first
    )
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    assert not prepare_one(app.state.session_factory, clock.now)
    assert db.get(LearningPackCommand, first["id"]).plan_json == {"remaining_minutes": 0}
    assert db.get(LearningPackPublication, first["id"]) is None
    assert (
        onboarded.data("GET", f"/learning/jobs/{first['id']}")["pack_result"]
        == "insufficient_budget"
    )
    assert onboarded.data("GET", f"/learning/jobs/{first['id']}")["status"] == "succeeded"


def test_worker_publishes_both_sample_pdfs(
    onboarded, app, clock, db, new_student, parent, tmp_path
):
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    result = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 5})
    assert onboarded.data("GET", "/learning/packs") == {"ids": []}
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    pack = db.get_one(LearningPackPublication, result["id"])
    duplicate = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 5})
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    assert db.get(LearningPackPublication, duplicate["id"]) is None
    assert (
        onboarded.data("GET", f"/learning/jobs/{duplicate['id']}")["pack_result"]
        == "awaiting_return"
    )
    assert (
        db.get_one(LearningPackCommand, duplicate["id"]).plan_json["deferred_reason"]
        == "awaiting_return"
    )
    assert pack.student_pdf.startswith(b"%PDF")
    assert pack.solution_pdf.startswith(b"%PDF")
    assert pack.manifest_json["items"][0]["code"] == "001"
    assert onboarded.data("GET", f"/learning/jobs/{result['id']}")["status"] == "succeeded"
    assert onboarded.data("GET", f"/learning/jobs/{result['id']}")["pack_result"] == "published"
    path = f"/learning/packs/{result['id']}"
    pdf = onboarded.data("GET", f"{path}/student-pdf")
    assert b64decode(pdf["content_base64"]) == pack.student_pdf
    assert pdf["sha256"] == sha256(pack.student_pdf).hexdigest()
    item = onboarded.data("GET", f"{path}/items/001")
    assert item == {
        "revision": 1,
        "code": "001",
        "question_version_id": pack.manifest_json["items"][0]["question_version_id"],
    }
    onboarded.error("GET", f"{path}/items/999", expect=404)
    assert onboarded.data("GET", f"{path}/items") == {"items": [item]}
    other = new_student()
    assert onboarded.data("GET", "/learning/packs") == {"ids": [result["id"]]}
    assert onboarded.data("GET", "/learning/packs", params={"after": result["id"]}) == {"ids": []}
    assert other.data("GET", "/learning/packs") == {"ids": []}
    other.error("GET", f"{path}/student-pdf", expect=404)
    other.error("GET", f"{path}/items/001", expect=404)
    other.error("GET", f"{path}/items", expect=404)
    token = pack.manifest_json["items"][0]["page_token"]
    assert onboarded.data("GET", f"{path}/page", params={"token": token}) == item
    onboarded.error("GET", f"{path}/page", params={"token": "0" * 32}, expect=404)
    other.error("GET", f"{path}/page", params={"token": token}, expect=404)
    returned = f"{path}/items/001/returns"
    solution = f"{path}/solution-pdf"
    onboarded.error("GET", solution, expect=409)
    other.error("GET", solution, expect=404)
    body = {
        "transcript": "我选 B，因为返回较早位置。",
        "completed_on": "2026-11-08",
        "independence": "independent",
    }
    store = app.state.media_store = FilesystemBlobStore(
        tmp_path / "paper-blobs", max_bytes=10485760
    )

    def photo(owner, size):
        data = png_image(size)
        blob = store.reserve(
            owner=owner,
            purpose="ocr_source",
            mime="image/png",
            size_bytes=len(data),
            sha256=sha256(data).hexdigest(),
            now=clock.now(),
            expires_at=clock.now() + timedelta(hours=1),
        )
        store.put(blob.id, owner=owner, data=data, now=clock.now())
        return blob.id

    foreign_photo = photo(other.user_id, (320, 80))
    body["photo_ids"] = [photo(onboarded.user_id, (320, 80)), photo(onboarded.user_id, (321, 80))]
    preview = f"/scans/uploads/{body['photo_ids'][0]}/content"
    assert b64decode(onboarded.data("GET", preview)["content_base64"]) == png_image((320, 80))
    other.error("GET", preview, expect=404)
    onboarded.error("GET", returned, expect=404)
    other.error("POST", returned, json=body, expect=404)
    onboarded.error("POST", returned, json={"transcript": " "}, expect=422)
    onboarded.error(
        "POST", returned, json={**body, "photo_ids": [item["question_version_id"]]}, expect=404
    )
    onboarded.error("POST", returned, json={**body, "photo_ids": [foreign_photo]}, expect=404)
    onboarded.error("POST", returned, json={**body, "completed_on": "2099-01-01"}, expect=422)
    assert onboarded.data("POST", returned, json=body, key="return-001", expect=201) == item
    assert (
        db.get_one(LearningPackReturnPhotos, (result["id"], "001")).media_ids_json
        == body["photo_ids"]
    )
    assert onboarded.data("POST", returned, json=body, key="return-001", expect=201) == item
    onboarded.error("POST", returned, json=body, expect=409)
    record = onboarded.data("GET", returned)
    assert record["item"] == item
    assert record["transcript"] == body["transcript"]
    other.error("GET", returned, expect=404)
    correction = {"expected_revision": 0, "transcript": "校正后的转写"}
    other.error("PUT", returned, json=correction, expect=404)
    corrected = onboarded.data("PUT", returned, json=correction, key="correct-paper")
    assert corrected["transcript_revision"] == 1
    assert corrected["transcript"] == correction["transcript"]
    assert onboarded.data("PUT", returned, json=correction, key="correct-paper") == corrected
    onboarded.error("PUT", returned, json=correction, expect=409)
    assert onboarded.data("GET", returned) == corrected
    with app.state.session_factory() as session:
        evidence = paper_evidence(session, onboarded.user_id)
        assert len(evidence) == 1
        assert evidence[0].transcript == correction["transcript"]
        assert evidence[0].transcript_revision == 1
        assert evidence[0].question_version_id == item["question_version_id"]
        assert evidence[0].outcome == "unknown"
        assert evidence[0].completed_on.isoformat() == "2026-11-08"
        assert evidence[0].independence == "independent"
        assert paper_evidence(session, other.user_id) == []
    onboarded.data("PUT", returned, json={"expected_revision": 1, "transcript": "Ｂ"})
    with app.state.session_factory() as session:
        evidence = paper_evidence(session, onboarded.user_id)
        assert len(evidence) == 1
        assert evidence[0].outcome == "correct"
    onboarded.data("PUT", returned, json={"expected_revision": 2, "transcript": "A"})
    with app.state.session_factory() as session:
        assert paper_evidence(session, onboarded.user_id)[0].outcome == "incorrect"
    downloaded = onboarded.data("GET", solution)
    assert b64decode(downloaded["content_base64"]) == pack.solution_pdf
    assert downloaded["sha256"] == sha256(pack.solution_pdf).hexdigest()
    other.error("GET", solution, expect=404)

    second = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 5})
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    path = f"/learning/packs/{second['id']}"
    other.error("POST", f"{path}/abandon", expect=404)
    first = onboarded.data("POST", f"{path}/abandon", key="abandon-pack")
    assert onboarded.data("POST", f"{path}/abandon", key="abandon-pack") == first
    onboarded.data("GET", f"{path}/solution-pdf")
    onboarded.error("POST", f"{path}/items/001/returns", json=body, expect=409)
    third = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 5})
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    onboarded.data(
        "POST",
        f"/learning/packs/{third['id']}/items/001/returns",
        json={**body, "transcript": "B", "completed_on": "2026-11-09"},
        expect=201,
    )
    schedule = onboarded.data("GET", "/learning/review-schedule")["items"]
    assert len(schedule) == 1
    assert schedule[0]["due_on"] == "2026-11-12"
    assert schedule[0]["stage"] == 0
    assert other.data("GET", "/learning/review-schedule") == {"items": []}
    weekly = f"/parents/students/{onboarded.user_id}/weekly"
    parent.error("GET", weekly, expect=404)
    invite = onboarded.data(
        "POST", "/me/parent-invites", expect=201, json={"expected_parent_invite_revision": 0}
    )
    parent.data("POST", "/parents/links", expect=201, json={"code": invite["code"]})
    paper = parent.data("GET", weekly)["paper"]
    assert paper["confirmed"] == 2
    assert paper["independent"]["denominator"] == 1
    assert paper["awaiting_assessment"] == 1
    assert paper["late_returns"] == 1
    assert parent.data("GET", weekly, params={"week_start": "2026-11-02"})["paper"] is None
    fourth = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 10})
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    with app.state.session_factory() as session:
        command = session.get_one(LearningPackCommand, fourth["id"])
        assert command.plan_json["reviews"] == [
            {
                "knowledge_id": schedule[0]["knowledge_id"],
                "original_due_on": "2026-11-12",
                "suggested_on": "2026-11-16",
                "deferred_reason": "insufficient_budget",
            }
        ]
    detail = onboarded.data("GET", f"/learning/jobs/{fourth['id']}")["reviews"]
    assert detail == [{**command.plan_json["reviews"][0], "title": schedule[0]["title"]}]
    other.error("GET", f"/learning/jobs/{fourth['id']}", expect=404)
    fifth = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})
    assert prepare_one(
        app.state.session_factory, clock.now, Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    )
    with app.state.session_factory() as session:
        pack = session.get_one(LearningPackPublication, fifth["id"])
        assert pack.manifest_json["items"][0]["suggested_on"] == "2026-11-16"
    clock.advance(days=7)
    onboarded.error("GET", preview, expect=404)
    assert generate_due_snapshots(app.state.session_factory, app.state.settings, clock.now()) == 1
    snapshot = f"/parents/students/{onboarded.user_id}/weekly-snapshots/2026-11-09"
    original = parent.data("GET", snapshot)
    assert original["revision"] == 1
    onboarded.data(
        "PUT",
        f"/learning/packs/{third['id']}/items/001/returns",
        json={"expected_revision": 0, "transcript": "校正后待确认"},
    )
    latest = parent.data("GET", snapshot)
    assert latest["revision"] == 2
    assert latest["report"]["paper"]["awaiting_assessment"] == 2
    assert parent.data("GET", snapshot, params={"revision": 1}) == original


def test_worker_rolls_back_staged_pdfs_and_retries_same_job(onboarded, app, clock, monkeypatch):
    import pytest

    from tutor_api.services import learning_pack_worker as worker
    from tutor_api.services.learning_jobs import RETRY_DELAY

    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    body = {"school_minutes": 0}
    job = onboarded.data("POST", "/learning/packs", expect=202, key="retry-pack", json=body)
    path = f"/learning/packs/{job['id']}"
    status_path = f"/learning/jobs/{job['id']}"
    sessions = app.state.session_factory
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    publish = worker.publish

    def interrupt_after_staging(*args):
        assert publish(*args)
        raise OSError("injected publication interruption")

    with monkeypatch.context() as patch:
        patch.setattr(worker, "publish", interrupt_after_staging)
        with pytest.raises(OSError, match="injected publication interruption"):
            prepare_one(sessions, clock.now, font)

    before_retry = onboarded.data("GET", status_path)
    assert before_retry["status"] == "retry_wait"
    assert onboarded.data("GET", "/learning/packs") == {"ids": []}
    onboarded.error("GET", f"{path}/student-pdf", expect=404)
    onboarded.error("GET", f"{path}/solution-pdf", expect=404)
    with sessions() as session:
        assert session.get(LearningPackPublication, job["id"]) is None
        assert session.get_one(LearningPackCommand, job["id"]).plan_json is None
    assert not prepare_one(sessions, clock.now, font)
    assert onboarded.data("POST", "/learning/packs", expect=202, key="retry-pack", json=body) == job

    clock.advance(RETRY_DELAY.total_seconds())
    assert prepare_one(sessions, clock.now, font)
    assert onboarded.data("GET", status_path)["pack_result"] == "published"
    assert onboarded.data("GET", "/learning/packs") == {"ids": [job["id"]]}
    assert onboarded.data("GET", f"{path}/student-pdf")["revision"] == 1
    onboarded.error("GET", f"{path}/solution-pdf", expect=409)


def test_worker_recovers_paper_pack_after_claimant_exits(onboarded, app, clock):
    from tutor_api.services.learning_jobs import LEASE, claim

    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})
    sessions = app.state.session_factory
    with sessions.begin() as session:
        assert claim(session, job["id"], clock.now()) is not None

    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    assert not prepare_one(sessions, clock.now, font)
    assert onboarded.data("GET", "/learning/packs") == {"ids": []}

    clock.advance(LEASE.total_seconds())
    assert prepare_one(sessions, clock.now, font)
    assert onboarded.data("GET", "/learning/packs") == {"ids": [job["id"]]}
    assert not prepare_one(sessions, clock.now, font)


def test_solution_render_retry_reuses_student_pdf(onboarded, app, clock, monkeypatch):
    import pytest

    from tutor_api.models import LearningPackRenderCheckpoint
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.learning_jobs import RETRY_DELAY

    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})
    sessions = app.state.session_factory
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"

    def fail(*args, **kwargs):
        raise OSError("render interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(publication, "render_solutions", fail)
        with pytest.raises(OSError, match="render interrupted"):
            prepare_one(sessions, clock.now, font)
    with sessions() as session:
        checkpoint = session.get_one(LearningPackRenderCheckpoint, job["id"])
        expected = checkpoint.student_pdf, checkpoint.manifest_json
        assert session.get(LearningPackPublication, job["id"]) is None

    monkeypatch.setattr(publication, "render_student", fail)
    clock.advance(RETRY_DELAY.total_seconds())
    assert prepare_one(sessions, clock.now, font)
    with sessions() as session:
        pack = session.get_one(LearningPackPublication, job["id"])
        assert (pack.student_pdf, pack.manifest_json["items"]) == expected
        assert session.get(LearningPackRenderCheckpoint, job["id"]) is None


def test_expired_worker_reuses_committed_student_pdf(onboarded, app, clock, monkeypatch):
    import pytest

    from tutor_api.models import LearningPackRenderCheckpoint
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.learning_jobs import LEASE

    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})
    sessions = app.state.session_factory
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"

    def fail(*args, **kwargs):
        raise SystemExit("render interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(publication, "render_solutions", fail)
        with pytest.raises(SystemExit, match="render interrupted"):
            prepare_one(sessions, clock.now, font)
    with sessions() as session:
        checkpoint = session.get_one(LearningPackRenderCheckpoint, job["id"])
        expected = checkpoint.student_pdf, checkpoint.manifest_json
        assert session.get(LearningPackPublication, job["id"]) is None

    monkeypatch.setattr(publication, "render_student", fail)
    clock.advance(LEASE.total_seconds())
    assert prepare_one(sessions, clock.now, font)
    with sessions() as session:
        pack = session.get_one(LearningPackPublication, job["id"])
        assert (pack.student_pdf, pack.manifest_json["items"]) == expected
        assert session.get(LearningPackRenderCheckpoint, job["id"]) is None


def test_worker_publishes_and_returns_a_physics_multiple_choice_sample(onboarded, app, clock, db):
    from io import BytesIO

    from pypdf import PdfReader

    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["physics"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})["id"]
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    assert prepare_one(app.state.session_factory, clock.now, font)
    path = f"/learning/packs/{job}"
    pack = db.get_one(LearningPackPublication, job)
    student_text = PdfReader(BytesIO(pack.student_pdf)).pages[0].extract_text()
    solution_text = PdfReader(BytesIO(pack.solution_pdf)).pages[0].extract_text()
    assert "mg sin " in solution_text
    assert "mg cos " in solution_text
    assert r"\theta" not in student_text + solution_text
    assert "$" not in student_text + solution_text
    item = onboarded.data("GET", f"{path}/items/001")
    assert (
        db.get_one(LearningPackPublication, job).manifest_json["items"][0]["answer_mode"]
        == "multiple_choice"
    )
    returned = onboarded.data(
        "POST", f"{path}/items/001/returns", expect=201, json={"transcript": "Ｂ、Ａ"}
    )
    assert returned == item
    with app.state.session_factory() as session:
        evidence = paper_evidence(session, onboarded.user_id, pack_id=job)
        assert evidence[0].question_version_id == item["question_version_id"]
        assert evidence[0].outcome == "correct"
    assert onboarded.data("GET", f"{path}/solution-pdf")["revision"] == 1


def test_worker_uses_another_subject_when_first_sample_is_awaiting_return(
    onboarded, app, clock, db
):
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry", "physics"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]},
        }
    )
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    jobs = []
    for _ in range(3):
        job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})[
            "id"
        ]
        assert prepare_one(app.state.session_factory, clock.now, font)
        jobs.append(job)
    packs = [db.get(LearningPackPublication, job_id) for job_id in jobs]
    assert [item.manifest_json["items"][0]["answer_mode"] for item in packs[:2]] == [
        "single_choice",
        "multiple_choice",
    ]
    assert len({item.manifest_json["items"][0]["question_version_id"] for item in packs[:2]}) == 2
    assert packs[2] is None
    assert onboarded.data("GET", f"/learning/jobs/{jobs[2]}")["pack_result"] == "awaiting_return"


def test_due_physics_review_takes_priority_over_fresh_chemistry(onboarded, app, clock, db, parent):
    settings = {"mode": "boarding", "weekly_minutes": 10, "weekdays": [1]}
    onboarded.save_profile(
        json={"region_code": "CN-51", "subjects": ["physics"], "learning_settings": settings}
    )
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    initial = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})[
        "id"
    ]
    assert prepare_one(app.state.session_factory, clock.now, font)
    onboarded.data(
        "POST",
        f"/learning/packs/{initial}/items/001/returns",
        expect=201,
        json={"transcript": "A,B", "independence": "independent"},
    )
    clock.advance(days=3)
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry", "physics"],
            "learning_settings": settings,
        }
    )
    review = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})["id"]
    assert prepare_one(app.state.session_factory, clock.now, font)
    item = db.get_one(LearningPackPublication, review).manifest_json["items"][0]
    assert item["answer_mode"] == "fill"
    assert (
        item["question_version_id"]
        != db.get_one(LearningPackPublication, initial).manifest_json["items"][0][
            "question_version_id"
        ]
    )
    assert item["suggested_on"]
    onboarded.data(
        "POST",
        f"/learning/packs/{review}/items/001/returns",
        expect=201,
        json={"transcript": "5 m/s²", "independence": "independent"},
    )
    with app.state.session_factory() as session:
        evidence = paper_evidence(session, onboarded.user_id, pack_id=review)
        assert evidence[0].outcome == "correct"
        assert evidence[0].question_version_id == item["question_version_id"]
    schedule = onboarded.data("GET", "/learning/review-schedule")["items"]
    assert sum(entry["stage"] == 1 for entry in schedule) == 1
    weekly = f"/parents/students/{onboarded.user_id}/weekly"
    parent.error("GET", weekly, expect=404)
    invite = onboarded.data(
        "POST", "/me/parent-invites", expect=201, json={"expected_parent_invite_revision": 0}
    )
    parent.data("POST", "/parents/links", expect=201, json={"code": invite["code"]})
    paper = parent.data("GET", weekly)["paper"]
    assert paper["confirmed"] == 2
    assert paper["independent"]["denominator"] == 2
    assert paper["independent"]["numerator"] == 2


def test_overdue_budget_cap_does_not_block_fresh_subject(onboarded, app, clock, db):
    settings = {"mode": "boarding", "weekly_minutes": 5, "weekdays": [1]}
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry", "physics"],
            "learning_settings": settings,
        }
    )
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    initial = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})[
        "id"
    ]
    assert prepare_one(app.state.session_factory, clock.now, font)
    onboarded.data(
        "POST",
        f"/learning/packs/{initial}/items/001/returns",
        expect=201,
        json={"transcript": "B", "independence": "independent"},
    )
    clock.advance(days=4)
    next_job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})[
        "id"
    ]
    assert prepare_one(app.state.session_factory, clock.now, font)
    assert (
        db.get_one(LearningPackPublication, next_job).manifest_json["items"][0]["answer_mode"]
        == "multiple_choice"
    )
    assert (
        onboarded.data("GET", f"/learning/jobs/{next_job}")["reviews"][0]["deferred_reason"]
        == "overdue_budget_cap"
    )
