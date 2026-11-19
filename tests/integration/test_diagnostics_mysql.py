"""Real migration, first-row races and RR recovery for fixed diagnostic plans."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from integration.test_mysql_migrations import mysql_engine  # noqa: F401
from migration_runner import apply_migrations
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from tutor_api.db import new_id
from tutor_api.diagnostic_models import DiagnosticItem, DiagnosticRun, DiagnosticState
from tutor_api.errors import ApiError
from tutor_api.models import StudentProfile, StudySession, User
from tutor_api.schemas import DiagnosticCreateIn, DiagnosticRevisionIn
from tutor_api.services import diagnostic_service as service
from tutor_api.services.content_seed import seed_if_empty

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.fixture
def diagnostic_db(mysql_engine):  # noqa: F811
    paths = sorted(Path("migrations").glob("*.sql"))
    old = [path for path in paths if path.name < "016_"]
    apply_migrations(mysql_engine, old)
    assert apply_migrations(mysql_engine, paths) == ["016_diagnostic_plans.sql"]
    assert apply_migrations(mysql_engine, paths) == []
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    owner = new_id()
    with factory() as db:
        seed_if_empty(db, NOW)
        db.add(User(id=owner, role="student", status="active", created_at=NOW, updated_at=NOW))
        db.flush()
        db.add(
            StudentProfile(
                user_id=owner,
                revision=1,
                grade="G10",
                region_code="CN-51",
                subjects_json=["math"],
                exam_year=2027,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        db.commit()
    return owner, factory


def creation(revision=0):
    return DiagnosticCreateIn(
        subject="math", expected_revision=revision, expected_profile_revision=1
    )


def test_mysql_first_row_concurrent_start_has_one_plan(diagnostic_db):
    owner, factory = diagnostic_db
    barrier = Barrier(2)

    def create(_):
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(DiagnosticState)) == 0
            barrier.wait(timeout=10)
            try:
                value = service.create(db, owner, creation(), NOW)
                db.commit()
                return value["revision"]
            except ApiError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2)), key=str) == [1, "diagnostic_revision_conflict"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DiagnosticRun)) == 1
        assert db.scalar(select(func.count()).select_from(DiagnosticItem)) == 3


def test_mysql_concurrent_open_binds_only_one_session(diagnostic_db):
    owner, factory = diagnostic_db
    with factory() as db:
        run = service.create(db, owner, creation(), NOW)["run"]
        db.commit()
    barrier = Barrier(2)

    def open_session(_):
        with factory() as db:
            db.get(DiagnosticState, owner)  # Establish an old RR snapshot.
            barrier.wait(timeout=10)
            try:
                value = service.open_session(
                    db, owner, run["id"], 1, DiagnosticRevisionIn(expected_revision=1), NOW
                )
                db.commit()
                return value.id
            except ApiError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_session, range(2)))
    assert results.count("diagnostic_revision_conflict") == 1
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(StudySession)
                .where(StudySession.student_id == owner)
            )
            == 1
        )
        assert service.workspace(db, owner)["run"]["items"][0]["session_id"] in results


def test_mysql_old_identity_map_cannot_reopen_abandoned_round(diagnostic_db):
    owner, factory = diagnostic_db
    with factory() as db:
        run = service.create(db, owner, creation(), NOW)["run"]
        db.commit()
    with factory() as stale:
        assert stale.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
        assert service.owned_run(stale, owner, run["id"]).abandoned_at is None
        with factory() as winner:
            service.abandon(
                winner, owner, run["id"], DiagnosticRevisionIn(expected_revision=1), NOW
            )
            winner.commit()
        with pytest.raises(ApiError) as error:
            service.open_session(
                stale, owner, run["id"], 1, DiagnosticRevisionIn(expected_revision=2), NOW
            )
        assert error.value.code == "diagnostic_inactive"
        stale.rollback()


def test_mysql_history_keyset_with_equal_creation_times(diagnostic_db):
    owner, factory = diagnostic_db
    ids = []
    with factory() as db:
        revision = 0
        for _ in range(4):
            run = service.create(db, owner, creation(revision), NOW)["run"]
            db.commit()
            ids.append(run["id"])
            result = service.abandon(
                db, owner, run["id"], DiagnosticRevisionIn(expected_revision=revision + 1), NOW
            )
            db.commit()
            revision = result["revision"]
        first = service.history(db, owner, limit=2)
        second = service.history(db, owner, limit=2, cursor=first["next_cursor"])
        assert [run["id"] for run in first["items"] + second["items"]] == sorted(ids, reverse=True)
        assert second["next_cursor"] is None


def test_mysql_export_uses_rr_snapshot_across_concurrent_creation(diagnostic_db):
    from types import SimpleNamespace

    from sqlalchemy import event

    from tutor_api.services import student_learning_export
    from tutor_api.settings import Settings

    owner, factory = diagnostic_db
    engine = factory.kw["bind"]
    created = []

    def another_device(connection, cursor, sql, parameters, context, many):
        if created or "FROM diagnostic_runs" not in sql:
            return
        created.append(None)
        with factory() as writer:
            result = service.create(writer, owner, creation(), NOW)
            writer.commit()
            created[0] = result["run"]["id"]

    event.listen(engine, "after_cursor_execute", another_device)
    try:
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            output = student_learning_export.export(
                SimpleNamespace(
                    db=db,
                    student_id=owner,
                    now=lambda: NOW,
                    settings=Settings(
                        env="staging", pseudonym_secret="self-authored-export-secret"
                    ),
                    request=SimpleNamespace(query_params={}),
                )
            )
            assert output.diagnostic_runs == []
            assert output.diagnostic_workspace == {"revision": 0, "run": None}
    finally:
        event.remove(engine, "after_cursor_execute", another_device)
    assert created and created[0] is not None
    with factory() as db:
        assert service.workspace(db, owner)["run"]["id"] == created[0]


def test_mysql_parent_export_is_owned_and_uses_same_rr_snapshot(diagnostic_db):
    from datetime import timedelta
    from types import SimpleNamespace

    from sqlalchemy import event, update

    from tutor_api.models import ParentInvite, ParentStudentLink
    from tutor_api.services import student_learning_export
    from tutor_api.settings import Settings

    owner, factory = diagnostic_db
    parent, other, link_id, invite_id, foreign_id = [new_id() for _ in range(5)]
    with factory.begin() as db:
        db.add_all(
            [
                User(id=identifier, role=role, status="active", created_at=NOW, updated_at=NOW)
                for identifier, role in ((parent, "parent"), (other, "student"))
            ]
        )
        db.flush()
        db.add(
            ParentStudentLink(
                id=link_id,
                parent_id=parent,
                student_id=owner,
                authorization_revision=1,
                consent_at=NOW,
                created_at=NOW,
            )
        )
        for identifier, student, code in ((invite_id, owner, "a"), (foreign_id, other, "b")):
            db.add(
                ParentInvite(
                    id=identifier,
                    student_id=student,
                    code_hash=code * 64,
                    expires_at=NOW + timedelta(hours=1),
                    created_at=NOW,
                )
            )
    changed = []
    engine = factory.kw["bind"]

    def another_device(connection, cursor, sql, parameters, context, many):
        if changed or "FROM parent_student_links" not in sql:
            return
        changed.append(True)
        with factory.begin() as writer:
            writer.execute(
                update(ParentStudentLink)
                .where(ParentStudentLink.id == link_id)
                .values(revoked_at=NOW + timedelta(minutes=1), authorization_revision=2)
            )
            writer.add(
                ParentInvite(
                    id=new_id(),
                    student_id=owner,
                    code_hash="c" * 64,
                    expires_at=NOW + timedelta(hours=2),
                    created_at=NOW + timedelta(minutes=1),
                )
            )

    event.listen(engine, "after_cursor_execute", another_device)
    try:
        with factory() as db:
            assert db.execute(text("SELECT @@transaction_isolation")).scalar() == "REPEATABLE-READ"
            output = student_learning_export.export(
                SimpleNamespace(
                    db=db,
                    student_id=owner,
                    now=lambda: NOW,
                    settings=Settings(
                        env="staging", pseudonym_secret="self-authored-export-secret"
                    ),
                    request=SimpleNamespace(query_params={}),
                )
            )
            records = output.parent_access_records
            assert records.history_complete is False
            assert len(records.links) == 1 and records.links[0].id == link_id
            assert records.links[0].revoked_at is None
            assert [row.id for row in records.invites] == [invite_id]
            raw = output.model_dump_json()
            assert all(
                secret not in raw for secret in (parent, other, foreign_id, "a" * 64, "b" * 64)
            )
    finally:
        event.remove(engine, "after_cursor_execute", another_device)
    assert changed
    with factory() as db:
        assert db.get(ParentStudentLink, link_id).authorization_revision == 2
        assert (
            len(list(db.scalars(select(ParentInvite).where(ParentInvite.student_id == owner)))) == 2
        )
