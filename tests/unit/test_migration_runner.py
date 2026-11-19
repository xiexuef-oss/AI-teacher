import hashlib

import pytest
from migration_runner import MigrationPlanError, plan_migrations


def migration(root, name, sql="SELECT 1;"):
    path = root / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_plan_only_unapplied_files_and_rejects_changed_history(tmp_path):
    first = migration(tmp_path, "001_first.sql")
    second = migration(tmp_path, "002_second.sql")
    applied = [
        {
            "name": first.name,
            "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
            "state": "applied",
        }
    ]
    assert [item.name for item in plan_migrations([second, first], applied)] == [second.name]
    first.write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationPlanError, match="校验和"):
        plan_migrations([first, second], applied)


@pytest.mark.parametrize("state", ["running", "failed"])
def test_dirty_migration_requires_explicit_manual_repair(tmp_path, state):
    first = migration(tmp_path, "001_first.sql")
    record = {
        "name": first.name,
        "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
        "state": state,
    }
    with pytest.raises(MigrationPlanError, match="修复"):
        plan_migrations([first], [record])


def test_missing_applied_file_and_history_gap_are_rejected(tmp_path):
    first = migration(tmp_path, "001_first.sql")
    second = migration(tmp_path, "002_second.sql")
    record = {
        "name": second.name,
        "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
        "state": "applied",
    }
    with pytest.raises(MigrationPlanError, match="顺序"):
        plan_migrations([first, second], [record])
    with pytest.raises(MigrationPlanError, match="缺失"):
        plan_migrations([first], [record])


def test_execution_refuses_non_mysql_without_touching_schema():
    from migration_runner import apply_migrations
    from sqlalchemy import create_engine, inspect

    engine = create_engine("sqlite:///:memory:")
    with pytest.raises(MigrationPlanError, match="MySQL"):
        apply_migrations(engine, [])
    assert inspect(engine).get_table_names() == []


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE proto_private (id INT);",
        "DROP TABLE schema_migration_ledger;",
        "USE other_database;",
        "SET autocommit = 0;",
        "CREATE DATABASE unexpected_database;",
        "CREATE TABLE other_database.outside_table (id INT);",
    ],
)
def test_unsafe_scripts_are_rejected_before_connection(tmp_path, sql):
    from types import SimpleNamespace

    from migration_runner import apply_migrations

    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    path = migration(tmp_path, "001_unsafe.sql", sql)
    with pytest.raises(MigrationPlanError):
        apply_migrations(engine, [path])


def test_cli_without_private_connection_configuration_fails_safely(monkeypatch, capsys):
    import json
    import sys

    from migration_runner import main

    monkeypatch.delenv("TUTOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["migration_runner.py"])
    assert main() == 1
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {"error"}
    assert "mysql://" not in report["error"]
