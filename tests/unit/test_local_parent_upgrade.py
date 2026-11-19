"""Both parent epochs upgrade in one explicit SQLite transaction."""

import pytest
from sqlalchemy import create_engine, inspect

from tutor_api.local_schema import upgrade_local_draft_schema


def legacy(engine, bad=False):
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE student_profiles (user_id CHAR(36) PRIMARY KEY)")
        c.exec_driver_sql("INSERT INTO student_profiles VALUES ('student')")
        c.exec_driver_sql(
            "CREATE TABLE parent_student_links (id CHAR(36) PRIMARY KEY"
            + (", authorization_revision TEXT DEFAULT '1'" if bad else "")
            + ")"
        )
        c.exec_driver_sql("INSERT INTO parent_student_links (id) VALUES ('link')")


def test_local_parent_upgrade_preserves_rows_and_repeats(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'parents.sqlite3'}")
    legacy(engine)
    upgrade_local_draft_schema(engine)
    upgrade_local_draft_schema(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT user_id,revision,parent_invite_revision FROM student_profiles"
        ).one() == ("student", 0, 0)
        assert c.exec_driver_sql(
            "SELECT id,authorization_revision FROM parent_student_links"
        ).one() == ("link", 1)
    engine.dispose()


def test_local_parent_partial_upgrade_rolls_back_both_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'partial.sqlite3'}")
    legacy(engine, bad=True)
    with pytest.raises(RuntimeError, match="parent revision"):
        upgrade_local_draft_schema(engine)
    assert {c["name"] for c in inspect(engine).get_columns("student_profiles")} == {"user_id"}
    engine.dispose()


def test_local_parent_upgrade_refuses_only_one_existing_epoch(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'one-epoch.sqlite3'}")
    legacy(engine)
    with engine.begin() as c:
        c.exec_driver_sql(
            "ALTER TABLE student_profiles ADD COLUMN parent_invite_revision BIGINT NOT NULL DEFAULT 0"
        )
    with pytest.raises(RuntimeError, match="partial local parent"):
        upgrade_local_draft_schema(engine)
    assert {c["name"] for c in inspect(engine).get_columns("parent_student_links")} == {"id"}
    assert "revision" not in {c["name"] for c in inspect(engine).get_columns("student_profiles")}
    engine.dispose()
