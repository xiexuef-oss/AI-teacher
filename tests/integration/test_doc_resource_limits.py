import os
import sys
import tempfile
from pathlib import Path

import pytest

from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.document_subprocess import run_bounded
from tutor_api.settings import Settings


@pytest.mark.skipif(sys.platform != "win32", reason="Windows硬配额集成验证")
def test_self_authored_doc_conversion_under_hard_limits(tmp_path):
    executable = os.environ.get("TUTOR_TEST_LIBREOFFICE")
    if not executable:
        pytest.skip("需要显式配置本机LibreOffice")
    if not Path(executable).is_file():
        pytest.fail("测试转换器不存在")
    source = tmp_path / "sample.rtf"
    source.write_text(r"{\rtf1\ansi Self authored bounded document test.}", encoding="ascii")
    profile = tmp_path / "profile"
    profile.mkdir()
    command = [
        executable,
        "-env:UserInstallation=" + profile.as_uri(),
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--convert-to",
        "doc:MS Word 97",
        "--outdir",
        str(tmp_path),
        str(source),
    ]
    with tempfile.TemporaryFile() as output:
        run_bounded(
            command,
            timeout=30,
            output=output,
            max_memory_bytes=512 * 1024 * 1024,
            max_cpu_seconds=20,
        )
    document = tmp_path / "sample.doc"
    assert document.read_bytes().startswith(b"\xd0\xcf\x11\xe0")
    settings = Settings(
        import_doc_converter=Path(executable),
        import_memory_limit_bytes=512 * 1024 * 1024,
        import_cpu_limit_seconds=20,
    )
    result = parse_isolated(document.read_bytes(), "doc", settings)
    assert "Self authored bounded document test" in result["pages"][0]["text"]
