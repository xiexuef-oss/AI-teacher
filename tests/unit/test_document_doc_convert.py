from pathlib import Path

import pytest

from support.documents import docx_document
from tutor_api.services.document_doc_convert import convert_doc
from tutor_api.services.document_extract import DocumentParseError, ParseLimits
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.settings import Settings


def test_converter_defaults_disabled():
    assert Settings().import_doc_converter is None
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(b"legacy doc", "doc", Settings())
    assert error.value.code == "converter_unavailable"


def test_missing_converter_is_explicit(tmp_path):
    with pytest.raises(DocumentParseError) as error:
        convert_doc(b"legacy", tmp_path / "missing.exe", ParseLimits(), 1)
    assert error.value.code == "converter_unavailable"


def test_conversion_profile_and_docx_result(monkeypatch, tmp_path):
    executable = tmp_path / "soffice.exe"
    executable.touch()
    expected = docx_document("<w:p><w:r><w:t>Self authored</w:t></w:r></w:p>")

    def run(command, **kwargs):
        # Use URI decoding for spaces and Windows paths.
        from urllib.parse import unquote, urlparse
        from urllib.request import url2pathname

        profile = Path(url2pathname(unquote(urlparse(command[1].split("=", 1)[1]).path)))
        config = (profile / "user" / "registrymodifications.xcu").read_text()
        assert "DisableMacrosExecution" in config
        assert "MacroSecurityLevel" in config
        assert "Update" in config and "Link" in config
        output = Path(command[command.index("--outdir") + 1])
        (output / "source.docx").write_bytes(expected)

    monkeypatch.setattr("tutor_api.services.document_doc_convert.run_bounded", run)
    assert convert_doc(b"legacy", executable, ParseLimits(), 1) == expected


def test_converter_timeout_and_resource_limits(tmp_path):
    import sys
    import tempfile

    from tutor_api.services.document_subprocess import run_bounded

    with tempfile.TemporaryFile() as output:
        with pytest.raises(DocumentParseError) as error:
            run_bounded(
                [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1, output=output
            )
        assert error.value.code == "parse_timeout"
    with tempfile.TemporaryFile() as output:
        with pytest.raises(DocumentParseError) as error:
            run_bounded(
                [sys.executable, "-c", 'print("x" * 10000)'],
                timeout=5,
                output=output,
                max_bytes=100,
            )
        assert error.value.code == "parse_failed"


def test_real_libreoffice_self_authored_doc(tmp_path):
    import tempfile

    from tutor_api.services.document_subprocess import run_bounded

    executable = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if not executable.is_file():
        pytest.skip("Local LibreOffice not installed")
    # Self-authored RTF is converted to an actual binary Word 97 DOC fixture.
    source = tmp_path / "sample.rtf"
    source.write_bytes(b"{\\rtf1\\ansi Self authored engineering question 1. Solve x+1=2.}")
    profile = tmp_path / "fixture-profile"
    with tempfile.TemporaryFile() as output:
        run_bounded(
            [
                str(executable),
                "-env:UserInstallation=" + profile.as_uri(),
                "--headless",
                "--convert-to",
                "doc:MS Word 97",
                "--outdir",
                str(tmp_path),
                str(source),
            ],
            timeout=20,
            output=output,
        )
    data = (tmp_path / "sample.doc").read_bytes()
    assert data.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    settings = Settings(import_doc_converter=executable)
    result = parse_isolated(data, "doc", settings)
    assert "Self authored engineering question" in result["pages"][0]["text"]
    # DOCX text fragments share the existing explicit no-raster fallback.
    with pytest.raises(DocumentParseError) as error:
        parse_isolated(data, "doc", settings, page=1)
    assert error.value.code == "preview_not_available"


def test_missing_or_oversized_converter_output(monkeypatch, tmp_path):
    executable = tmp_path / "converter.exe"
    executable.touch()
    monkeypatch.setattr("tutor_api.services.document_doc_convert.run_bounded", lambda *a, **k: None)
    with pytest.raises(DocumentParseError) as error:
        convert_doc(b"legacy", executable, ParseLimits(), 1)
    assert error.value.code == "parse_failed"

    def oversized(command, **kwargs):
        output = Path(command[command.index("--outdir") + 1])
        (output / "source.docx").write_bytes(b"x" * 1025)

    monkeypatch.setattr("tutor_api.services.document_doc_convert.run_bounded", oversized)
    with pytest.raises(DocumentParseError) as error:
        convert_doc(b"legacy", executable, ParseLimits(max_unpacked_bytes=1024), 1)
    assert error.value.code == "unpacked_limit"


def test_timeout_terminates_descendants(tmp_path):
    import sys
    import tempfile
    import time

    from tutor_api.services.document_subprocess import run_bounded

    marker = tmp_path / "child-survived"
    child_code = (
        f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()"
    )
    parent_code = (
        f'import subprocess, sys, time; subprocess.Popen([sys.executable, "-c", {child_code!r}]); '
        "time.sleep(20)"
    )
    with tempfile.TemporaryFile() as output, pytest.raises(DocumentParseError) as error:
        run_bounded([sys.executable, "-c", parent_code], timeout=0.3, output=output)
    assert error.value.code == "parse_timeout"
    time.sleep(1.2)
    assert not marker.exists()
