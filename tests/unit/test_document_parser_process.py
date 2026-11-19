import base64

import pytest

from support.documents import text_pdf
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.settings import Settings


def test_configured_hard_limits_reach_parser_process(monkeypatch):
    from tutor_api.services import document_parser_process

    captured = {}

    def run(command, *, output, **kwargs):
        captured.update(kwargs)
        output.write(b'{"pages": []}')

    monkeypatch.setattr(document_parser_process, "run_bounded", run)
    settings = Settings(import_memory_limit_bytes=512 * 1024 * 1024, import_cpu_limit_seconds=20)
    assert parse_isolated(b"test", "pdf", settings) == {"pages": []}
    assert captured["max_memory_bytes"] == 512 * 1024 * 1024
    assert captured["max_cpu_seconds"] == 20


def test_required_linux_isolation_never_falls_back_to_plain_process():
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(
            text_pdf("self authored"), "pdf", Settings(import_isolation_mode="linux_bwrap")
        )
    assert error.value.code == "isolation_unavailable"


@pytest.mark.parametrize(
    "kind,converter,enabled",
    [
        ("pdf", "/usr/lib/libreoffice/program/oosplash", False),
        ("doc", None, False),
        ("doc", "/usr/lib/libreoffice/program/oosplash", True),
    ],
)
def test_office_mount_only_requested_for_explicit_doc_conversion(
    monkeypatch, kind, converter, enabled
):
    from types import SimpleNamespace

    from tutor_api.services import document_parser_process as parser

    requested = {}
    monkeypatch.setattr(parser, "sys", SimpleNamespace(platform="linux", executable="python"))

    def command(**kwargs):
        requested.update(kwargs)
        return ["/tools/bwrap"]

    def run(*args, output, **kwargs):
        output.write(b'{"pages": []}')

    monkeypatch.setattr(parser, "linux_parser_command", command)
    monkeypatch.setattr(parser, "run_bounded", run)
    settings = Settings(
        import_isolation_mode="linux_bwrap",
        import_linux_bwrap="/tools/bwrap",
        import_linux_runtime="/runtime",
        import_memory_limit_bytes=2147483648,
        import_cpu_limit_seconds=20,
        import_doc_converter=converter,
    )
    assert parse_isolated(b"test", kind, settings) == {"pages": []}
    assert requested["doc_conversion"] is enabled


def test_missing_parser_executable_has_safe_explicit_error(monkeypatch):
    from tutor_api.services import document_parser_process

    def missing(*args, **kwargs):
        raise FileNotFoundError("private runtime path")

    monkeypatch.setattr(document_parser_process, "run_bounded", missing)
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(b"test", "pdf", Settings())
    assert "private runtime path" not in str(error.value)


def test_isolated_extraction_and_preview():
    data = text_pdf("1. Self authored question")
    settings = Settings()
    result = parse_isolated(data, "pdf", settings)
    assert "Self authored" in result["pages"][0]["text"]
    result = parse_isolated(data, "pdf", settings, page=1)
    assert base64.b64decode(result["png"]).startswith(b"\x89PNG")


def test_timeout_is_explicit_and_does_not_return_partial_text(monkeypatch):
    def timeout(*args, **kwargs):
        raise DocumentParseError("parse_timeout", "\u89e3\u6790\u8d85\u65f6")

    monkeypatch.setattr("tutor_api.services.document_parser_process.run_bounded", timeout)
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(b"%PDF", "pdf", Settings())
    assert error.value.code == "parse_timeout"


def test_child_validation_error_is_preserved():
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(b"%PDF-invalid", "pdf", Settings())
    assert error.value.code == "invalid_pdf"
