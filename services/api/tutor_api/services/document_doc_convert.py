"""默认禁用的 LibreOffice DOC 适配；profile 设置不等于网络/内存安全沙箱。"""

import tempfile
from pathlib import Path

from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_subprocess import run_bounded

PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>0</value></prop>
<prop oor:name="Field" oor:op="fuse"><value>false</value></prop>
<prop oor:name="Chart" oor:op="fuse"><value>false</value></prop>
</item>
</oor:items>"""


def convert_doc(data, executable, limits, timeout):
    if not executable or not Path(executable).is_file():
        raise DocumentParseError("converter_unavailable", "未配置可用 DOC 转换器，请先转为 DOCX")
    if len(data) > limits.max_unpacked_bytes:
        raise DocumentParseError("unpacked_limit", "DOC 文件超过转换资源上限")
    with tempfile.TemporaryDirectory(prefix="tutor-doc-") as directory:
        root = Path(directory)
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(PROFILE, encoding="utf-8")
        source = root / "source.doc"
        source.write_bytes(data)
        output_dir = root / "output"
        output_dir.mkdir()
        command = [
            str(Path(executable).resolve()),
            "-env:UserInstallation=" + profile.as_uri(),
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--convert-to",
            "docx:Office Open XML Text",
            "--outdir",
            str(output_dir),
            str(source),
        ]
        with tempfile.TemporaryFile() as output:
            run_bounded(
                command,
                timeout=timeout,
                output=output,
                workspace=root,
                max_bytes=limits.max_unpacked_bytes,
            )
        converted = output_dir / "source.docx"
        if not converted.is_file() or converted.is_symlink():
            raise DocumentParseError("parse_failed", "DOC 转换失败，请先手工转为 DOCX")
        if converted.stat().st_size > limits.max_unpacked_bytes:
            raise DocumentParseError("unpacked_limit", "转换后文件超过资源上限")
        return converted.read_bytes()
