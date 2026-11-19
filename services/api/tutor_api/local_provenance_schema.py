"""Append-only upgrade of existing local version rows; never backfill provenance."""

from sqlalchemy import JSON, Connection, Engine, inspect


def _upgrade(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("question_versions"):
        return
    columns = {c["name"]: c for c in inspector.get_columns("question_versions")}
    if not {"id", "question_id", "version"} <= columns.keys() or columns["id"]["primary_key"] != 1:
        raise RuntimeError("Unsupported local question version schema")
    if "provenance_json" in columns:
        column = columns["provenance_json"]
        if (
            not isinstance(column["type"], JSON)
            or not column["nullable"]
            or column["default"] is not None
        ):
            raise RuntimeError("Unsupported local provenance column; no changes applied")
        return
    conn.exec_driver_sql("ALTER TABLE question_versions ADD COLUMN provenance_json JSON NULL")


def upgrade_local_provenance_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _upgrade(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
