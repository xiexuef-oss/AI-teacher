"""联调要起的服务（后端、Web 版的静态服务器、审核后台的开发服务器），以及"Web 版是不是过期了"。

端口是固定的：Flutter Web 版里把后端地址写死成了 127.0.0.1:8000（`lib/config.dart`），
后端本地环境又只放行 localhost 来源的跨域请求，审核后台的开发服务器固定在 5174。
所以联调开始前这三个端口都得是空的——本机的开发服务器要先停掉。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import IO

REPO_ROOT = Path(__file__).resolve().parents[2]

API_PORT = 8000
FLUTTER_PORT = 8081
ADMIN_PORT = 5174
API_URL = f"http://127.0.0.1:{API_PORT}/api/v1"
FLUTTER_URL = f"http://127.0.0.1:{FLUTTER_PORT}/"
ADMIN_URL = f"http://127.0.0.1:{ADMIN_PORT}/"

FLUTTER_APP = REPO_ROOT / "apps" / "flutter_student"
FLUTTER_WEB = FLUTTER_APP / "build" / "web"
ADMIN_APP = REPO_ROOT / "apps" / "admin_web"
CONTRACTS_DART = REPO_ROOT / "packages" / "contracts" / "dart"

# 这些东西变了，Web 版就该重新构建
FLUTTER_SOURCES = [
    FLUTTER_APP / "lib",
    FLUTTER_APP / "web",
    FLUTTER_APP / "assets",
    FLUTTER_APP / "pubspec.yaml",
    FLUTTER_APP / "pubspec.lock",
    CONTRACTS_DART / "lib",
    CONTRACTS_DART / "pubspec.yaml",
]
# 本机没有把 Flutter 加进 PATH（AGENTS.md），找不到时退回到文档里写的位置
DEFAULT_FLUTTER = "C:/src/flutter/bin/flutter.bat"


class ServiceError(RuntimeError):
    """服务没起来、或者起来之后又退出了。"""


# ---------------------------------------------------------------- 纯判断


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _files(source: Path) -> Iterable[Path]:
    if source.is_file():
        return [source]
    if source.is_dir():
        return (path for path in source.rglob("*") if path.is_file())
    return []  # 不存在的来源直接跳过（例如这个应用没有 web/ 目录）


def needs_rebuild(built: Path, sources: Iterable[Path]) -> str | None:
    """Web 版要不要重新构建：没有构建、或者有源文件比它新，就返回原因；不用就返回 None。

    过期的构建会让联调测到旧代码，给出"通过"的假象，所以默认遇到过期就重新构建。
    """
    if not built.exists():
        return f"还没有 Web 构建（{built} 不存在）"
    built_time = built.stat().st_mtime
    newest_time, newest_path = 0.0, None
    for source in sources:
        for path in _files(source):
            modified = path.stat().st_mtime
            if modified > newest_time:
                newest_time, newest_path = modified, path
    if newest_path is not None and newest_time > built_time:
        return f"{newest_path.name} 比 Web 构建新"
    return None


# ---------------------------------------------------------------- 进程


def kill_tree(process: subprocess.Popen) -> None:
    """结束进程和它的子进程（Windows 上 terminate 只杀自己，node 的子进程会留下）。"""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "（没有日志）"


def wait_for_url(
    url: str, *, timeout: float, process: subprocess.Popen | None = None, log: Path | None = None
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            tail = _tail(log) if log else ""
            raise ServiceError(f"{url} 没等到服务就退出了（退出码 {process.returncode}）\n{tail}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except urllib.error.HTTPError:
            return  # 有响应（哪怕是 404）就说明服务起来了
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    tail = _tail(log) if log else ""
    raise ServiceError(f"{url} 在 {timeout:.0f} 秒内没有起来\n{tail}")


class Service:
    """一个子进程服务，日志写进 log_path。"""

    def __init__(self, name: str, process: subprocess.Popen, log_path: Path, log: IO[bytes]):
        self.name = name
        self.process = process
        self.log_path = log_path
        self._log = log

    def stop(self) -> None:
        kill_tree(self.process)
        self._log.close()


def _spawn(name: str, command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
    )
    return Service(name, process, log_path, log)


def start_api(work_dir: Path) -> Service:
    """启动本地开发后端，数据库放在 work_dir 里：每个流程一个全新的库，互不影响，也不碰本机的演示库。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    database = (work_dir / "tutor.sqlite3").resolve().as_posix()
    env = {
        **os.environ,
        "TUTOR_DATABASE_URL": f"sqlite:///{database}",
        "PYTHONIOENCODING": "utf-8",
    }
    service = _spawn(
        "后端",
        [sys.executable, "-X", "utf8", str(REPO_ROOT / "tools" / "run_dev_api.py")],
        cwd=REPO_ROOT,
        env=env,
        log_path=work_dir / "api.log",
    )
    try:
        wait_for_url(f"{API_URL}/health", timeout=90, process=service.process, log=service.log_path)
    except ServiceError:
        service.stop()
        raise
    return service


def start_admin_dev(log_dir: Path) -> Service:
    """启动审核后台的开发服务器（直接用 node 跑 vite，省掉 npm 这一层，结束进程更干净）。"""
    node = shutil.which("node")
    vite = ADMIN_APP / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite.exists():
        raise ServiceError(
            "没有 node，或者审核后台还没有安装依赖：先在 apps/admin_web 下执行 npm install"
        )
    service = _spawn(
        "审核后台",
        [node, str(vite)],
        cwd=ADMIN_APP,
        env={**os.environ},
        log_path=log_dir / "admin_dev.log",
    )
    try:
        wait_for_url(ADMIN_URL, timeout=60, process=service.process, log=service.log_path)
    except ServiceError:
        service.stop()
        raise
    return service


class _WebHandler(SimpleHTTPRequestHandler):
    # Windows 的注册表里 .js 有时是 text/plain，浏览器会拒绝把它当模块脚本加载
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".wasm": "application/wasm",
        ".json": "application/json",
    }

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class StaticServer:
    """在后台线程里静态托管 Flutter 的 Web 构建。"""

    def __init__(self, directory: Path, port: int = FLUTTER_PORT) -> None:
        handler = partial(_WebHandler, directory=str(directory))
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# ---------------------------------------------------------------- Flutter 构建


def find_flutter(explicit: str | None = None) -> str | None:
    for candidate in (explicit, os.environ.get("FLUTTER_BIN"), shutil.which("flutter")):
        if candidate:
            return candidate
    return DEFAULT_FLUTTER if Path(DEFAULT_FLUTTER).exists() else None


def build_flutter_web(flutter: str, log_path: Path) -> None:
    """构建 Web 发布版（联调测的是发布版，和学生实际拿到的一致）。约 2~3 分钟。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        done = subprocess.run(
            [flutter, "build", "web", "--release"],
            cwd=FLUTTER_APP,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    if done.returncode != 0:
        raise ServiceError(f"flutter build web 失败（退出码 {done.returncode}）\n{_tail(log_path)}")
