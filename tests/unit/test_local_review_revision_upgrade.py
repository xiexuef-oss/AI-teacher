import pytest
from sqlalchemy import create_engine, inspect

from tutor_api import local_schema


def test_review_epoch_upgrade_preserves_rows_and_repeats(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite3'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE questions (id CHAR(36) PRIMARY KEY, version INTEGER)")
        conn.exec_driver_sql("INSERT INTO questions VALUES ('old', 7)")
    local_schema.upgrade_local_draft_schema(engine)
    local_schema.upgrade_local_draft_schema(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT id,version,review_revision FROM questions").one() == ("old", 7, 1)
    engine.dispose()


def test_review_epoch_ddl_rolls_back_if_later_upgrade_fails(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.sqlite3'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE questions (id CHAR(36) PRIMARY KEY)")

    def fail(_conn):
        raise RuntimeError("injected later upgrade failure")

    monkeypatch.setattr(local_schema, "_ensure_review_session_index", fail)
    with pytest.raises(RuntimeError, match="injected"):
        local_schema.upgrade_local_draft_schema(engine)
    assert "review_revision" not in {c["name"] for c in inspect(engine).get_columns("questions")}
    engine.dispose()
