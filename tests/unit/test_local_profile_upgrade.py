"""Profile revision is an atomic append-only upgrade of existing SQLite files."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from tutor_api.local_schema import upgrade_local_draft_schema


def legacy(engine, revision_definition=""):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE student_profiles (user_id CHAR(36) PRIMARY KEY, display_legacy TEXT"
            + revision_definition
            + ")"
        )
        conn.exec_driver_sql(
            "INSERT INTO student_profiles (user_id, display_legacy) VALUES ('owner', 'original')"
        )


def test_local_profile_upgrade_preserves_old_rows_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    legacy(engine)
    upgrade_local_draft_schema(engine)
    upgrade_local_draft_schema(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT user_id, display_legacy, revision FROM student_profiles"
        ).one() == ("owner", "original", 0)
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql("UPDATE student_profiles SET revision=NULL")
    engine.dispose()


@pytest.mark.parametrize(
    "definition", [", revision TEXT NOT NULL DEFAULT '0'", ", revision INTEGER DEFAULT 0"]
)
def test_local_profile_upgrade_refuses_partial_schema(tmp_path, definition):
    engine = create_engine(f"sqlite:///{tmp_path / 'partial.sqlite3'}")
    legacy(engine, definition)
    with engine.connect() as conn:
        before = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='student_profiles'"
        ).scalar_one()
    with pytest.raises(RuntimeError, match="profile"):
        upgrade_local_draft_schema(engine)
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='student_profiles'"
            ).scalar_one()
            == before
        )
    engine.dispose()


def test_profile_upgrade_rolls_back_when_later_upgrade_fails(tmp_path, monkeypatch):
    from tutor_api import local_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.sqlite3'}")
    legacy(engine)

    def fail(_conn):
        raise RuntimeError("injected later failure")

    monkeypatch.setattr(local_schema, "_upgrade_review_history", fail)
    with pytest.raises(RuntimeError, match="injected"):
        upgrade_local_draft_schema(engine)
    assert "revision" not in {c["name"] for c in inspect(engine).get_columns("student_profiles")}
    engine.dispose()
