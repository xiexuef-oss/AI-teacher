"""有界的本地子进程。进程树清理与轮询磁盘上限不是 OS 安全沙箱。"""

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress

from tutor_api.services.document_extract import DocumentParseError


def windows_job(process, *, max_memory_bytes=None, max_cpu_seconds=None):
    # Job handles are private and non-inheritable. Closing kills every descendant.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ctypes.create_string_buffer(144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)
    flags = 0x2000  # KILL_ON_JOB_CLOSE
    if max_memory_bytes is not None:
        flags |= 0x300  # PROCESS_MEMORY | JOB_MEMORY
        offset = 112 if ctypes.sizeof(ctypes.c_void_p) == 8 else 96
        ctypes.c_size_t.from_buffer(limits, offset).value = max_memory_bytes
        ctypes.c_size_t.from_buffer(
            limits, offset + ctypes.sizeof(ctypes.c_void_p)
        ).value = max_memory_bytes
    if max_cpu_seconds is not None:
        flags |= 0x4  # JOB_TIME: user-mode execution time, 100ns ticks
        ctypes.c_int64.from_buffer(limits, 8).value = int(max_cpu_seconds * 10_000_000)
    ctypes.c_uint32.from_buffer(limits, 16).value = flags
    if (
        not job
        or not kernel.SetInformationJobObject(job, 9, limits, len(limits))
        or not kernel.AssignProcessToJobObject(job, int(process._handle))
    ):
        if job:
            kernel.CloseHandle(job)
        terminate_tree(process)
        raise DocumentParseError("parse_failed", "Cannot establish Windows process job")
    return lambda: kernel.CloseHandle(job)


def terminate_tree(process):
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait()


def run_bounded(
    command,
    *,
    timeout,
    output,
    input_file=None,
    env=None,
    workspace=None,
    max_bytes=24 * 1024 * 1024,
    max_memory_bytes=None,
    max_cpu_seconds=None,
):
    if (
        max_memory_bytes is not None
        and max_memory_bytes <= 0
        or max_cpu_seconds is not None
        and max_cpu_seconds <= 0
    ):
        raise ValueError("资源限制必须为正数")
    if sys.platform != "win32" and (max_memory_bytes is not None or max_cpu_seconds is not None):
        raise DocumentParseError("isolation_unavailable", "此平台尚未配置所要求的硬资源隔离")
    process = subprocess.Popen(
        command,
        stdin=input_file or subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    close_job = (
        windows_job(process, max_memory_bytes=max_memory_bytes, max_cpu_seconds=max_cpu_seconds)
        if sys.platform == "win32"
        else None
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            size = os.fstat(output.fileno()).st_size
            if workspace is not None:
                size += sum(p.stat().st_size for p in workspace.rglob("*") if p.is_file())
            if size > max_bytes:
                raise DocumentParseError("parse_failed", "解析输出或临时文件超过限制")
            if time.monotonic() >= deadline:
                raise DocumentParseError("parse_timeout", "解析超时，请拆分文件后重试")
            if process.poll() is not None:
                break
            time.sleep(0.025)
        if process.returncode:
            raise DocumentParseError("parse_failed", "解析进程退出，无法安全解析文件")
    finally:
        if close_job is not None:
            close_job()
        # Also terminate descendants while the root is still alive on failure.
        if process.poll() is None:
            terminate_tree(process)
