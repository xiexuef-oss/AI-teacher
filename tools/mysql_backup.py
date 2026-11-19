"""MySQL备份恢复检查；备份及其元数据应放在受保护目录，哈希不是数字签名。"""

import hashlib
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import inspect, text


class BackupValidationError(ValueError):
    pass


def _client_environment():
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("MYSQL_")}


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path, metadata):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise BackupValidationError("备份必须是普通文件")
    if metadata.get("format") != 1 or metadata.get("size_bytes", 0) <= 0:
        raise BackupValidationError("备份元数据无效")
    if path.stat().st_size != metadata["size_bytes"] or file_digest(path) != metadata.get("sha256"):
        raise BackupValidationError("备份校验失败，拒绝执行")


def require_empty_database(engine):
    inspector = inspect(engine)
    if inspector.get_table_names() or inspector.get_view_names():
        raise BackupValidationError("恢复目标必须为空库，拒绝覆盖已有表或视图")
    if engine.dialect.name == "mysql":
        with engine.connect() as connection:
            routines = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()"
                )
            )
            events = connection.scalar(
                text("SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE()")
            )
        if routines or events:
            raise BackupValidationError("恢复目标必须为空库，拒绝覆盖已有过程、函数或事件")


@contextmanager
def _credentials_file(credentials):
    with tempfile.TemporaryDirectory(prefix="tutor-mysql-client-") as directory:
        path = Path(directory) / "client.cnf"
        lines = ["[client]", "protocol=TCP"]
        for key in ("host", "port", "user", "password"):
            value = str(credentials[key])
            if any(char in value for char in "\n\r\x00"):
                raise BackupValidationError("客户端凭据格式无效")
            value = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}="{value}"')
        with path.open("x", encoding="utf-8") as output:
            path.chmod(0o600)
            output.write("\n".join(lines) + "\n")
        yield path


def _database(engine):
    name = engine.url.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
        raise BackupValidationError("数据库名不符合受控客户端调用规则")
    return name


def _require_matching_target(engine, credentials):
    url = engine.url
    query = dict(getattr(url, "query", {}))
    if (
        engine.dialect.name != "mysql"
        or any(key != "charset" for key in query)
        or (query and query.get("charset") != "utf8mb4")
        or any(
            left != right
            for left, right in (
                (url.host, credentials.get("host")),
                (url.port or 3306, int(credentials.get("port", 3306))),
                (url.username, credentials.get("user")),
                (url.password, credentials.get("password")),
            )
        )
    ):
        raise BackupValidationError("检查连接与客户端连接必须使用同一受控目标")


def create_backup(engine, *, executable, credentials, output_path, timeout=60):
    _require_matching_target(engine, credentials)
    name, target = _database(engine), Path(output_path)
    if target.exists() or target.is_symlink():
        raise BackupValidationError("备份输出已存在，拒绝覆盖")
    created = False
    try:
        with _credentials_file(credentials) as config, target.open("xb") as output:
            created = True
            target.chmod(0o600)
            result = subprocess.run(
                [
                    str(executable),
                    "--defaults-file=" + str(config),
                    "--no-login-paths",
                    "--single-transaction",
                    "--skip-lock-tables",
                    "--skip-add-locks",
                    "--skip-comments",
                    "--set-gtid-purged=OFF",
                    "--no-tablespaces",
                    "--hex-blob",
                    "--routines",
                    "--events",
                    "--triggers",
                    name,
                ],
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                env=_client_environment(),
                check=False,
            )
            if result.returncode:
                raise BackupValidationError("备份客户端失败，未生成可用备份")
        return {
            "format": 1,
            "source_database": name,
            "size_bytes": target.stat().st_size,
            "sha256": file_digest(target),
        }
    except BaseException as error:
        if created:
            target.unlink(missing_ok=True)
        if not isinstance(error, (OSError, subprocess.TimeoutExpired, BackupValidationError)):
            raise
        raise BackupValidationError("备份未完成；请检查受保护的连接配置与客户端") from None


def restore_backup(engine, *, executable, credentials, backup_path, metadata, timeout=60):
    _require_matching_target(engine, credentials)
    verify_backup(backup_path, metadata)
    require_empty_database(engine)
    name = _database(engine)
    with _credentials_file(credentials) as config, Path(backup_path).open("rb") as source:
        try:
            result = subprocess.run(
                [str(executable), "--defaults-file=" + str(config), "--no-login-paths", name],
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                env=_client_environment(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BackupValidationError(
                "恢复失败；目标可能已有部分DDL，请人工检查，不自动重跑"
            ) from None
        if result.returncode:
            raise BackupValidationError("恢复失败；目标可能已有部分DDL，请人工检查，不自动重跑")
