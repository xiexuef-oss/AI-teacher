"""303C: isolated MySQL upgrade, RR current reads, and same-owner CAS."""

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
from tutor_api.models import StudentProfile, User
from tutor_api.schemas import ProfileUpdateIn
from tutor_api.services.profile_service import update_profile

NOW = datetime(2026, 11, 10, tzinfo=UTC)


def initialize(engine):
    paths = sorted(Path("migrations").glob("*.sql"))
    baseline = [p for p in paths if p.name < "010_"]
    profile_upgrade = next(p for p in paths if p.name == "010_profile_revision.sql")
    apply_migrations(engine, baseline)
    owner = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, role, status, created_at, updated_at) VALUES (:id, 'student', 'active', :now, :now)"
            ),
            {"id": owner, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO student_profiles (user_id, created_at, updated_at) VALUES (:id, :now, :now)"
            ),
            {"id": owner, "now": NOW},
        )
    assert apply_migrations(engine, [*baseline, profile_upgrade]) == [profile_upgrade.name]
    apply_migrations(engine, paths)
    assert apply_migrations(engine, paths) == []
    return owner, sessionmaker(engine, expire_on_commit=False)


def body(revision, region="CN-51"):
    return ProfileUpdateIn(expected_revision=revision, region_code=region, subjects=["math"])


def test_real_profile_upgrade_and_rr_identity_map_current_read(mysql_engine):  # noqa: F811
    owner, factory = initialize(mysql_engine)
    with factory() as stale:
        original = stale.get(StudentProfile, owner)
        assert original.revision == 0
        # Establish RR snapshot and cache both rows before the competing commit.
        stale.get(User, owner)
        with factory() as winner:
            update_profile(winner, owner, body(0), now=NOW, request_id="winner")
            winner.commit()
        with pytest.raises(ApiError) as caught:
            update_profile(stale, owner, body(0, "CN-50"), now=NOW, request_id="stale")
        assert caught.value.code == "profile_revision_conflict"
        assert caught.value.details["server_revision"] == 1
        stale.rollback()
    with factory() as check:
        assert check.get(StudentProfile, owner).revision == 1


def test_real_profile_concurrent_same_owner_has_one_winner(mysql_engine):  # noqa: F811
    owner, factory = initialize(mysql_engine)
    barrier = Barrier(2)

    def save(region):
        with factory() as db:
            assert (
                db.scalar(select(StudentProfile.revision).where(StudentProfile.user_id == owner))
                == 0
            )
            barrier.wait(timeout=10)
            try:
                profile = update_profile(db, owner, body(0, region), now=NOW, request_id=region)
                db.commit()
                return profile.revision
            except ApiError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["CN-51", "CN-50"]))
    assert sorted(results, key=str) == [1, "profile_revision_conflict"]
