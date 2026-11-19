import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from migration_runner import apply_migrations, audit_schema
from mysql_backup import BackupValidationError, restore_backup
from mysql_backup_cli import main
from sqlalchemy import create_engine, text
from test_mysql_migrations import mysql_engine  # noqa: F401


def test_real_backup_restore_and_nonempty_refusal(mysql_engine, tmp_path):  # noqa: F811
    directory = os.environ.get("TUTOR_MYSQL_CLIENT_BIN")
    if not directory:
        pytest.skip("需要显式指定MySQL客户端工具目录")
    credentials = json.loads(Path(os.environ["TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS"]).read_text())
    paths = sorted(Path("migrations").glob("*.sql"))
    apply_migrations(mysql_engine, paths)
    identifier = str(uuid4())
    with mysql_engine.begin() as db:
        db.exec_driver_sql("CREATE FUNCTION backup_probe() RETURNS INT DETERMINISTIC RETURN 42")
        db.execute(
            text(
                "INSERT INTO users (id,role,status,display_name,created_at,updated_at) VALUES (:id,'student','active',:name,UTC_TIMESTAMP(3),UTC_TIMESTAMP(3))"
            ),
            {"id": identifier, "name": "自编恢复测试😀"},
        )
    suffix = ".exe" if os.name == "nt" else ""
    backup = tmp_path / "backup.sql"
    metadata_path = tmp_path / "backup.json"
    assert (
        main(
            [
                "backup",
                "--credentials",
                os.environ["TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS"],
                "--database",
                mysql_engine.url.database,
                "--client",
                str(Path(directory) / ("mysqldump" + suffix)),
                "--backup",
                str(backup),
                "--metadata",
                str(metadata_path),
            ]
        )
        == 0
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert main(["verify", "--backup", str(backup), "--metadata", str(metadata_path)]) == 0
    target_name = "tutor_migration_restore_" + uuid4().hex[:16]
    with mysql_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
        db.exec_driver_sql(f"CREATE DATABASE `{target_name}` CHARACTER SET utf8mb4")
    target = create_engine(mysql_engine.url.set(database=target_name), hide_parameters=True)
    try:
        assert (
            main(
                [
                    "restore",
                    "--credentials",
                    os.environ["TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS"],
                    "--database",
                    target_name,
                    "--client",
                    str(Path(directory) / ("mysql" + suffix)),
                    "--backup",
                    str(backup),
                    "--metadata",
                    str(metadata_path),
                ]
            )
            == 0
        )
        with target.connect() as db:
            assert db.scalar(text("SELECT backup_probe()")) == 42
            assert (
                db.scalar(text("SELECT display_name FROM users WHERE id=:id"), {"id": identifier})
                == "自编恢复测试😀"
            )
        assert audit_schema(target, paths)["pending"] == []
        with pytest.raises(BackupValidationError, match="空库"):
            restore_backup(
                target,
                executable=Path(directory) / ("mysql" + suffix),
                credentials=credentials,
                backup_path=backup,
                metadata=metadata,
            )
    finally:
        target.dispose()
