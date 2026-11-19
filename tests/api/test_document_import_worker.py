import base64
from datetime import timedelta

import pytest
from test_document_import_jobs import PATH, create_job, upload_body

from support.documents import png_image, text_pdf
from tutor_api.proto_models import DocumentImportJob
from tutor_api.services.document_import_worker import process_next


def queued(reviewer, files):
    job = create_job(reviewer)
    for name, data in files:
        result = reviewer.data(
            "POST",
            f"{PATH}/{job['id']}/files",
            json=upload_body(job["revision"], filename=name, data=data),
            expect=201,
        )
        job = result["job"]
    reviewer.data(
        "POST",
        f"{PATH}/{job['id']}/process",
        json={"expected_revision": job["revision"]},
        expect=200,
    )
    return job["id"]


def test_worker_checkpoints_files_and_requires_human_confirmation(reviewer, app, clock):
    job_id = queued(
        reviewer, [("text.pdf", text_pdf("1. Self authored question")), ("scan.png", png_image())]
    )
    assert process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["job"]["status"] == "needs_review"
    assert {f["filename"]: f["status"] for f in detail["files"]} == {
        "text.pdf": "ready",
        "scan.png": "needs_ocr",
    }
    assert len(detail["candidates"]) == 2
    assert all(not c["confirmed"] and c["question_id"] is None for c in detail["candidates"])
    assert not process_next(app.state.session_factory, app.state.settings, clock.now)


def test_worker_continues_after_bad_file(reviewer, app, clock):
    job_id = queued(reviewer, [("bad.pdf", b"%PDF-broken"), ("good.pdf", text_pdf("Question"))])
    process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["job"]["status"] == "partial_failure"
    files = {f["filename"]: f for f in detail["files"]}
    assert files["bad.pdf"]["status"] == "failed" and files["good.pdf"]["status"] == "ready"
    assert "invalid_pdf" in files["bad.pdf"]["problems"][0]


def test_cancel_during_parse_discards_late_result(reviewer, app, clock):
    job_id = queued(reviewer, [("text.pdf", text_pdf("Question"))])

    def parser(*args, **kwargs):
        detail = reviewer.data("GET", f"{PATH}/{job_id}")
        reviewer.data(
            "POST", f"{PATH}/{job_id}/cancel", json={"expected_revision": detail["job"]["revision"]}
        )
        return {"pages": []}

    process_next(app.state.session_factory, app.state.settings, clock.now, parser=parser)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["job"]["status"] == "cancelled" and detail["candidates"] == []


def test_expired_lease_recovers_after_restart(reviewer, app, clock):
    job_id = queued(reviewer, [("text.pdf", text_pdf("Question"))])
    with app.state.session_factory() as db:
        job = db.get(DocumentImportJob, job_id)
        job.status, job.lease_id = "processing", "abandoned"
        job.lease_until = clock.now() - timedelta(seconds=1)
        db.commit()
    assert process_next(app.state.session_factory, app.state.settings, clock.now)
    assert reviewer.data("GET", f"{PATH}/{job_id}")["job"]["status"] == "needs_review"


def test_preview_is_png_owner_only_and_has_bounded_page(reviewer, new_reviewer):
    job = create_job(reviewer)
    uploaded = reviewer.data(
        "POST",
        f"{PATH}/{job['id']}/files",
        json=upload_body(filename="text.pdf", data=text_pdf("Question")),
        expect=201,
    )
    path = f"{PATH}/{job['id']}/files/{uploaded['file']['id']}/previews"
    result = reviewer.data("GET", f"{path}/1")
    assert result["media_type"] == "image/png"
    assert base64.b64decode(result["content_base64"]).startswith(b"\x89PNG")
    assert new_reviewer().request("GET", f"{path}/1").status_code == 404
    assert reviewer.request("GET", f"{path}/2").status_code == 422


@pytest.mark.parametrize("phase", ["parser", "gateway"])
def test_slow_file_renews_lease_before_second_worker_can_take_it(
    reviewer, app, clock, monkeypatch, phase
):
    import time
    from threading import Event, Thread

    import tutor_api.services.document_import_worker as worker

    monkeypatch.setattr(worker, "_HEARTBEAT_MAX_INTERVAL", 0.02, raising=False)
    job_id = queued(reviewer, [("slow.pdf", text_pdf("Question"))])
    entered, release = Event(), Event()
    calls = []

    def slow_call():
        calls.append("parse")
        entered.set()
        assert release.wait(5)

    def parser(*args, **kwargs):
        if phase == "parser":
            slow_call()
            return {"pages": []}
        if "page" in kwargs:
            return {"png": base64.b64encode(png_image()).decode("ascii")}
        return {
            "pages": [
                {"number": 1, "text": "", "method": "unavailable", "warnings": [], "media_refs": []}
            ]
        }

    class SlowGateway:
        def invoke(self, request):
            from types import SimpleNamespace

            slow_call()
            return SimpleNamespace(
                provider="fake",
                status="ok",
                validated_output={"stem_text": "Self authored"},
                confidence=0.9,
                review_required=False,
            )

        def provider_is_mock(self, provider):
            return False

    app.state.settings.import_ocr_mode = "configured"

    thread = Thread(
        target=process_next,
        args=(app.state.session_factory, app.state.settings, clock.now),
        kwargs={"parser": parser, "gateway": SlowGateway()},
    )
    thread.start()
    try:
        assert entered.wait(3)
        seconds = app.state.settings.import_worker_lease_seconds
        for _ in range(3):
            clock.advance(seconds=seconds / 2)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                with app.state.session_factory() as db:
                    until = db.get(DocumentImportJob, job_id).lease_until
                if (until - clock.now()).total_seconds() >= seconds - 1:
                    break
                time.sleep(0.01)
            assert (until - clock.now()).total_seconds() >= seconds - 1
            assert not process_next(
                app.state.session_factory,
                app.state.settings,
                clock.now,
                parser=lambda *a, **k: calls.append("duplicate") or {"pages": []},
            )
        assert calls == ["parse"]
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "invalidated", ["cancelled", "expired", "lease_expired", "new_lease", "shutdown"]
)
def test_heartbeat_stops_without_overwriting_invalidated_lease(
    reviewer, app, clock, monkeypatch, invalidated
):
    import time
    from threading import Event

    import tutor_api.services.document_import_worker as worker

    monkeypatch.setattr(worker, "_HEARTBEAT_MAX_INTERVAL", 0.02)
    job_id = queued(reviewer, [("slow.pdf", text_pdf("Question"))])
    stopping = Event()
    until = clock.now() + timedelta(seconds=180)
    with app.state.session_factory() as db:
        job = db.get(DocumentImportJob, job_id)
        job.status, job.lease_id, job.lease_until = "processing", "owner", until
        db.commit()
    accesses = []

    def factory():
        accesses.append("db")
        return app.state.session_factory()

    with worker._keep_lease(factory, app.state.settings, clock.now, job_id, "owner", stopping):
        with app.state.session_factory() as db:
            job = db.get(DocumentImportJob, job_id)
            if invalidated == "cancelled":
                job.status = "cancelled"
            elif invalidated == "expired":
                job.expires_at = clock.now()
            elif invalidated == "lease_expired":
                job.lease_until = clock.now()
                until = job.lease_until
            elif invalidated == "new_lease":
                job.lease_id = "new-owner"
            else:
                stopping.set()
            db.commit()
        clock.advance(seconds=10)
        time.sleep(0.08)
        with app.state.session_factory() as db:
            job = db.get(DocumentImportJob, job_id)
            assert job.lease_until == until
            assert job.lease_id == ("new-owner" if invalidated == "new_lease" else "owner")
    # Simulate disposal immediately after the owner's scope exits.
    count = len(accesses)
    time.sleep(0.04)
    assert len(accesses) == count


def test_close_waits_for_inflight_worker_before_database_disposal(monkeypatch):
    from threading import Event, Thread

    import tutor_api.services.document_import_worker as worker
    from tutor_api.settings import Settings

    entered, release, closed = Event(), Event(), Event()
    accesses = []

    def slow_process(factory, settings, clock, **kwargs):
        entered.set()
        assert release.wait(5)
        assert kwargs["stopping"].is_set()
        accesses.append("last in-flight action")
        return True

    monkeypatch.setattr(worker, "process_next", slow_process)
    instance = worker.ImportWorker(None, Settings(), None)
    instance.start()
    assert entered.wait(2)
    closer = Thread(target=lambda: (instance.close(), closed.set()))
    closer.start()
    try:
        assert not closed.wait(0.1)
    finally:
        release.set()
        closer.join(3)
    assert closed.is_set()
    assert not instance.thread.is_alive()
    assert accesses == ["last in-flight action"]


def test_upload_audit_order_and_cross_file_merge_with_answer_positions(reviewer, app, clock):
    from tutor_api.services.document_import_service import job_files

    job_id = queued(
        reviewer,
        [
            ("first.pdf", text_pdf("1. Question")),
            ("second.pdf", text_pdf("continued condition")),
            ("answers.pdf", text_pdf("1. secret answer")),
        ],
    )
    with app.state.session_factory() as db:
        assert [f.filename for f in job_files(db, job_id)] == [
            "first.pdf",
            "second.pdf",
            "answers.pdf",
        ]
    process_next(app.state.session_factory, app.state.settings, clock.now)
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert len(detail["candidates"]) == 1
    item = detail["candidates"][0]
    assert item["text"] == "1. Question\ncontinued condition"
    assert len(item["locations"]) == 2
    assert item["locations"][0]["file_id"] != item["locations"][1]["file_id"]
    assert all(loc["page"] == 1 and loc["block"] == 1 for loc in item["locations"])
    answer_id = next(f["id"] for f in detail["files"] if f["filename"] == "answers.pdf")
    assert any(answer_id in w and "人工确认" in w for w in item["warnings"])
    assert item["payload"] is None and not item["confirmed"]


def test_missing_upload_audit_does_not_assume_uuid_file_order(reviewer, app, clock):
    from sqlalchemy import delete

    from tutor_api.models import AuditLog

    job_id = queued(
        reviewer, [("a.pdf", text_pdf("1. Question")), ("b.pdf", text_pdf("continuation"))]
    )
    with app.state.session_factory() as db:
        db.execute(
            delete(AuditLog).where(
                AuditLog.target_id == job_id, AuditLog.action == "document_import.upload"
            )
        )
        db.commit()
    process_next(app.state.session_factory, app.state.settings, clock.now)
    items = reviewer.data("GET", f"{PATH}/{job_id}")["candidates"]
    assert len(items) == 2
    assert all(any("顺序" in w for w in i["warnings"]) for i in items)


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "human text"),
        ("title", "human title"),
        ("payload_json", {"human": True}),
        ("confirmed_by", "reviewer"),
    ],
)
def test_final_cross_file_suggestions_preserve_human_workspace(reviewer, app, clock, field, value):
    from sqlalchemy import select

    from tutor_api.proto_models import DocumentImportCandidate
    from tutor_api.services.document_parser_process import parse_isolated

    job_id = queued(
        reviewer, [("a.pdf", text_pdf("1. Question")), ("b.pdf", text_pdf("continuation"))]
    )
    changed = []
    calls = []

    def parser(data, kind, settings):
        if calls:
            with app.state.session_factory() as db:
                item = db.scalar(
                    select(DocumentImportCandidate).where(DocumentImportCandidate.job_id == job_id)
                )
                changed.append(item.id)
                setattr(item, field, reviewer.user_id if field == "confirmed_by" else value)
                db.commit()
        calls.append(True)
        return parse_isolated(data, kind, settings)

    process_next(app.state.session_factory, app.state.settings, clock.now, parser=parser)
    with app.state.session_factory() as db:
        item = db.get(DocumentImportCandidate, changed[0])
        assert getattr(item, field) == (reviewer.user_id if field == "confirmed_by" else value)
        assert (
            len(
                list(
                    db.scalars(
                        select(DocumentImportCandidate).where(
                            DocumentImportCandidate.job_id == job_id
                        )
                    )
                )
            )
            == 2
        )
