import hashlib
from types import SimpleNamespace

import pytest
from mysql_backup import BackupValidationError, create_backup, require_empty_database, verify_backup
from sqlalchemy import create_engine, text


def client_engine(password="test"):
    return SimpleNamespace(
        dialect=SimpleNamespace(name="mysql"),
        url=SimpleNamespace(
            database="test", host="127.0.0.1", port=13316, username="test", password=password
        ),
    )


def test_backup_tampering_is_rejected(tmp_path):
    path = tmp_path / "backup.sql"
    path.write_bytes(b"SELECT 1;")
    metadata = {
        "format": 1,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    verify_backup(path, metadata)
    path.write_bytes(b"SELECT 2;")
    with pytest.raises(BackupValidationError, match="校验"):
        verify_backup(path, metadata)


def test_restore_never_overwrites_existing_tables_or_views():
    engine = create_engine("sqlite:///:memory:")
    require_empty_database(engine)
    with engine.begin() as db:
        db.execute(text("CREATE VIEW existing_view AS SELECT 1"))
    with pytest.raises(BackupValidationError, match="空库"):
        require_empty_database(engine)
    engine.dispose()


def test_dump_credentials_are_not_command_arguments_and_temp_file_is_removed(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setenv("MYSQL_TEST_LOGIN_FILE", "untrusted-config")
    monkeypatch.setenv("MYSQL_HOST", "untrusted-host")

    def run(command, *, stdout, **kwargs):
        assert command[1].startswith("--defaults-file=")
        assert command[2] == "--no-login-paths"
        assert not any(key.upper().startswith("MYSQL_") for key in kwargs["env"])
        assert "--routines" in command and "--events" in command
        assert not any("test-private-password" in arg for arg in command)
        path = command[1].split("=", 1)[1]
        seen.append(path)
        assert "test-private-password" in __import__("pathlib").Path(path).read_text()
        stdout.write(b"SELECT 1;")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("mysql_backup.subprocess.run", run)
    engine = client_engine("test-private-password")
    target = tmp_path / "backup.sql"
    metadata = create_backup(
        engine,
        executable="mysqldump",
        credentials={
            "host": "127.0.0.1",
            "port": 13316,
            "user": "test",
            "password": "test-private-password",
        },
        output_path=target,
    )
    verify_backup(target, metadata)
    assert not __import__("pathlib").Path(seen[0]).exists()


def test_interrupted_dump_removes_partial_file(tmp_path, monkeypatch):
    def interrupted(command, *, stdout, **kwargs):
        stdout.write(b"partial dump")
        raise KeyboardInterrupt

    monkeypatch.setattr("mysql_backup.subprocess.run", interrupted)
    engine = client_engine()
    target = tmp_path / "interrupted.sql"
    with pytest.raises(KeyboardInterrupt):
        create_backup(
            engine,
            executable="mysqldump",
            credentials={"host": "127.0.0.1", "port": 13316, "user": "test", "password": "test"},
            output_path=target,
        )
    assert not target.exists()


def test_mismatched_target_rejected_before_any_client_or_inspection(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mysql_backup.subprocess.run", lambda *a, **k: pytest.fail("client must not run")
    )
    from mysql_backup import restore_backup

    credentials = dict(host="other-server", port=13316, user="test", password="test")
    for operation, kwargs in (
        (create_backup, dict(output_path=tmp_path / "new.sql")),
        (restore_backup, dict(backup_path=tmp_path / "absent.sql", metadata={})),
    ):
        with pytest.raises(BackupValidationError, match="同一受控目标"):
            operation(client_engine(), executable="unused", credentials=credentials, **kwargs)


@pytest.mark.parametrize(
    "query",
    [
        {"host": "other-server"},
        {"unix_socket": "/tmp/other.sock"},
        {"read_default_file": "other.cnf"},
    ],
)
def test_url_query_cannot_override_controlled_target(tmp_path, query):
    from sqlalchemy import URL

    engine = client_engine()
    engine.url = URL.create(
        "mysql+pymysql",
        host="127.0.0.1",
        port=13316,
        username="test",
        password="test",
        database="test",
        query=query,
    )
    with pytest.raises(BackupValidationError, match="同一受控目标"):
        create_backup(
            engine,
            executable="unused",
            credentials=dict(host="127.0.0.1", port=13316, user="test", password="test"),
            output_path=tmp_path / "new.sql",
        )
