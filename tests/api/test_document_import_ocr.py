from types import SimpleNamespace

import pytest
from test_document_import_jobs import PATH
from test_document_import_worker import queued

from support.documents import png_image
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_import_worker import process_next
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.settings import Settings


def test_disabled_ocr_never_calls_gateway(reviewer, app, clock):
    job_id = queued(reviewer, [("scan.png", png_image())])

    class ForbiddenGateway:
        def invoke(self, request):
            raise AssertionError("disabled OCR must not invoke gateway")

    process_next(
        app.state.session_factory, app.state.settings, clock.now, gateway=ForbiddenGateway()
    )
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["files"][0]["pages"][0]["method"] == "unavailable"


def test_mock_uses_gateway_but_never_claims_recognition(reviewer, app, clock):
    job_id = queued(reviewer, [("scan.png", png_image())])
    app.state.settings.import_ocr_mode = "mock"
    process_next(
        app.state.session_factory, app.state.settings, clock.now, gateway=app.state.gateway
    )
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    page = detail["files"][0]["pages"][0]
    assert page["method"] == "ocr_mock" and page["text"] == ""
    assert detail["files"][0]["status"] == "needs_ocr"
    assert any("Mock" in warning for warning in page["warnings"])


@pytest.mark.parametrize(
    "output,status", [(None, "error"), ({"stem_text": "", "expressions": []}, "ok")]
)
def test_configured_failure_or_empty_output_requires_manual_input(output, status):
    calls = []

    class Gateway:
        def invoke(self, request):
            calls.append(request)
            return SimpleNamespace(
                provider="test-provider",
                status=status,
                validated_output=output,
                confidence=None,
                review_required=True,
            )

        def provider_is_mock(self, provider):
            return False

    pages = [{"number": 1, "text": "", "method": "unavailable", "warnings": [], "confidence": None}]
    result = recognize_pages(
        pages,
        b"image",
        "png",
        Settings(import_ocr_mode="configured"),
        Gateway(),
        lambda *a, **kw: {"png": "test-image"},
        "local-job",
    )
    assert len(calls) == 1 and calls[0].task_type.value == "ocr_extract"
    assert result[0]["method"] == "unavailable" and result[0]["text"] == ""
    assert result[0]["warnings"]


def test_configured_mode_with_mock_fallback_is_still_not_real_ocr(reviewer, app, clock):
    job_id = queued(reviewer, [("scan.png", png_image())])
    app.state.settings.import_ocr_mode = "configured"
    process_next(
        app.state.session_factory, app.state.settings, clock.now, gateway=app.state.gateway
    )
    detail = reviewer.data("GET", f"{PATH}/{job_id}")
    assert detail["files"][0]["status"] == "needs_ocr"
    assert detail["files"][0]["pages"][0]["method"] == "ocr_mock"


def test_cancel_checkpoint_prevents_next_page_gateway_call():
    class Gateway:
        def invoke(self, request):
            raise AssertionError("cancelled job must not invoke provider")

    pages = [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]
    with pytest.raises(DocumentParseError) as error:
        recognize_pages(
            pages,
            b"",
            "png",
            Settings(import_ocr_mode="configured"),
            Gateway(),
            None,
            "job",
            lambda: False,
        )
    assert error.value.code == "import_cancelled"


def test_cancel_during_preview_prevents_provider_call():
    state = {"cancelled": False}

    class Gateway:
        def invoke(self, request):
            raise AssertionError("provider invoked after cancellation")

    def parser(*args, **kwargs):
        state["cancelled"] = True
        return {"png": "test"}

    with pytest.raises(DocumentParseError):
        recognize_pages(
            [{"number": 1, "text": "", "method": "unavailable", "warnings": []}],
            b"",
            "png",
            Settings(import_ocr_mode="configured"),
            Gateway(),
            parser,
            "job",
            lambda: not state["cancelled"],
        )


@pytest.mark.parametrize("confidence", [None, 0.2])
def test_low_or_unknown_confidence_keeps_explicit_manual_review(confidence):
    class Gateway:
        def invoke(self, request):
            assert request.input_parts[1].media_ref.startswith("data:image/png;base64,")
            return SimpleNamespace(
                provider="configured-test",
                status="ok",
                validated_output={"stem_text": "1. 自编测试文字", "expressions": []},
                confidence=confidence,
                review_required=True,
            )

        def provider_is_mock(self, provider):
            return False

    pages = [{"number": 1, "text": "", "method": "unavailable", "warnings": [], "confidence": None}]
    result = recognize_pages(
        pages,
        b"",
        "png",
        Settings(import_ocr_mode="configured"),
        Gateway(),
        lambda *a, **kw: {"png": "test"},
        "job",
    )
    assert result[0]["method"] == "ocr"
    assert result[0]["confidence"] == confidence
    assert any("置信度" in warning for warning in result[0]["warnings"])
