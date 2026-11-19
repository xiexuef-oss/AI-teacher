"""有超时和输出上限的独立解析进程；不是操作系统安全沙箱。"""

import base64
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from tutor_api.services.document_extract import DocumentParseError, ParseLimits
from tutor_api.services.document_sandbox import linux_parser_command, systemd_scope_command
from tutor_api.services.document_subprocess import run_bounded

MAX_RESULT_BYTES = 24 * 1024 * 1024


def limits_for(settings):
    return ParseLimits(
        max_pages=settings.import_max_pages,
        max_chars=settings.import_max_extracted_chars,
        max_unpacked_bytes=settings.import_max_unpacked_bytes,
        max_image_pixels=settings.import_max_image_pixels,
        max_candidates=settings.import_max_candidates,
    )


def parse_isolated(data, kind, settings, *, page=None, media_index=None):
    command = [sys.executable, "-m", "tutor_api.document_parser"]
    linux_mode = settings.import_isolation_mode == "linux_bwrap"
    if settings.import_linux_cgroup and not linux_mode:
        raise DocumentParseError("isolation_unavailable", "资源组隔离必须配合Linux隔离模式")
    if linux_mode:
        if (
            sys.platform != "linux"
            or not settings.import_linux_bwrap
            or not settings.import_linux_runtime
            or settings.import_memory_limit_bytes is None
            or settings.import_cpu_limit_seconds is None
        ):
            raise DocumentParseError(
                "isolation_unavailable", "所要求的Linux隔离未配置完整或当前平台不支持"
            )
        command = [
            "/usr/bin/prlimit",
            f"--as={settings.import_memory_limit_bytes}",
            f"--cpu={settings.import_cpu_limit_seconds}",
            "--",
            *linux_parser_command(
                bwrap=str(settings.import_linux_bwrap),
                runtime=str(settings.import_linux_runtime),
                package=str(Path(__file__).resolve().parents[1]),
                temp_bytes=settings.import_max_unpacked_bytes,
                doc_conversion=kind == "doc" and settings.import_doc_converter is not None,
            ),
        ]
        if settings.import_linux_cgroup:
            command = systemd_scope_command(
                command,
                memory_bytes=settings.import_memory_limit_bytes,
                tasks=settings.import_linux_task_limit,
                cpu_percent=settings.import_linux_cpu_percent,
            )
    request = {
        "operation": "extract" if page is None else "preview",
        "content": base64.b64encode(data).decode("ascii"),
        "kind": kind,
        "limits": asdict(limits_for(settings)),
        "page": page,
        "media_index": media_index,
        "doc_converter": str(settings.import_doc_converter)
        if settings.import_doc_converter
        else None,
        "timeout": settings.import_parse_timeout_seconds,
    }
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as input_file:
        input_file.write(json.dumps(request).encode("utf-8"))
        input_file.seek(0)
        try:
            run_bounded(
                command,
                input_file=input_file,
                output=output,
                timeout=settings.import_parse_timeout_seconds,
                env={
                    **os.environ,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                    **(
                        {
                            "XDG_RUNTIME_DIR": os.environ.get(
                                "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"
                            )
                        }
                        if linux_mode and settings.import_linux_cgroup
                        else {}
                    ),
                },
                max_bytes=MAX_RESULT_BYTES,
                max_memory_bytes=None if linux_mode else settings.import_memory_limit_bytes,
                max_cpu_seconds=None if linux_mode else settings.import_cpu_limit_seconds,
            )
        except OSError as error:
            code = "isolation_unavailable" if linux_mode else "parse_failed"
            raise DocumentParseError(code, "无法启动所要求的解析运行环境") from error
        output.seek(0, 2)
        if output.tell() > MAX_RESULT_BYTES:
            raise DocumentParseError("parse_failed", "解析进程退出或结果超过限制")
        output.seek(0)
        try:
            result = json.load(output)
        except ValueError as error:
            raise DocumentParseError("parse_failed", "解析进程没有返回有效结果") from error
    if "error" in result:
        raise DocumentParseError(**result["error"])
    return result
