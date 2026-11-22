"""Isolated real MySQL parent revision upgrade, current reads and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from integration.test_mysql_migrations import mysql_engine  # noqa: F401
from migration_runner import apply_migrations
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from tutor_api.errors import ApiError
from tutor_api.models import ParentStudentLink, StudentProfile
from tutor_api.services import parent_service as service
from tutor_api.settings import Settings

NOW = datetime(2026, 11, 10, tzinfo=UTC)


def initialize(engine):
    migrations = sorted(Path("migrations").glob("*.sql"))
    baseline = [p for p in migrations if p.name < "011_"]
    candidate = Path("migrations/011_parent_authorization_revisions.sql")
    if not candidate.exists():
        candidate = Path("var/draft303c-candidate/011_parent_authorization_revisions.sql")
    apply_migrations(engine, baseline)
    owner, parent, link = [str(uuid4()) for _ in range(3)]
    with engine.begin() as conn:
        for identifier, role in [(owner, "student"), (parent, "parent")]:
            conn.execute(
                text(
                    "INSERT INTO users (id,role,status,created_at,updated_at) VALUES (:id,:role,'active',:now,:now)"
                ),
                {"id": identifier, "role": role, "now": NOW},
            )
        conn.execute(
            text(
                "INSERT INTO student_profiles (user_id,created_at,updated_at) VALUES (:id,:now,:now)"
            ),
            {"id": owner, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO parent_student_links (id,parent_id,student_id,consent_at,created_at) VALUES (:id,:parent,:student,:now,:now)"
            ),
            {"id": link, "parent": parent, "student": owner, "now": NOW},
        )
    assert apply_migrations(engine, [*baseline, candidate]) == [candidate.name]
    assert apply_migrations(engine, [*baseline, candidate]) == []
    # Business calls below use the current ORM, including columns added after 011.
    apply_migrations(
        engine, [*baseline, candidate, *(p for p in migrations if p.name > candidate.name)]
    )
    return owner, parent, link, sessionmaker(engine, expire_on_commit=False)


def create(db, owner, revision):
    return service.create_invite(
        db,
        Settings(),
        owner,
        expected_parent_invite_revision=revision,
        now=NOW,
        request_id="mysql-parent-test",
    )


def test_real_parent_migration_and_stale_rr_generation_current_summary(mysql_engine):  # noqa: F811
    owner, _, link, factory = initialize(mysql_engine)
    with factory() as stale:
        assert stale.get(StudentProfile, owner).parent_invite_revision == 0
        assert stale.get(ParentStudentLink, link).authorization_revision == 1
        with factory() as winner:
            current, _ = create(winner, owner, 0)
            winner.commit()
        with pytest.raises(ApiError) as caught:
            create(stale, owner, 0)
        assert caught.value.code == "parent_invite_revision_conflict"
        assert caught.value.details["server_parent_invite_revision"] == 1
        assert caught.value.details["server_parent_links"]["parent_invite_revision"] == 1
        assert caught.value.details["server_parent_links"]["pending_invite"]["id"] == current.id
        stale.rollback()


def test_real_stale_rr_revoke_cannot_revoke_regrant(mysql_engine):  # noqa: F811
    owner, parent, link, factory = initialize(mysql_engine)
    with factory() as stale:
        assert stale.get(ParentStudentLink, link).authorization_revision == 1
        with factory() as winner:
            service.revoke_link(
                winner, owner, link, expected_authorization_revision=1, now=NOW, request_id="revoke"
            )
            invite, code = create(winner, owner, 0)
            service.redeem_invite(winner, parent, code, now=NOW, request_id="regrant")
            winner.commit()
        with pytest.raises(ApiError) as caught:
            service.revoke_link(
                stale,
                owner,
                link,
                expected_authorization_revision=1,
                now=NOW,
                request_id="old-revoke",
            )
        assert caught.value.code == "authorization_revision_conflict"
        assert caught.value.details["server_link"]["authorization_revision"] == 3
        assert caught.value.details["server_link"]["revoked_at"] is None
        stale.rollback()


def test_real_same_owner_concurrent_generate_one_winner(mysql_engine):  # noqa: F811
    owner, _, _, factory = initialize(mysql_engine)
    barrier = Barrier(2)

    def save(_):
        with factory() as db:
            assert (
                db.scalar(
                    select(StudentProfile.parent_invite_revision).where(
                        StudentProfile.user_id == owner
                    )
                )
                == 0
            )
            barrier.wait(timeout=10)
            try:
                create(db, owner, 0)
                db.commit()
                return "created"
            except ApiError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [0, 1])) == ["created", "parent_invite_revision_conflict"]
