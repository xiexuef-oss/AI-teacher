"""Real SQLite legacy database upgrades; no provenance backfill or table replacement."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, inspect

from tutor_api import local_provenance_schema


def legacy(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE question_versions (id CHAR(36) PRIMARY KEY, question_id CHAR(36) NOT NULL, version INTEGER NOT NULL, content_json JSON NOT NULL, answer_json JSON NOT NULL, teaching_json JSON NULL, created_by CHAR(36), created_at DATETIME NOT NULL, UNIQUE(question_id,version))"
        )
        c.exec_driver_sql(
            "INSERT INTO question_versions VALUES ('old-version','old-question',7,'{\"stem\":\"legacy text\"}','{\"value\":\"A\"}',NULL,NULL,'2026-01-01 00:00:00')"
        )
    return engine


def test_existing_sqlite_version_rows_stay_null_and_upgrade_is_idempotent(tmp_path):
    engine = legacy(tmp_path)
    try:
        with engine.connect() as c:
            before = c.exec_driver_sql("SELECT * FROM question_versions").one()
        local_provenance_schema.upgrade_local_provenance_schema(engine)
        local_provenance_schema.upgrade_local_provenance_schema(engine)
        with engine.connect() as c:
            after = c.exec_driver_sql("SELECT * FROM question_versions").one()
        assert tuple(after[:-1]) == tuple(before) and after[-1] is None
        column = next(
            c
            for c in inspect(engine).get_columns("question_versions")
            if c["name"] == "provenance_json"
        )
        assert column["nullable"] and column["default"] is None
    finally:
        engine.dispose()


def test_concurrent_local_startups_append_only_one_nullable_column(tmp_path):
    engine = legacy(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(local_provenance_schema.upgrade_local_provenance_schema, engine)
                for _ in range(2)
            ]
            for future in futures:
                future.result(timeout=10)
        assert [c["name"] for c in inspect(engine).get_columns("question_versions")].count(
            "provenance_json"
        ) == 1
        with engine.connect() as c:
            assert c.exec_driver_sql(
                "SELECT version,provenance_json FROM question_versions"
            ).one() == (7, None)
    finally:
        engine.dispose()


def test_append_ddl_is_rolled_back_if_upgrade_fails(tmp_path, monkeypatch):
    engine = legacy(tmp_path)
    original = local_provenance_schema._upgrade

    def fail(conn):
        original(conn)
        raise RuntimeError("injected provenance upgrade failure")

    monkeypatch.setattr(local_provenance_schema, "_upgrade", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            local_provenance_schema.upgrade_local_provenance_schema(engine)
        assert "provenance_json" not in {
            c["name"] for c in inspect(engine).get_columns("question_versions")
        }
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "declaration", ["TEXT NULL", "JSON NOT NULL DEFAULT '{}'", "JSON NULL DEFAULT '{}'"]
)
def test_unknown_existing_column_is_preserved_and_stops_startup(tmp_path, declaration):
    engine = legacy(tmp_path)
    try:
        with engine.begin() as c:
            c.exec_driver_sql(
                f"ALTER TABLE question_versions ADD COLUMN provenance_json {declaration}"
            )
        with pytest.raises(RuntimeError, match="Unsupported"):
            local_provenance_schema.upgrade_local_provenance_schema(engine)
        with engine.connect() as c:
            assert c.exec_driver_sql("SELECT version FROM question_versions").scalar_one() == 7
    finally:
        engine.dispose()


def test_real_local_app_startup_upgrades_a_precolumn_seeded_database(settings, clock):
    from starlette.testclient import TestClient

    from support.api import LOOPBACK
    from tutor_api.main import create_app
    from tutor_api.models import QuestionVersion

    # Reconstruct the genuine pre-013 table in the isolated seeded database.
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE question_versions DROP COLUMN provenance_json")
            before = list(
                conn.exec_driver_sql(
                    "SELECT id,version,content_json FROM question_versions ORDER BY id"
                )
            )
    finally:
        engine.dispose()
    for _ in range(2):
        app = create_app(settings, clock=clock.now)
        with TestClient(app, client=LOOPBACK), app.state.session_factory() as db:
            rows = db.query(QuestionVersion).order_by(QuestionVersion.id).all()
            assert all(row.provenance_json is None for row in rows)
            import json

            assert [(r.id, r.version, r.content_json) for r in rows] == [
                (r.id, r.version, json.loads(r.content_json)) for r in before
            ]
