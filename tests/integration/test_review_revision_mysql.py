"""Real MySQL: an old publish cannot promote a concurrently edited unreviewed v2."""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, current_thread
from uuid import uuid4

from integration.test_mysql_migrations import mysql_engine  # noqa: F401
from migration_runner import apply_migrations
from sqlalchemy.orm import sessionmaker

from support.admin import FAST_KEY, edit_body, make_draft
from tutor_api.errors import ApiError
from tutor_api.models import Question, User
from tutor_api.schemas import AdminQuestionEditIn, ReviewDecisionIn
from tutor_api.services import review_service as service
from tutor_api.services.content_seed import apply_seed, load_seed


def test_real_old_publish_serializes_with_new_content_version(mysql_engine, monkeypatch):  # noqa: F811
    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    reviewer, editor = str(uuid4()), str(uuid4())
    with factory() as db:
        for identifier in (reviewer, editor):
            db.add(
                User(
                    id=identifier, role="reviewer", status="active", created_at=now, updated_at=now
                )
            )
        apply_seed(db, load_seed(), now)
        db.commit()
        identifier = make_draft(db, FAST_KEY)
        service.decide(
            db,
            actor_id=reviewer,
            question_id=identifier,
            body=ReviewDecisionIn(
                decision="approve", expected_version=1, expected_review_revision=1
            ),
            now=now,
            request_id="initial",
        )
        db.commit()
        detail = service.question_detail(db, identifier).model_dump(mode="json")
    edit = AdminQuestionEditIn.model_validate(
        edit_body(detail, title=detail["title"] + " v2", expected_review_revision=2)
    )
    reached, release = Event(), Event()
    original = service._solutions

    def gated(db, question_id, version):
        rows = original(db, question_id, version)
        if (
            current_thread().name.startswith("old-publish")
            and sys._getframe(1).f_code.co_name == "decide"
        ):
            reached.set()
            assert release.wait(timeout=20)
        return rows

    monkeypatch.setattr(service, "_solutions", gated)

    def publish():
        with factory() as db:
            result = service.decide(
                db,
                actor_id=reviewer,
                question_id=identifier,
                body=ReviewDecisionIn(
                    decision="publish", expected_version=1, expected_review_revision=2
                ),
                now=now,
                request_id="publish",
            )
            db.commit()
            return result

    def change():
        with factory() as db:
            try:
                service.create_version(
                    db,
                    actor_id=editor,
                    question_id=identifier,
                    body=edit,
                    now=now,
                    request_id="edit",
                )
                db.commit()
                return "edited"
            except ApiError as error:
                db.rollback()
                return error.code

    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="old-publish") as pub,
        ThreadPoolExecutor(max_workers=1) as edits,
    ):
        pending = pub.submit(publish)
        assert reached.wait(timeout=20)
        editing = edits.submit(change)
        try:
            # A proper Question lock keeps the edit waiting until publish commits.
            Event().wait(0.3)
        finally:
            release.set()
        published = pending.result(timeout=25)
        outcome = editing.result(timeout=25)
    assert published.version == 1
    assert outcome == "review_revision_conflict"
    with factory() as db:
        question = db.get(Question, identifier)
        assert (question.version, question.status, question.review_revision) == (1, "published", 3)


def test_real_review_epoch_upgrade_preserves_old_question(mysql_engine):  # noqa: F811
    from sqlalchemy import text

    paths = sorted(Path("migrations").glob("*.sql"))
    baseline = [p for p in paths if p.name < "012_"]
    apply_migrations(mysql_engine, baseline)
    identifier = str(uuid4())
    with mysql_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO questions (id,subject,type,answer_mode,source_type,source_category,source_license,created_at,updated_at) VALUES (:id,'math','choice','single_choice','self_authored','foundation','probe',NOW(3),NOW(3))"
            ),
            {"id": identifier},
        )
    assert apply_migrations(mysql_engine, paths) == ["012_question_review_revision.sql"]
    assert apply_migrations(mysql_engine, paths) == []
    with mysql_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT review_revision FROM questions WHERE id=:id"), {"id": identifier}
            ).scalar_one()
            == 1
        )


def test_real_publish_reads_current_solution_flags_after_old_rr_snapshot(mysql_engine):  # noqa: F811
    from sqlalchemy import select

    from tutor_api.models import Solution

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    actor = str(uuid4())
    with factory() as db:
        db.add(User(id=actor, role="reviewer", status="active", created_at=now, updated_at=now))
        apply_seed(db, load_seed(), now)
        db.commit()
        identifier = make_draft(db, FAST_KEY)
    with factory() as stale:
        old_standard = stale.scalar(
            select(Solution).where(Solution.question_id == identifier, Solution.kind == "standard")
        )
        assert not old_standard.reviewed
        with factory() as winner:
            service.decide(
                winner,
                actor_id=actor,
                question_id=identifier,
                body=ReviewDecisionIn(
                    decision="approve", expected_version=1, expected_review_revision=1
                ),
                now=now,
                request_id="new-approval",
            )
            winner.commit()
        result = service.decide(
            stale,
            actor_id=actor,
            question_id=identifier,
            body=ReviewDecisionIn(
                decision="publish", expected_version=1, expected_review_revision=2
            ),
            now=now,
            request_id="old-snapshot-publish",
        )
        stale.commit()
        assert result.status == "published"
    with factory() as db:
        question = db.get(Question, identifier)
        assert (question.status, question.review_revision) == ("published", 3)


def test_real_media_confirmation_rejects_old_rr_version_without_audit(mysql_engine):  # noqa: F811
    import hashlib
    from datetime import timedelta
    from types import SimpleNamespace

    from sqlalchemy import func, select

    from support.documents import png_image
    from tutor_api.media_models import MediaAsset
    from tutor_api.models import AuditLog, QuestionVersion
    from tutor_api.schemas import MediaReviewConfirmationIn
    from tutor_api.services import media_service
    from tutor_api.settings import Settings

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    reviewer, editor, media_id = str(uuid4()), str(uuid4()), str(uuid4())
    data = png_image()
    digest = hashlib.sha256(data).hexdigest()
    with factory() as db:
        for identifier in (reviewer, editor):
            db.add(
                User(
                    id=identifier, role="reviewer", status="active", created_at=now, updated_at=now
                )
            )
        apply_seed(db, load_seed(), now)
        db.commit()
        identifier = make_draft(db, FAST_KEY)
        db.add(
            MediaAsset(
                id=media_id,
                owner_id=editor,
                object_key=media_id,
                mime="image/png",
                sha256=digest,
                size_bytes=len(data),
                purpose="question_attachment",
                created_at=now,
            )
        )
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == identifier, QuestionVersion.version == 1
            )
        )
        version.content_json = {
            **version.content_json,
            "attachments": [{"kind": "image", "media_id": media_id, "alt": "工程探针图片"}],
        }
        db.commit()
        detail = service.question_detail(db, identifier).model_dump(mode="json")
    edit = AdminQuestionEditIn.model_validate(edit_body(detail, title=detail["title"] + " v2"))

    class MemoryBlob:
        def read(self, *_args, **_kwargs):
            return data

        def stat(self, *_args, **_kwargs):
            return SimpleNamespace(expires_at=now + timedelta(days=1))

    with factory() as stale:
        assert stale.get(Question, identifier).version == 1  # Establish the old RR snapshot.
        with factory() as winner:
            changed = service.create_version(
                winner,
                actor_id=editor,
                question_id=identifier,
                body=edit,
                now=now,
                request_id="edit-before-declaration",
            )
            assert changed.version == 2
            winner.commit()
        ctx = SimpleNamespace(
            db=stale,
            actor_id=reviewer,
            request_id="stale-media-declaration",
            now=lambda: now,
            settings=Settings(env="local"),
            request=SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(media_store=MemoryBlob()))
            ),
        )
        try:
            media_service.confirm_review(
                ctx,
                identifier,
                media_id,
                MediaReviewConfirmationIn(expected_version=1, sha256=digest, confirmed=True),
            )
        except ApiError as error:
            stale.rollback()
            assert error.status_code == 409
            assert error.code == "version_conflict"
        else:
            stale.commit()
            raise AssertionError(
                "Old RR snapshot admitted a stale v1 media declaration after v2 committed"
            )
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "media.review_confirmed", AuditLog.target_id == identifier
                )
            )
            == 0
        )
