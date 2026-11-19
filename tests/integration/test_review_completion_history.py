"""303B migration and RR concurrency acceptance on isolated real MySQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from integration.test_draft_submission_migration import seed_legacy
from integration.test_mysql_migrations import mysql_engine  # noqa: F401
from migration_runner import MigrationPlanError, apply_migrations
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from tutor_api.errors import ApiError
from tutor_api.models import ReviewCompletionRecord, ReviewItem
from tutor_api.schemas import ReviewItemOut
from tutor_api.services import review_scheduler
from tutor_api.settings import Settings


def paths():
    candidate = Path(
        os.environ.get(
            "TUTOR_REVIEW_HISTORY_CANDIDATE", "migrations/009_review_completion_history.sql"
        )
    )
    return [*sorted(Path("migrations").glob("00[1-8]_*.sql")), candidate]


def seed(engine, *, last=False, invalid=False):
    with engine.begin() as conn:
        sessions, records = seed_legacy(conn)
        owner, question = conn.execute(
            text("SELECT student_id, question_id FROM study_sessions WHERE id=:s"),
            {"s": sessions[0]},
        ).one()
        review = str(uuid4())
        conn.execute(
            text("""INSERT INTO review_items
            (id, student_id, question_id, status, stage, due_at, last_attempt_id, last_result, created_at, updated_at)
            VALUES (:r, :o, :q, 'scheduled', 0, '2026-01-01', :a, :result, '2026-01-01', '2026-01-01')"""),
            {
                "r": review,
                "o": owner,
                "q": question,
                "a": records[0 if invalid else 7]["id"] if last else None,
                "result": "passed" if last else None,
            },
        )
        conn.execute(
            text(
                "UPDATE study_sessions SET origin='review', review_item_id=:r WHERE student_id=:o"
            ),
            {"r": review, "o": owner},
        )
        for record in records:
            conn.execute(
                text("UPDATE attempts SET submission_no=:n WHERE id=:a"),
                {"n": {3: 1, 5: 2, 2: 3}.get(record["number"]), "a": record["id"]},
            )
        conn.exec_driver_sql(
            "UPDATE attempts SET evaluation_state='verified', is_correct=1, independent=1 WHERE submission_no=1"
        )
        return review, owner, question, records[2]["id"], records[7]["id"]


def test_real_history_upgrade_distinguishes_known_and_unknown(mysql_engine):  # noqa: F811
    migrations = paths()
    apply_migrations(mysql_engine, migrations[:-1])
    review, _, _, first, last = seed(mysql_engine, last=True)
    with mysql_engine.connect() as conn:
        before = conn.exec_driver_sql("SELECT * FROM attempts ORDER BY id").all()
    apply_migrations(mysql_engine, migrations)
    with mysql_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT first_attempt_id, state, result, completed_at FROM review_completion_history WHERE review_id=:r"
            ),
            {"r": review},
        ).all()
        assert set(rows) == {
            (first, "legacy_unknown", None, None),
            (last, "completed", "passed", None),
        }
        assert conn.exec_driver_sql("SELECT * FROM attempts ORDER BY id").all() == before
    assert apply_migrations(mysql_engine, migrations) == []


def test_real_history_upgrade_refuses_invalid_last_without_changing_attempts(mysql_engine):  # noqa: F811
    migrations = paths()
    apply_migrations(mysql_engine, migrations[:-1])
    seed(mysql_engine, last=True, invalid=True)
    with mysql_engine.connect() as conn:
        before = conn.exec_driver_sql("SELECT * FROM attempts ORDER BY id").all()
    with pytest.raises(MigrationPlanError, match="脏版本"):
        apply_migrations(mysql_engine, migrations)
    with mysql_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT * FROM attempts ORDER BY id").all() == before
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM review_completion_history").scalar() == 0


@pytest.mark.parametrize("correct", [True, False])
def test_real_rr_duplicate_first_is_serialized_and_rollback_keeps_history_atomic(
    mysql_engine,  # noqa: F811
    monkeypatch,
    correct,
):  # noqa: F811
    apply_migrations(mysql_engine, paths())
    review, owner, question, first, second = seed(mysql_engine)
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    settings = Settings()
    monkeypatch.setattr(
        review_scheduler,
        "serialize",
        lambda db, item, **kw: ReviewItemOut(
            id=item.id,
            question_id=question,
            question_title="fixture",
            subject="math",
            status=item.status,
            stage=item.stage,
            total_stages=3,
            due_at=item.due_at,
            is_due=item.due_at <= now,
            last_result=item.last_result,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ),
    )
    with mysql_engine.begin() as conn:
        conn.execute(
            text("UPDATE attempts SET is_correct=:correct WHERE id=:a"),
            {"correct": correct, "a": first},
        )

    def complete(db, attempt):
        return review_scheduler.complete(
            db, settings, student_id=owner, review_id=review, attempt_id=attempt, now=now
        )

    with factory() as db:
        complete(db, first)
        db.rollback()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReviewCompletionRecord)) == 0
        assert db.get(ReviewItem, review).stage == 0
    gate = Barrier(2)

    def worker():
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            db.get(ReviewItem, review)  # Establish a stale consistent-read snapshot.
            gate.wait(timeout=8)
            try:
                result = complete(db, first)
                db.commit()
                return result.result
            except ApiError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(outcomes) == sorted(
        ["passed" if correct else "failed", "review_already_completed"]
    )
    now += timedelta(days=7)
    with factory() as db:
        complete(db, second)
        db.commit()
    now += timedelta(days=7)
    with factory() as db:
        with pytest.raises(ApiError) as error:
            complete(db, first)
        assert error.value.code == "review_already_completed"
        db.rollback()
        assert db.scalar(select(func.count()).select_from(ReviewCompletionRecord)) == 2


def test_real_unrelated_first_completions_do_not_gap_deadlock(mysql_engine, monkeypatch):  # noqa: F811
    from sqlalchemy import event

    apply_migrations(mysql_engine, paths())
    cases = [seed(mysql_engine), seed(mysql_engine)]
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    gate = Barrier(2)

    def observe(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith("INSERT IGNORE INTO REVIEW_COMPLETION_HISTORY"):
            gate.wait(timeout=8)

    monkeypatch.setattr(
        review_scheduler,
        "serialize",
        lambda db, item, **kw: ReviewItemOut(
            id=item.id,
            question_id=item.question_id,
            question_title="fixture",
            subject="math",
            status=item.status,
            stage=item.stage,
            total_stages=3,
            due_at=item.due_at,
            is_due=False,
            last_result=item.last_result,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ),
    )

    def worker(case):
        review, owner, _, first, _ = case
        with factory() as db:
            result = review_scheduler.complete(
                db, Settings(), student_id=owner, review_id=review, attempt_id=first, now=now
            )
            db.commit()
            return result.result

    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(worker, cases)) == ["passed", "passed"]
    finally:
        event.remove(mysql_engine, "before_cursor_execute", observe)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReviewCompletionRecord)) == 2
