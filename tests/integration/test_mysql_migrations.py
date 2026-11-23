"""Opt-in real MySQL migration tests; create unique databases and never drop existing data."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from migration_runner import LEDGER, MigrationPlanError, apply_migrations, audit_schema
from sqlalchemy import URL, create_engine, text


@pytest.fixture
def mysql_engine():
    config_path = os.environ.get("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS")
    if not config_path:
        pytest.skip("Explicit local migration test credentials required")
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    if config.get("host") != "127.0.0.1" or config.get("port") != 13316:
        pytest.fail("Only the explicitly designated isolated local MySQL server is permitted")
    database = "tutor_migration_runner_" + uuid4().hex[:16]
    url = URL.create(
        "mysql+pymysql",
        username=config["user"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
    )
    admin = create_engine(url, hide_parameters=True)
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
        record_path = Path(config_path).parent / "migration-runner-test-databases.jsonl"
        with record_path.open("a", encoding="utf-8") as record:
            record.write(
                json.dumps({"database": database, "purpose": "isolated migration regression"})
                + "\n"
            )
        engine = create_engine(url.set(database=database), hide_parameters=True)
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        admin.dispose()


def script(tmp_path, name, sql):
    path = tmp_path / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_real_clean_install_current_repository_migrations(mysql_engine):
    paths = sorted(Path("migrations").glob("*.sql"))
    assert apply_migrations(mysql_engine, paths) == [path.name for path in paths]
    report = audit_schema(mysql_engine, paths)
    assert all(row["state"] == "applied" for row in report["history"])
    assert report["pending"] == []
    assert not any(table.startswith("proto_") for table in report["tables"])
    assert apply_migrations(mysql_engine, paths) == []


def test_real_v14_upgrade_and_concurrent_weekly_snapshots(mysql_engine, settings):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, date, datetime
    from threading import Barrier

    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from tutor_api.models import User, WeeklyReportSnapshot
    from tutor_api.services.weekly_snapshots import save_snapshot

    paths = sorted(Path("migrations").glob("*.sql"))
    baseline = [path for path in paths if int(path.name[:3]) <= 16]
    assert apply_migrations(mysql_engine, baseline) == [path.name for path in baseline]
    student_id = str(uuid4())
    now = datetime(2026, 11, 18, tzinfo=UTC)
    week = date(2026, 11, 9)
    sessions = sessionmaker(mysql_engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(User(id=student_id, role="student", created_at=now, updated_at=now))
    assert apply_migrations(mysql_engine, paths) == [path.name for path in paths[len(baseline) :]]
    barrier = Barrier(2)

    def save():
        with sessions.begin() as session:
            barrier.wait(timeout=5)
            return save_snapshot(session, settings, student_id, week, now).revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [pool.submit(save) for _ in range(2)]
        assert [write.result(timeout=15) for write in writes] == [1, 1]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(WeeklyReportSnapshot)) == 1


def test_real_upgrade_and_tampered_history_fail_closed(mysql_engine, tmp_path):
    first = script(tmp_path, "001_first.sql", "CREATE TABLE first_table (id INT PRIMARY KEY);")
    second = script(tmp_path, "002_second.sql", "CREATE TABLE second_table (id INT PRIMARY KEY);")
    assert apply_migrations(mysql_engine, [first]) == [first.name]
    assert apply_migrations(mysql_engine, [first, second]) == [second.name]
    assert apply_migrations(mysql_engine, [first, second]) == []
    first.write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationPlanError, match="校验和"):
        apply_migrations(mysql_engine, [first, second])


@pytest.mark.parametrize("state", ["failed", "running"])
def test_real_partial_ddl_is_dirty_and_never_retried(mysql_engine, tmp_path, state):
    path = script(
        tmp_path,
        "001_partial.sql",
        "CREATE TABLE retained_partial (id INT); INSERT INTO nonexistent_table VALUES (1);",
    )
    with pytest.raises(MigrationPlanError, match="脏版本"):
        apply_migrations(mysql_engine, [path])
    with mysql_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        assert "retained_partial" in [row[0] for row in connection.exec_driver_sql("SHOW TABLES")]
        assert connection.exec_driver_sql(f"SELECT state FROM {LEDGER}").scalar() == "failed"
        connection.execute(text(f"UPDATE {LEDGER} SET state=:state"), {"state": state})
    report = audit_schema(mysql_engine, [path])
    assert not report["ready"] and report["pending"] is None
    assert report["history"][0]["state"] == state
    with pytest.raises(MigrationPlanError, match="修复"):
        apply_migrations(mysql_engine, [path])


def test_real_unmanaged_schema_refused_and_audit_is_read_only(mysql_engine, tmp_path):
    path = script(tmp_path, "001_first.sql", "CREATE TABLE first_table (id INT);")
    with mysql_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("CREATE TABLE existing_legacy_table (id INT)")
    assert audit_schema(mysql_engine, [path])["unmanaged_schema"]
    with pytest.raises(MigrationPlanError, match="自动认领"):
        apply_migrations(mysql_engine, [path])
    assert audit_schema(mysql_engine, [path])["tables"] == ["existing_legacy_table"]


def test_real_connection_lock_blocks_concurrent_runner(mysql_engine, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = script(tmp_path, "001_first.sql", "CREATE TABLE first_table (id INT);")
    with mysql_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        database = connection.exec_driver_sql("SELECT DATABASE()").scalar()
        lock = "tutor-migrations:" + hashlib.sha256(database.encode()).hexdigest()[:32]
        assert connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock}).scalar() == 1
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(apply_migrations, mysql_engine, [path])
                with pytest.raises(MigrationPlanError, match="迁移锁"):
                    future.result(timeout=5)
            assert audit_schema(mysql_engine, [path])["tables"] == []
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock})
    assert apply_migrations(mysql_engine, [path]) == [path.name]


@pytest.mark.parametrize("recover_expired_claim", [False, True])
def test_real_concurrent_workers_publish_only_one_unreturned_pack(
    mysql_engine, monkeypatch, recover_expired_claim
):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    from threading import Event

    from reportlab import __file__ as reportlab_path
    from sqlalchemy.orm import sessionmaker

    from tutor_api.models import LearningPackCommand, LearningPackPublication, User
    from tutor_api.services import learning_pack_worker as worker
    from tutor_api.services.content_seed import seed_if_empty
    from tutor_api.services.learning_jobs import LEASE, enqueue

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(mysql_engine)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    student = str(uuid4())
    with sessions.begin() as session:
        seed_if_empty(session, now)
        session.add(User(id=student, role="student", created_at=now, updated_at=now))
        session.flush()
        jobs = [enqueue(session, student, key, now) for key in ("first", "second")]
        for job in jobs:
            session.add(
                LearningPackCommand(
                    job_id=job,
                    input_json={
                        "settings": {"weekly_minutes": 10, "weekdays": [1]},
                        "subjects": ["chemistry"],
                        "school_minutes": 0,
                    },
                )
            )

    if recover_expired_claim:
        with sessions.begin() as session:
            assert worker.claim(session, jobs[0], now) is not None
        now += LEASE

    publishing = Event()
    second_claimed = Event()
    real_publish = worker.publish
    real_claim = worker.claim

    def publish(*args, **kwargs):
        publishing.set()
        assert second_claimed.wait(timeout=10)
        return real_publish(*args, **kwargs)

    def claim(*args):
        token = real_claim(*args)
        if token and publishing.is_set():
            second_claimed.set()
        return token

    monkeypatch.setattr(worker, "publish", publish)
    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "PAPER_SAMPLES", (("chemistry", "chem-process-reading"),))
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.prepare_one, sessions, lambda: now, font)
        if not publishing.wait(timeout=10):
            first.result(timeout=1)
            pytest.fail("Worker did not reach publication")
        second = pool.submit(worker.prepare_one, sessions, lambda: now, font)
        assert first.result(timeout=15)
        assert second.result(timeout=15)
    with sessions() as session:
        plans = [session.get_one(LearningPackCommand, job).plan_json for job in jobs]
        assert sum(session.get(LearningPackPublication, job) is not None for job in jobs) == 1
        assert sum(plan.get("published", False) for plan in plans) == 1
        assert sum(plan.get("deferred_reason") == "awaiting_return" for plan in plans) == 1


def test_mysql_cancel_committed_during_render_blocks_publication(mysql_engine, monkeypatch):
    from datetime import UTC, datetime

    from reportlab import __file__ as reportlab_path
    from sqlalchemy.orm import sessionmaker

    from tutor_api.models import LearningJob, LearningPackPublication, User
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.learning_jobs import cancel, claim, enqueue

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(mysql_engine)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    owner = str(uuid4())
    with sessions.begin() as session:
        session.add(User(id=owner, role="student", created_at=now, updated_at=now))
        session.flush()
        job = enqueue(session, owner, "cancel-real-render", now)
        token = claim(session, job, now)
        assert token is not None

    render = publication.render_solutions

    def render_then_cancel(*args, **kwargs):
        pdf = render(*args, **kwargs)
        with sessions.begin() as cancellation:
            assert cancel(cancellation, owner, job)
        return pdf

    monkeypatch.setattr(publication, "render_solutions", render_then_cancel)
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    with sessions.begin() as session:
        items = [publication.PrintedQuestion("version-1", "Question", "Solution")]
        assert not publication.publish(session, job, token, items, font, lambda: now)
    with sessions() as session:
        assert session.get_one(LearningJob, job).status == "cancelled"
        assert session.get(LearningPackPublication, job) is None


@pytest.mark.parametrize("kind", [None, "pdf", "png"])
def test_content_factory_worker_processes_authorized_source_in_mysql(mysql_engine, kind):
    import subprocess
    import sys
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import sessionmaker

    from support.documents import png_image, text_pdf
    from tutor_api.gateway_io import DbBudgetStore
    from tutor_api.models import (
        ContentFactoryJob,
        ContentFactorySource,
        ContentFactorySourceOriginal,
        ContentFactorySourcePermission,
        KnowledgeNode,
        User,
    )

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(mysql_engine)
    now = datetime.now(UTC).replace(microsecond=0)
    owner, source_id, job_id = (str(uuid4()) for _ in range(3))
    node_id = str(uuid4())
    content = png_image() if kind == "png" else text_pdf("Quadratic functions")
    with sessions.begin() as db:
        db.add(User(id=owner, role="reviewer", created_at=now, updated_at=now))
        db.flush()
        db.add(
            ContentFactorySource(
                id=source_id,
                title="工程样本",
                source_class="original",
                sha256=hashlib.sha256(content).hexdigest(),
                created_by=owner,
                created_at=now,
            )
        )
        db.flush()
        if kind is not None:
            db.add(
                KnowledgeNode(
                    id=node_id,
                    subject="math",
                    code="math.fixture",
                    title="Quadratic functions",
                    created_at=now,
                )
            )
            db.add(
                ContentFactorySourceOriginal(
                    source_id=source_id,
                    region_code="CN-51",
                    kind=kind,
                    content=content,
                    expires_at=now + timedelta(hours=1),
                )
            )
            db.add_all(
                ContentFactorySourcePermission(
                    source_id=source_id,
                    operation=operation,
                    region_code="CN-51",
                    evidence_ref="integration-license",
                    reviewed_by=owner,
                    valid_from=now,
                    valid_until=now + timedelta(hours=1),
                )
                for operation in ("read", "store_original")
            )
        db.add_all(
            (
                ContentFactorySourcePermission(
                    source_id=source_id,
                    operation="internal_analysis",
                    region_code="CN-51",
                    evidence_ref="integration-license",
                    reviewed_by=owner,
                    valid_from=now,
                    valid_until=now + timedelta(hours=1),
                ),
                ContentFactoryJob(
                    id=job_id,
                    source_id=source_id,
                    requested_by=owner,
                    kind="analyze_source",
                    parameters_json={"region_code": "CN-51"},
                    status="queued",
                    attempts=0,
                    available_at=now,
                ),
            )
        )
    run = subprocess.run(
        [
            sys.executable,
            "tools/run_content_factory_worker.py",
            "--once",
            *(["--mock-ocr"] if kind == "png" else []),
        ],
        env={
            **os.environ,
            "TUTOR_ENV": "dev",
            "TUTOR_PSEUDONYM_SECRET": uuid4().hex,
            "TUTOR_DATABASE_URL": mysql_engine.url.render_as_string(hide_password=False),
        },
        capture_output=True,
        timeout=30,
    )
    assert run.returncode == 0
    with sessions() as db:
        job = db.get_one(ContentFactoryJob, job_id)
        assert (job.status, job.attempts) == ("review_required", 1)
        assert job.result_json["level"] == "metadata"
        if kind == "pdf":
            assert job.result_json["document"] == {
                "pages": 1,
                "text_chars": len("Quadratic functions"),
                "needs_ocr_pages": 0,
                "knowledge_suggestions": [
                    {
                        "knowledge_id": node_id,
                        "title": "Quadratic functions",
                        "subject": "math",
                        "matched_pages": [1],
                    }
                ],
            }
        elif kind == "png":
            assert job.result_json["document"] == {
                "pages": 1,
                "text_chars": 0,
                "needs_ocr_pages": 1,
                "knowledge_suggestions": [],
            }
        else:
            assert "document" not in job.result_json
    learning = DbBudgetStore(sessions, lambda: now)
    research = DbBudgetStore(sessions, lambda: now, namespace="content_factory")
    assert learning.get_requests("platform", "platform", now.date()) == 0
    assert research.get_requests("platform", "platform", now.date()) == (1 if kind == "png" else 0)


def test_mysql_withdraws_paper_source_in_separate_transaction(mysql_engine, monkeypatch):
    from datetime import UTC, datetime

    from reportlab import __file__ as reportlab_path
    from sqlalchemy.orm import sessionmaker

    from tutor_api.models import (
        LearningJob,
        LearningPackCommand,
        LearningPackPublication,
        Question,
        User,
    )
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.content_seed import seed_if_empty, seed_uuid
    from tutor_api.services.learning_jobs import enqueue
    from tutor_api.services.learning_pack_worker import prepare_one

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(mysql_engine)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    owner = str(uuid4())
    with sessions.begin() as session:
        seed_if_empty(session, now)
        second = session.get_one(Question, seed_uuid("question", "chem-conservation-co2"))
        second.status = "withdrawn"
        session.add(User(id=owner, role="student", created_at=now, updated_at=now))
        session.flush()
        job = enqueue(session, owner, "withdraw-source", now)
        session.add(
            LearningPackCommand(
                job_id=job,
                input_json={
                    "settings": {"weekly_minutes": 10, "weekdays": [1]},
                    "subjects": ["chemistry"],
                    "school_minutes": 0,
                },
            )
        )

    render = publication.render_solutions

    def render_then_withdraw(*args, **kwargs):
        pdf = render(*args, **kwargs)
        with sessions.begin() as session:
            source = session.get_one(Question, seed_uuid("question", "chem-process-reading"))
            source.source_license = "withdrawn-for-test"
        return pdf

    monkeypatch.setattr(publication, "render_solutions", render_then_withdraw)
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    assert prepare_one(sessions, lambda: now, font, queued_id=job)
    with sessions() as session:
        assert session.get_one(LearningJob, job).status == "needs_review"
        assert session.get(LearningPackPublication, job) is None


def test_mysql_worker_recovers_committed_render_checkpoint(mysql_engine, monkeypatch):
    import subprocess
    import sys
    from datetime import UTC, datetime

    from reportlab import __file__ as reportlab_path
    from sqlalchemy.orm import sessionmaker

    from tutor_api.models import (
        LearningJob,
        LearningPackCommand,
        LearningPackPublication,
        LearningPackRenderCheckpoint,
        User,
    )
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.content_seed import seed_if_empty
    from tutor_api.services.learning_jobs import LEASE, enqueue
    from tutor_api.services.learning_pack_worker import prepare_one

    apply_migrations(mysql_engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(mysql_engine)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    owner = str(uuid4())
    with sessions.begin() as session:
        seed_if_empty(session, now)
        session.add(User(id=owner, role="student", created_at=now, updated_at=now))
        session.flush()
        job = enqueue(session, owner, "resume-render", now)
        session.add(
            LearningPackCommand(
                job_id=job,
                input_json={
                    "settings": {"weekly_minutes": 10, "weekdays": [1]},
                    "subjects": ["chemistry"],
                    "school_minutes": 0,
                },
            )
        )

    def interrupt(*args, **kwargs):
        raise SystemExit("worker stopped")

    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    worker_code = """
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tutor_api.services import learning_pack_publication
from tutor_api.services.learning_pack_worker import prepare_one

recovering = os.environ['TUTOR_TEST_WORKER_RECOVERING'] == '1'
if recovering:
    learning_pack_publication.render_student = lambda *args, **kwargs: os._exit(85)
else:
    learning_pack_publication.render_solutions = lambda *args, **kwargs: os._exit(83)
engine = create_engine(os.environ['TUTOR_TEST_WORKER_DATABASE'], hide_parameters=True)
completed = prepare_one(
    sessionmaker(engine),
    lambda: datetime.fromisoformat(os.environ['TUTOR_TEST_WORKER_TIME']),
    Path(os.environ['TUTOR_TEST_WORKER_FONT']),
)
os._exit(84 if completed else 86)
"""

    def crash_worker(*, recovering):
        clock = now + LEASE if recovering else now
        return subprocess.run(
            [sys.executable, "-c", worker_code],
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    str(Path(path).resolve()) for path in ("services/api", "services/ai_gateway")
                ),
                "TUTOR_TEST_WORKER_DATABASE": mysql_engine.url.render_as_string(
                    hide_password=False
                ),
                "TUTOR_TEST_WORKER_TIME": clock.isoformat(),
                "TUTOR_TEST_WORKER_FONT": str(font),
                "TUTOR_TEST_WORKER_RECOVERING": "1" if recovering else "0",
            },
            capture_output=True,
            timeout=30,
        ).returncode

    assert crash_worker(recovering=False) == 83
    with sessions() as session:
        checkpoint = session.get_one(LearningPackRenderCheckpoint, job)
        expected = checkpoint.student_pdf, checkpoint.manifest_json
        assert session.get(LearningPackPublication, job) is None

    assert crash_worker(recovering=True) == 84
    with sessions() as session:
        pack = session.get_one(LearningPackPublication, job)
        published = (pack.student_pdf, pack.solution_pdf, pack.manifest_json)
        attempts = session.get_one(LearningJob, job).attempts

    monkeypatch.setattr(publication, "render_student", interrupt)
    assert not prepare_one(sessions, lambda: now + LEASE, font, queued_id=job)
    with sessions() as session:
        pack = session.get_one(LearningPackPublication, job)
        assert (pack.student_pdf, pack.manifest_json["items"]) == expected
        assert (pack.student_pdf, pack.solution_pdf, pack.manifest_json) == published
        assert session.get_one(LearningJob, job).attempts == attempts
        assert session.get(LearningPackRenderCheckpoint, job) is None
