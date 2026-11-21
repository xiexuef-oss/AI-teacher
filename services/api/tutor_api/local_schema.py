"""Append-only DRAFT-301B upgrade for existing local SQLite files.

This deliberately does not rebuild tables or touch draft payloads/receipts. Unknown
or partially upgraded schemas stop startup so they can be investigated intact.
"""

from sqlalchemy import CHAR, INTEGER, Connection, Engine, inspect

_OLD_COLUMNS = frozenset(
    [
        "id",
        "session_id",
        "attempt_no",
        "status",
        "answer_json",
        "assisted",
        "used_solution",
        "independent",
        "evaluation_state",
        "outcome",
        "is_correct",
        "evaluation_json",
        "request_id",
        "elapsed_ms",
        "submitted_at",
        "created_at",
        "updated_at",
    ]
)
_NEW_COLUMNS = frozenset(("submission_no", "copied_from_attempt_id", "copied_from_revision"))
_OLD_TYPES = {
    "id": "CHAR(36)",
    "session_id": "CHAR(36)",
    "attempt_no": "INTEGER",
    "status": "VARCHAR(16)",
    "answer_json": "JSON",
    "assisted": "BOOLEAN",
    "used_solution": "BOOLEAN",
    "independent": "BOOLEAN",
    "evaluation_state": "VARCHAR(16)",
    "outcome": "VARCHAR(24)",
    "is_correct": "BOOLEAN",
    "evaluation_json": "JSON",
    "request_id": "VARCHAR(128)",
    "elapsed_ms": "INTEGER",
    "submitted_at": "DATETIME",
    "created_at": "DATETIME",
    "updated_at": "DATETIME",
}


def _check_submission_unique(conn: Connection) -> None:
    inspector = inspect(conn)
    definitions = [
        *inspector.get_unique_constraints("attempts"),
        *inspector.get_indexes("attempts"),
    ]
    if not any(
        item["name"] == "uq_attempt_submission"
        and item["column_names"] == ["session_id", "submission_no"]
        and item.get("unique", True)
        and not item.get("dialect_options", {}).get("sqlite_where")
        for item in definitions
    ):
        raise RuntimeError("Unsupported local attempts schema: submission uniqueness missing")


def _upgrade_locked(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("attempts"):
        return
    columns = {item["name"]: item for item in inspector.get_columns("attempts")}
    names = columns.keys()
    if names not in (_OLD_COLUMNS, _OLD_COLUMNS | _NEW_COLUMNS):
        raise RuntimeError("Unsupported or partial local attempts schema; no changes applied")
    if columns["id"]["primary_key"] != 1 or not isinstance(columns["attempt_no"]["type"], INTEGER):
        raise RuntimeError("Unsupported local attempts schema: legacy column definitions")
    if any(str(columns[name]["type"]) != kind for name, kind in _OLD_TYPES.items()):
        raise RuntimeError("Unsupported local attempts schema: legacy column types")
    unique_columns = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("attempts")
    }
    if not {("session_id", "attempt_no"), ("request_id",)} <= unique_columns:
        raise RuntimeError("Unsupported local attempts schema: legacy uniqueness")
    if names == _OLD_COLUMNS | _NEW_COLUMNS:
        for name in _NEW_COLUMNS:
            column = columns[name]
            expected = CHAR if name == "copied_from_attempt_id" else INTEGER
            if not column["nullable"] or not isinstance(column["type"], expected):
                raise RuntimeError("Unsupported local attempts schema: new column definitions")
        source_type = columns["copied_from_attempt_id"]["type"]
        if source_type.length != 36 or not any(
            fk["constrained_columns"] == ["copied_from_attempt_id"]
            and fk["referred_table"] == "attempts"
            and fk["referred_columns"] == ["id"]
            for fk in inspector.get_foreign_keys("attempts")
        ):
            raise RuntimeError("Unsupported local attempts schema: source reference")
        _check_submission_unique(conn)
        return
    version = conn.exec_driver_sql("SELECT sqlite_version()").scalar_one()
    if tuple(int(part) for part in version.split(".")) < (3, 25, 0):
        raise RuntimeError("Local draft upgrade requires SQLite >= 3.25 with window functions")
    conn.exec_driver_sql("ALTER TABLE attempts ADD COLUMN submission_no INTEGER NULL")
    conn.exec_driver_sql(
        "ALTER TABLE attempts ADD COLUMN copied_from_attempt_id CHAR(36) NULL REFERENCES attempts(id)"
    )
    conn.exec_driver_sql("ALTER TABLE attempts ADD COLUMN copied_from_revision INTEGER NULL")
    conn.exec_driver_sql(
        "WITH numbered AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY session_id "
        "ORDER BY submitted_at, attempt_no, id) AS number FROM attempts WHERE status='submitted') "
        "UPDATE attempts SET submission_no=(SELECT number FROM numbered WHERE numbered.id=attempts.id) "
        "WHERE status='submitted'"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX uq_attempt_submission ON attempts (session_id, submission_no)"
    )
    _check_submission_unique(conn)


def upgrade_local_draft_schema(engine: Engine) -> None:
    """Upgrade known legacy SQLite attempts atomically, before metadata.create_all.

    BEGIN IMMEDIATE is explicit: pysqlite legacy transaction mode otherwise leaves
    DDL outside the transaction. Inspect only after obtaining the write lock, so
    concurrent startups observe either the entire old or the entire new schema.
    Non-SQLite engines are left to the managed migration path.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _upgrade_locked(conn)
            _upgrade_profile_revision(conn)
            columns = (
                inspect(conn).get_columns("student_profiles")
                if inspect(conn).has_table("student_profiles")
                else []
            )
            if columns and not any(
                column["name"] == "learning_settings_json" for column in columns
            ):
                conn.exec_driver_sql(
                    "ALTER TABLE student_profiles ADD COLUMN learning_settings_json JSON"
                )
            _upgrade_parent_revisions(conn)
            _upgrade_question_review_revision(conn)
            _ensure_review_session_index(conn)
            _upgrade_review_history(conn)
            _upgrade_paper_ocr_and_corrections(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def _upgrade_paper_ocr_and_corrections(conn: Connection) -> None:
    inspector = inspect(conn)
    for table, column, definition in (
        ("learning_pack_corrections", "before_solution", "BOOLEAN NULL"),
        ("learning_pack_photo_ocr", "pages_json", "JSON NULL"),
    ):
        if inspector.has_table(table) and column not in {
            field["name"] for field in inspector.get_columns(table)
        }:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _upgrade_parent_revisions(conn: Connection) -> None:
    inspector = inspect(conn)
    presence = []
    for table, column in (
        ("student_profiles", "parent_invite_revision"),
        ("parent_student_links", "authorization_revision"),
    ):
        if inspector.has_table(table):
            presence.append(column in {c["name"] for c in inspector.get_columns(table)})
    if len(presence) == 2 and len(set(presence)) != 1:
        raise RuntimeError("Unsupported partial local parent revision schema")
    for table, key, column, initial in (
        ("student_profiles", "user_id", "parent_invite_revision", 0),
        ("parent_student_links", "id", "authorization_revision", 1),
    ):
        inspector = inspect(conn)
        if not inspector.has_table(table):
            continue
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        if key not in columns or columns[key]["primary_key"] != 1:
            raise RuntimeError("Unsupported local parent revision owner schema")
        if column not in columns:
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} BIGINT NOT NULL DEFAULT {initial}"
            )
        else:
            value = columns[column]
            if (
                str(value["type"]) != "BIGINT"
                or value["nullable"]
                or str(value["default"]).strip("'\"()") != str(initial)
            ):
                raise RuntimeError("Unsupported local parent revision column schema")
            if conn.exec_driver_sql(
                f"SELECT 1 FROM {table} WHERE {column} < {initial} OR typeof({column}) != 'integer' LIMIT 1"
            ).first():
                raise RuntimeError("Unsupported local parent revision values")


def _upgrade_profile_revision(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("student_profiles"):
        return
    columns = {c["name"]: c for c in inspector.get_columns("student_profiles")}
    if "user_id" not in columns or columns["user_id"]["primary_key"] != 1:
        raise RuntimeError("Unsupported local profile schema: owner key")
    if "revision" in columns:
        revision = columns["revision"]
        if (
            not isinstance(revision["type"], INTEGER)
            or revision["nullable"]
            or str(revision["default"]).strip("'\"()") != "0"
        ):
            raise RuntimeError("Unsupported local profile revision schema")
        if conn.exec_driver_sql(
            "SELECT 1 FROM student_profiles WHERE revision < 0 OR typeof(revision) != 'integer' LIMIT 1"
        ).first():
            raise RuntimeError("Unsupported local profile revision values")
        return
    conn.exec_driver_sql(
        "ALTER TABLE student_profiles ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
    )


def _ensure_review_session_index(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("study_sessions"):
        return
    expected = ["student_id", "review_item_id", "id"]
    if not set(expected).issubset(
        {column["name"] for column in inspector.get_columns("study_sessions")}
    ):
        raise RuntimeError("Unsupported local review scope: missing session columns")
    indexes = {row["name"]: row for row in inspector.get_indexes("study_sessions")}
    existing = indexes.get("ix_sessions_review_owner")
    if existing is not None:
        if (
            existing["column_names"] != expected
            or existing.get("unique")
            or existing.get("dialect_options", {}).get("sqlite_where")
        ):
            raise RuntimeError("Unsupported local review scope index; no changes applied")
        return
    conn.exec_driver_sql(
        "CREATE INDEX ix_sessions_review_owner ON study_sessions (student_id, review_item_id, id)"
    )


def _upgrade_review_history(conn: Connection) -> None:
    from sqlalchemy import text

    from tutor_api.models import ReviewCompletionRecord

    inspector = inspect(conn)
    if not inspector.has_table("review_items"):
        return
    if inspector.has_table("review_completion_history"):
        table = ReviewCompletionRecord.__table__
        actual = {c["name"]: c for c in inspector.get_columns(table.name)}
        if (
            set(actual) != set(table.columns.keys())
            or any(
                str(actual[c.name]["type"]) != str(c.type)
                or actual[c.name]["nullable"] != c.nullable
                for c in table.columns
            )
            or inspector.get_pk_constraint(table.name)["constrained_columns"]
            != ["review_id", "first_attempt_id"]
        ):
            raise RuntimeError("Unsupported local review completion history schema")
        expected = {
            (fk.parent.name, fk.column.table.name, fk.column.name) for fk in table.foreign_keys
        }
        references = {
            (fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0])
            for fk in inspector.get_foreign_keys(table.name)
        }
        if references != expected:
            raise RuntimeError("Unsupported local review completion history references")
        return
    # The last pointer is evidence only when every resource and grading link agrees.
    invalid = conn.execute(
        text("""
        SELECT r.id FROM review_items r
        LEFT JOIN attempts a ON a.id = r.last_attempt_id
        LEFT JOIN study_sessions s ON s.id = a.session_id
        WHERE r.last_attempt_id IS NOT NULL AND NOT COALESCE(
            s.review_item_id = r.id AND s.student_id = r.student_id
            AND s.question_id = r.question_id AND s.origin = 'review'
            AND a.submission_no = 1 AND a.status = 'submitted'
            AND a.evaluation_state = 'verified'
            AND r.last_result = CASE WHEN a.is_correct = 1 AND a.independent = 1
                THEN 'passed' ELSE 'failed' END, 0)
    """)
    ).first()
    if invalid is not None:
        raise RuntimeError(
            "Unsupported local review completion history: inconsistent last reference"
        )
    ReviewCompletionRecord.__table__.create(conn)
    conn.execute(
        text("""
        INSERT INTO review_completion_history
            (review_id, first_attempt_id, student_id, question_id, state, result, completed_at)
        SELECT r.id, a.id, r.student_id, r.question_id,
            CASE WHEN r.last_attempt_id = a.id THEN 'completed' ELSE 'legacy_unknown' END,
            CASE WHEN r.last_attempt_id = a.id THEN r.last_result ELSE NULL END, NULL
        FROM review_items r
        JOIN study_sessions s ON s.review_item_id = r.id AND s.student_id = r.student_id
            AND s.question_id = r.question_id AND s.origin = 'review'
        JOIN attempts a ON a.session_id = s.id AND a.submission_no = 1
            AND a.status = 'submitted' AND a.evaluation_state = 'verified'
    """)
    )


def _upgrade_question_review_revision(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("questions"):
        return
    columns = {c["name"]: c for c in inspector.get_columns("questions")}
    if "id" not in columns or columns["id"]["primary_key"] != 1:
        raise RuntimeError("Unsupported local question review owner schema")
    if "review_revision" not in columns:
        conn.exec_driver_sql(
            "ALTER TABLE questions ADD COLUMN review_revision BIGINT NOT NULL DEFAULT 1"
        )
        return
    revision = columns["review_revision"]
    if (
        str(revision["type"]) != "BIGINT"
        or revision["nullable"]
        or str(revision["default"]).strip("'\"()") != "1"
    ):
        raise RuntimeError("Unsupported local question review revision schema")
    if conn.exec_driver_sql(
        "SELECT 1 FROM questions WHERE review_revision < 1 OR typeof(review_revision) != 'integer' LIMIT 1"
    ).first():
        raise RuntimeError("Unsupported local question review revision values")
