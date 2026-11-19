from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, inspect

from tutor_api.local_schema import upgrade_local_draft_schema

OLD = """
CREATE TABLE attempts (
 id CHAR(36) PRIMARY KEY, session_id CHAR(36) NOT NULL, attempt_no INTEGER NOT NULL,
 status VARCHAR(16) NOT NULL, answer_json JSON, assisted BOOLEAN NOT NULL,
 used_solution BOOLEAN NOT NULL, independent BOOLEAN, evaluation_state VARCHAR(16),
 outcome VARCHAR(24), is_correct BOOLEAN, evaluation_json JSON, request_id VARCHAR(128),
 elapsed_ms INTEGER, submitted_at DATETIME, created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 CONSTRAINT uq_attempt_no UNIQUE(session_id, attempt_no),
 CONSTRAINT uq_attempt_request UNIQUE(request_id)
)
"""


@pytest.fixture
def legacy(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD)
        conn.exec_driver_sql("CREATE TABLE handwriting_drafts (attempt_id TEXT, strokes_json TEXT)")
        conn.exec_driver_sql("CREATE TABLE receipts (raw TEXT)")
        for ident, session, number, status, submitted in [
            ("draft", "s", 1, "draft", None),
            ("later", "s", 2, "submitted", "2026-01-02"),
            ("first", "s", 4, "submitted", "2026-01-01"),
            ("tie", "s", 5, "submitted", "2026-01-02"),
            ("other", "t", 1, "submitted", "2026-01-01"),
        ]:
            conn.exec_driver_sql(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, 0, 0, NULL, NULL, NULL, NULL, ?, ?, NULL, ?, '2026-01-01', '2026-01-01')",
                (
                    ident,
                    session,
                    number,
                    status,
                    '{"unknown_answer":"保留"}',
                    '{"unknown_evaluation":1}',
                    ident,
                    submitted,
                ),
            )
        conn.exec_driver_sql(
            "INSERT INTO handwriting_drafts VALUES ('draft', '{\"unknown_stroke\":[1,2]}')"
        )
        conn.exec_driver_sql("INSERT INTO receipts VALUES ('{\"unknown_raw_receipt\":42}')")
    yield engine
    engine.dispose()


def snapshot(engine):
    with engine.connect() as conn:
        return {
            table: conn.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all()
            for table in ("attempts", "handwriting_drafts", "receipts")
        }


def test_upgrade_preserves_every_existing_value_and_numbers_only_submitted(legacy):
    before = snapshot(legacy)
    upgrade_local_draft_schema(legacy)
    after = snapshot(legacy)
    assert [row[:17] for row in after["attempts"]] == before["attempts"]
    assert after["handwriting_drafts"] == before["handwriting_drafts"]
    assert after["receipts"] == before["receipts"]
    with legacy.connect() as conn:
        assert dict(conn.exec_driver_sql("SELECT id, submission_no FROM attempts").all()) == {
            "draft": None,
            "first": 1,
            "later": 2,
            "tie": 3,
            "other": 1,
        }
    upgrade_local_draft_schema(legacy)
    assert snapshot(legacy) == after


def test_failure_rolls_back_alter_and_backfill(legacy):
    before = snapshot(legacy)

    def fail(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("CREATE UNIQUE INDEX"):
            raise RuntimeError("injected index failure")

    event.listen(legacy, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError, match="injected"):
        upgrade_local_draft_schema(legacy)
    event.remove(legacy, "before_cursor_execute", fail)
    assert len(inspect(legacy).get_columns("attempts")) == 17
    assert snapshot(legacy) == before
    upgrade_local_draft_schema(legacy)


def test_two_startups_serialize_and_reinspect(legacy):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: upgrade_local_draft_schema(legacy), range(2)))
    with legacy.connect() as conn:
        assert (
            conn.exec_driver_sql("SELECT submission_no FROM attempts WHERE id='tie'").scalar_one()
            == 3
        )


def test_partial_schema_is_rejected_without_changes(legacy):
    with legacy.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE attempts ADD COLUMN submission_no INTEGER")
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match="schema"):
        upgrade_local_draft_schema(legacy)
    assert len(inspect(legacy).get_columns("attempts")) == 18
    assert snapshot(legacy) == before


def test_empty_database_is_unchanged(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    upgrade_local_draft_schema(engine)
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_existing_session_rows_get_scoped_lock_index_without_data_changes(legacy):
    with legacy.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE study_sessions (id CHAR(36) PRIMARY KEY, student_id CHAR(36), review_item_id CHAR(36))"
        )
        conn.exec_driver_sql("INSERT INTO study_sessions VALUES ('s', 'owner', 'review')")
    upgrade_local_draft_schema(legacy)
    indexes = {item["name"]: item for item in inspect(legacy).get_indexes("study_sessions")}
    assert indexes["ix_sessions_review_owner"]["column_names"] == [
        "student_id",
        "review_item_id",
        "id",
    ]
    upgrade_local_draft_schema(legacy)
    with legacy.connect() as conn:
        assert conn.exec_driver_sql("SELECT * FROM study_sessions").all() == [
            ("s", "owner", "review")
        ]


def test_unknown_review_scope_index_rolls_back_attempt_changes(legacy):
    with legacy.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE study_sessions (id CHAR(36) PRIMARY KEY, student_id CHAR(36), review_item_id CHAR(36))"
        )
        conn.exec_driver_sql("CREATE INDEX ix_sessions_review_owner ON study_sessions (id)")
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match="review scope"):
        upgrade_local_draft_schema(legacy)
    assert len(inspect(legacy).get_columns("attempts")) == 17
    assert snapshot(legacy) == before


def test_new_schema_missing_unique_index_is_rejected(legacy):
    upgrade_local_draft_schema(legacy)
    with legacy.begin() as conn:
        conn.exec_driver_sql("DROP INDEX uq_attempt_submission")
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match="uniqueness"):
        upgrade_local_draft_schema(legacy)
    assert snapshot(legacy) == before


def test_legacy_schema_with_missing_column_is_rejected(legacy):
    with legacy.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE attempts DROP COLUMN elapsed_ms")
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match="schema"):
        upgrade_local_draft_schema(legacy)
    assert snapshot(legacy) == before


def test_new_orm_schema_is_noop(tmp_path):
    from tutor_api.db import Base
    from tutor_api.models import Attempt

    engine = create_engine(f"sqlite:///{tmp_path / 'new.sqlite3'}")
    Base.metadata.create_all(engine)
    assert "submission_no" in Attempt.__table__.columns
    upgrade_local_draft_schema(engine)
    assert any(
        item["name"] == "uq_attempt_submission"
        for item in inspect(engine).get_unique_constraints("attempts")
    )
    engine.dispose()


def test_old_sqlite_without_window_functions_fails_before_ddl(legacy, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import Connection

    original = Connection.exec_driver_sql

    def execute(conn, statement, *args, **kwargs):
        if statement == "SELECT sqlite_version()":
            return SimpleNamespace(scalar_one=lambda: "3.24.0")
        return original(conn, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "exec_driver_sql", execute)
    before = snapshot(legacy)
    with pytest.raises(RuntimeError, match="window functions"):
        upgrade_local_draft_schema(legacy)
    assert len(inspect(legacy).get_columns("attempts")) == 17
    assert snapshot(legacy) == before
