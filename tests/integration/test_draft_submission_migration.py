"""DRAFT-301B: submission order upgrades use isolated, explicitly opted-in MySQL."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from integration.test_mysql_migrations import mysql_engine  # noqa: F401
from migration_runner import apply_migrations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from verify_migrations import _load_orm_metadata, load_migration_schema, orm_drift


def migration_paths():
    # Allows validating a candidate outside immutable migrations/ before publishing it.
    candidate = Path(
        os.environ.get(
            "TUTOR_DRAFT_MIGRATION_CANDIDATE", "migrations/007_attempt_submission_order.sql"
        )
    )
    assert candidate.is_file(), "DRAFT-301B submission migration is missing"
    return [*sorted(Path("migrations").glob("00[1-6]_*.sql")), candidate]


def test_submission_migration_static_schema_and_orm(tmp_path):
    paths = (
        migration_paths()
        if os.environ.get("TUTOR_DRAFT_MIGRATION_CANDIDATE")
        else sorted(Path("migrations").glob("*.sql"))
    )
    for path in paths:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    schema = load_migration_schema(tmp_path)
    assert {"submission_no", "copied_from_attempt_id", "copied_from_revision"} <= set(
        schema["attempts"]
    )
    assert orm_drift(schema, _load_orm_metadata()) == []


def seed_legacy(connection):
    student, question = str(uuid4()), str(uuid4())
    connection.execute(
        text(
            "INSERT INTO users (id, role, created_at, updated_at) VALUES (:id, 'student', NOW(3), NOW(3))"
        ),
        {"id": student},
    )
    connection.execute(
        text("""INSERT INTO questions
            (id, subject, type, answer_mode, source_type, source_category, source_license,
             created_at, updated_at)
            VALUES (:id, 'math', 'choice', 'choice', 'self_authored', 'foundation',
                    'test', NOW(3), NOW(3))"""),
        {"id": question},
    )
    sessions = [str(uuid4()), str(uuid4())]
    for session in sessions:
        connection.execute(
            text("""INSERT INTO study_sessions
                (id, student_id, question_id, question_version, state, origin, created_at, updated_at)
                VALUES (:id, :student, :question, 1, 'INDEPENDENT', 'practice', NOW(3), NOW(3))"""),
            {"id": session, "student": student, "question": question},
        )
    records = []
    for session in sessions:
        # Drafts precede and interrupt submissions; creation order reverses submission time.
        for number, submitted in enumerate(
            [None, "2026-01-02", "2026-01-01", None, "2026-01-01"], 1
        ):
            record = {
                "id": str(uuid4()),
                "session": session,
                "number": number,
                "submitted": submitted,
                "status": "submitted" if submitted else "draft",
            }
            connection.execute(
                text("""INSERT INTO attempts
                    (id, session_id, attempt_no, status, submitted_at, answer_json,
                     evaluation_state, created_at, updated_at)
                    VALUES (:id, :session, :number, :status, :submitted, '{"legacy": true}',
                            'pending', NOW(3), NOW(3))"""),
                record,
            )
            records.append(record)
    return sessions, records


def test_real_submission_upgrade_preserves_data_and_orders_submissions(mysql_engine):  # noqa: F811
    paths = migration_paths()
    apply_migrations(mysql_engine, paths[:-1])
    assert "submission_no" not in {c["name"] for c in inspect(mysql_engine).get_columns("attempts")}
    with mysql_engine.begin() as connection:
        sessions, records = seed_legacy(connection)
        before = connection.exec_driver_sql("SELECT * FROM attempts ORDER BY id").mappings().all()
    assert apply_migrations(mysql_engine, paths) == [paths[-1].name]
    with mysql_engine.connect() as connection:
        after = connection.exec_driver_sql("SELECT * FROM attempts ORDER BY id").mappings().all()
    for old, new in zip(before, after, strict=True):
        assert {key: new[key] for key in old} == dict(old)
        assert new["copied_from_attempt_id"] is None
        assert new["copied_from_revision"] is None
        assert new["submission_no"] == ({3: 1, 5: 2, 2: 3}.get(old["attempt_no"]))
    assert apply_migrations(mysql_engine, paths) == []
    with mysql_engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT * FROM attempts ORDER BY id").mappings().all()
            == after
        )
    # NULL values coexist, while a repeated number in the same session is rejected.
    with pytest.raises(IntegrityError), mysql_engine.begin() as connection:
        connection.execute(
            text("UPDATE attempts SET submission_no=1 WHERE id=:id"), {"id": records[0]["id"]}
        )
    # Provenance is nullable, accepts revision zero and points to an existing attempt.
    with mysql_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attempts SET copied_from_attempt_id=:source, copied_from_revision=0 WHERE id=:id"
            ),
            {"source": records[0]["id"], "id": records[3]["id"]},
        )
    with pytest.raises(IntegrityError), mysql_engine.begin() as connection:
        connection.execute(
            text("UPDATE attempts SET copied_from_attempt_id=:source WHERE id=:id"),
            {"source": str(uuid4()), "id": records[3]["id"]},
        )
    assert len(sessions) == 2


def test_real_submission_clean_install(mysql_engine):  # noqa: F811
    paths = migration_paths()
    assert apply_migrations(mysql_engine, paths) == [path.name for path in paths]
    columns = {column["name"]: column for column in inspect(mysql_engine).get_columns("attempts")}
    for name in ("submission_no", "copied_from_attempt_id", "copied_from_revision"):
        assert columns[name]["nullable"]
    assert any(
        index["unique"] and index["column_names"] == ["session_id", "submission_no"]
        for index in inspect(mysql_engine).get_indexes("attempts")
    )
    assert apply_migrations(mysql_engine, paths) == []
