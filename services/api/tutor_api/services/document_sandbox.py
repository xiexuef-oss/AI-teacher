"""Linux解析隔离策略。仅构造固定策略；调用方必须验证工具可用并失败关闭。"""

from pathlib import PurePosixPath
from uuid import uuid4


def systemd_scope_command(command, *, memory_bytes, tasks, cpu_percent):
    if (
        type(memory_bytes) is not int
        or memory_bytes <= 0
        or type(tasks) is not int
        or not 1 <= tasks <= 128
        or type(cpu_percent) is not int
        or not 1 <= cpu_percent <= 100
        or not command
    ):
        raise ValueError("资源组配额无效")
    return [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "--expand-environment=no",
        "--unit=tutor-parser-" + uuid4().hex + ".scope",
        f"--property=MemoryMax={memory_bytes}",
        "--property=MemorySwapMax=0",
        f"--property=TasksMax={tasks}",
        f"--property=CPUQuota={cpu_percent}%",
        "--",
        *command,
    ]


def _mount(value):
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) in {"/", "/home", "/root", "/mnt", "/etc", "/usr", "/proc", "/sys", "/dev"}
    ):
        raise ValueError("不允许挂载整个宿主目录或非绝对路径")
    return str(path)


def linux_parser_command(*, bwrap, runtime, package, temp_bytes, doc_conversion=False):
    if temp_bytes < 1024:
        raise ValueError("临时空间上限过小")
    runtime, package, executable = _mount(runtime), _mount(package), _mount(bwrap)
    if PurePosixPath(package).name != "tutor_api":
        raise ValueError("只允许挂载解析代码包")
    return [
        executable,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--disable-userns",
        "--new-session",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "PYTHONPATH",
        "/app",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        runtime,
        "/runtime",
        "--ro-bind",
        package,
        "/app/tutor_api",
        # Ubuntu's /usr LibreOffice registry points here. No other host /etc is exposed.
        *(["--ro-bind", "/etc/libreoffice", "/etc/libreoffice"] if doc_conversion else []),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--size",
        str(temp_bytes),
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/tmp",
        "--",
        "/runtime/bin/python",
        "-m",
        "tutor_api.document_parser",
    ]
