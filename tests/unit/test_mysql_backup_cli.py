import json

import mysql_backup_cli as cli


def test_verify_needs_no_database(tmp_path, capsys):
    backup = tmp_path / "backup.sql"
    backup.write_bytes(b"SELECT 1;")
    metadata = tmp_path / "metadata.json"
    from mysql_backup import file_digest

    metadata.write_text(
        json.dumps(
            {"format": 1, "size_bytes": backup.stat().st_size, "sha256": file_digest(backup)}
        )
    )
    assert cli.main(["verify", "--backup", str(backup), "--metadata", str(metadata)]) == 0
    assert "校验通过" in capsys.readouterr().out


def test_backup_refuses_existing_metadata_before_connection(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata.json"
    metadata.write_text("preserve")
    monkeypatch.setattr(
        cli,
        "create_engine",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    assert (
        cli.main(
            [
                "backup",
                "--backup",
                str(tmp_path / "backup.sql"),
                "--metadata",
                str(metadata),
                "--credentials",
                str(tmp_path / "absent.json"),
                "--database",
                "test",
                "--client",
                "mysqldump",
            ]
        )
        == 1
    )
    assert metadata.read_text() == "preserve"


def test_errors_do_not_print_credentials(tmp_path, capsys):
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"password":"never-print-this"}')
    assert (
        cli.main(
            [
                "backup",
                "--backup",
                str(tmp_path / "backup.sql"),
                "--metadata",
                str(tmp_path / "metadata.json"),
                "--credentials",
                str(credentials),
                "--database",
                "test",
                "--client",
                "mysqldump",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err
    assert not (tmp_path / "metadata.json").exists()


def test_metadata_failure_removes_only_new_backup(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        json.dumps(dict(host="127.0.0.1", port=13316, user="test", password="test"))
    )
    backup = tmp_path / "new.sql"
    metadata = tmp_path / "new.json"
    monkeypatch.setattr(cli, "create_engine", lambda *a, **k: SimpleNamespace(dispose=lambda: None))

    def dump(*a, **k):
        backup.write_bytes(b"complete dump")
        return dict(format=1)

    monkeypatch.setattr(cli, "create_backup", dump)
    original = Path.write_text

    def write(path, *a, **k):
        if path == metadata:
            raise OSError("disk full")
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "write_text", write)
    assert (
        cli.main(
            [
                "backup",
                "--credentials",
                str(credentials),
                "--database",
                "test",
                "--client",
                "mysqldump",
                "--backup",
                str(backup),
                "--metadata",
                str(metadata),
            ]
        )
        == 1
    )
    assert not backup.exists()
    assert not metadata.exists()
