from sqlalchemy import create_engine

from tutor_api.local_schema import upgrade_local_draft_schema


def test_paper_schema_upgrade_preserves_existing_transcripts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-paper.sqlite3'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE learning_pack_corrections (job_id CHAR(36), code CHAR(3), "
            "revision INTEGER, transcript TEXT, actor_id CHAR(36), corrected_at DATETIME, "
            "PRIMARY KEY (job_id, code, revision))"
        )
        conn.exec_driver_sql(
            "INSERT INTO learning_pack_corrections VALUES ('pack', '001', 1, 'B', 'student', '2026-11-18')"
        )
        conn.exec_driver_sql(
            "CREATE TABLE learning_pack_photo_ocr (job_id CHAR(36) PRIMARY KEY, pack_id CHAR(36), "
            "code CHAR(3), item_json JSON, photo_ids_json JSON, expires_at DATETIME, candidate TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO learning_pack_photo_ocr (job_id, candidate) VALUES ('ocr', 'B')"
        )

    upgrade_local_draft_schema(engine)
    upgrade_local_draft_schema(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT transcript, before_solution FROM learning_pack_corrections"
        ).one() == ("B", None)
        assert conn.exec_driver_sql(
            "SELECT candidate, pages_json FROM learning_pack_photo_ocr"
        ).one() == ("B", None)
    engine.dispose()
