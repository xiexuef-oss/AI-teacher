from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_document_import_jobs import PATH
from test_document_import_worker import queued

from support.documents import png_image
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob, DocumentImportOcrAttempt
from tutor_api.services.document_import_service import cleanup_expired
from tutor_api.services.document_import_worker import process_next


class PowerLoss(BaseException):
    """Simulate a process exit, outside ordinary worker error handling."""


@pytest.mark.parametrize("completed_pages", [0, 1])
@pytest.mark.parametrize("changed_preview", [False, True])
def test_restart_reuses_completed_pages_and_does_not_resend_unknown_page(
    reviewer, app, clock, completed_pages, changed_preview
):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    app.state.settings.import_ocr_mode = "configured"
    calls = []
    preview = ["self-authored-preview"]

    def parser(*args, **kwargs):
        if "page" in kwargs:
            return {"png": preview[0]}
        return {
            "pages": [
                {
                    "number": number,
                    "text": "",
                    "method": "unavailable",
                    "confidence": None,
                    "warnings": [],
                    "media_refs": [],
                }
                for number in range(1, completed_pages + 2)
            ]
        }

    class Gateway:
        def invoke(self, request):
            calls.append(request.request_id)
            if len(calls) == completed_pages + 1:
                raise PowerLoss()
            return SimpleNamespace(
                provider="fake-ocr",
                status="ok",
                validated_output={"stem_text": "1. 自编恢复测试", "expressions": []},
                confidence=0.9,
                review_required=False,
            )

        def provider_is_mock(self, provider):
            return False

    kwargs = {"parser": parser, "gateway": Gateway()}
    args = (app.state.session_factory, app.state.settings, clock.now)
    with pytest.raises(PowerLoss):
        process_next(*args, **kwargs)
    partial = reviewer.data("GET", f"{PATH}/{job_id}")
    assert partial["job"]["status"] == "processing"
    assert len(partial["files"][0]["pages"]) == completed_pages
    if changed_preview:
        preview[0] = "changed-self-authored-preview"
    clock.advance(seconds=app.state.settings.import_worker_lease_seconds + 1)
    assert process_next(*args, **kwargs)
    assert len(calls) == completed_pages + 1
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    file = detail["files"][0]
    assert file["status"] == "needs_ocr"
    assert len(file["pages"]) == completed_pages + 1
    for page in file["pages"][:completed_pages]:
        if changed_preview:
            assert page["text"] == "" and page["method"] == "unavailable"
        else:
            assert page["text"] == "1. 自编恢复测试"
            assert page["method"] == "ocr"
    unknown = file["pages"][-1]
    assert unknown["text"] == "" and unknown["method"] == "unavailable"
    assert any("未自动重发" in warning for warning in unknown["warnings"])
    with app.state.session_factory() as db:
        attempts = list(db.scalars(select(DocumentImportOcrAttempt)))
        assert len(attempts) == completed_pages + 1
        assert all(attempt.trace_id in calls for attempt in attempts)
        assert all(len(attempt.request_digest) == 64 for attempt in attempts)
        expiry = db.get(DocumentImportJob, job_id).expires_at
    clock.advance(seconds=(expiry - clock.now()).total_seconds() + 1)
    with app.state.session_factory() as db:
        assert cleanup_expired(db, clock.now()) == 1
        db.commit()
        assert list(db.scalars(select(DocumentImportOcrAttempt))) == []
        assert db.get(DocumentImportFile, file["id"]) is None


@pytest.mark.parametrize("invalidated", ["cancelled", "takeover"])
def test_late_ocr_response_cannot_write_after_cancellation_or_takeover(
    reviewer, app, clock, invalidated
):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    app.state.settings.import_ocr_mode = "configured"

    def parser(*args, **kwargs):
        if "page" in kwargs:
            return {"png": "self-authored-preview"}
        return {"pages": [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]}

    class Gateway:
        def invoke(self, request):
            with app.state.session_factory() as db:
                job = db.get(DocumentImportJob, job_id)
                if invalidated == "cancelled":
                    job.status = "cancelled"
                else:
                    job.lease_id = "new-worker"
                db.commit()
            return SimpleNamespace(
                provider="fake-ocr",
                status="ok",
                validated_output={"stem_text": "迟到结果不得落库"},
                confidence=0.9,
                review_required=False,
            )

        def provider_is_mock(self, provider):
            return False

    process_next(
        app.state.session_factory, app.state.settings, clock.now, parser=parser, gateway=Gateway()
    )
    with app.state.session_factory() as db:
        attempt = db.scalar(select(DocumentImportOcrAttempt))
        assert attempt.state == "dispatch_unknown"
        assert db.get(DocumentImportFile, attempt.file_id).pages_json == []
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["candidates"] == []


def test_oversized_ocr_text_is_not_persisted_as_a_page_checkpoint(reviewer, app, clock):
    job_id = queued(reviewer, [("self-authored.png", png_image())])
    app.state.settings.import_ocr_mode = "configured"
    app.state.settings.import_max_extracted_chars = 5

    def parser(*args, **kwargs):
        if "page" in kwargs:
            return {"png": "self-authored-preview"}
        return {"pages": [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]}

    class Gateway:
        def invoke(self, request):
            return SimpleNamespace(
                provider="fake-ocr",
                status="ok",
                validated_output={"stem_text": "超过配置文字长度的自编输出"},
                confidence=0.9,
                review_required=False,
            )

        def provider_is_mock(self, provider):
            return False

    process_next(
        app.state.session_factory, app.state.settings, clock.now, parser=parser, gateway=Gateway()
    )
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["files"][0]["status"] == "failed"
    assert detail["files"][0]["pages"] == []
    assert detail["candidates"] == []
    assert "text_limit" in detail["files"][0]["problems"][0]
