from pathlib import Path

from migration_runner import apply_migrations
from sqlalchemy import inspect
from test_mysql_migrations import mysql_engine  # noqa: F401


def test_review_owner_scope_index_matches_deterministic_lock_order(mysql_engine):  # noqa: F811
    paths = sorted(Path("migrations").glob("*.sql"))
    apply_migrations(mysql_engine, paths)
    indexes = {row["name"]: row for row in inspect(mysql_engine).get_indexes("study_sessions")}
    assert "ix_sessions_review_owner" in indexes
    scoped = indexes["ix_sessions_review_owner"]
    assert scoped["column_names"] == ["student_id", "review_item_id", "id"]
    assert not scoped["unique"]
    assert apply_migrations(mysql_engine, paths) == []
