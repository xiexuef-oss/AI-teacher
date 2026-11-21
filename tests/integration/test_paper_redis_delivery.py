import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import quote
from uuid import uuid4

import pytest
from migration_runner import apply_migrations
from sqlalchemy.orm import sessionmaker
from test_durable_receipts import real_coordinator  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from support.documents import text_pdf
from tutor_api.learning_pack_pdf_store import local_pdf_store
from tutor_api.models import (
    LearningJob,
    LearningPackCommand,
    LearningPackOutbox,
    LearningPackPublication,
    ParentStudentLink,
    SchoolMaterialCommand,
    SchoolMaterialResult,
    User,
    WeeklyReportSnapshot,
)
from tutor_api.s3_blob_store import S3BlobStore
from tutor_api.services.content_seed import seed_if_empty
from tutor_api.services.learning_jobs import enqueue
from tutor_api.services.learning_pack_outbox import RedisPaperQueue, deliver_one
from tutor_api.services.learning_pack_worker import LearningPackWorker, prepare_one


def test_independent_worker_publishes_s3_pair_and_extracts_private_material(request, tmp_path):
    from reportlab import __file__ as reportlab_path

    s3_config = os.environ.get("TUTOR_S3_BLOB_TEST_CONFIG")
    if not s3_config:
        pytest.skip("Explicit isolated S3 test configuration required")
    config = json.loads(Path(s3_config).read_text(encoding="utf-8-sig"))
    assert config.get("test_only") is True
    config["prefix"] = f"tutor-tests/paper-worker/{uuid4().hex}/"
    config_path = tmp_path / "paper-store.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    media_path = tmp_path / "material-store.json"
    media_prefix = config["prefix"] + "material/"
    media_path.write_text(json.dumps({**config, "prefix": media_prefix}), encoding="utf-8")
    engine = request.getfixturevalue("mysql_engine")
    coordinator = request.getfixturevalue("real_coordinator")
    apply_migrations(engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(engine)
    now = datetime.now(UTC).replace(microsecond=0)
    owner = str(uuid4())
    with sessions.begin() as session:
        seed_if_empty(session, now)
        session.add(User(id=owner, role="student", created_at=now, updated_at=now))
        session.flush()
        job_id = enqueue(session, owner, "paper-s3", now)
        session.add(
            LearningPackCommand(
                job_id=job_id,
                input_json={
                    "settings": {"weekly_minutes": 10, "weekdays": [1]},
                    "subjects": ["chemistry"],
                    "school_minutes": 0,
                },
            )
        )
        session.flush()
        session.add(LearningPackOutbox(job_id=job_id, created_at=now))
    redis = coordinator.client.connection_pool.connection_kwargs
    redis_url = (
        f"redis://:{quote(redis['password'], safe='')}@127.0.0.1:{redis['port']}/{redis['db']}"
    )
    store = local_pdf_store(config_path)
    try:
        media = S3BlobStore(
            store.client, bucket=store.bucket, prefix=media_prefix, max_bytes=10485760
        )
        material = text_pdf("Private practice document", "Continuation page")
        expiry = now + timedelta(minutes=10)
        source = media.reserve(
            owner=owner,
            purpose="school_material",
            sha256=sha256(material).hexdigest(),
            size_bytes=len(material),
            mime="application/pdf",
            expires_at=expiry,
            now=now,
        )
        media.put(source.id, owner=owner, data=material, now=now)
        with sessions.begin() as session:
            material_job = enqueue(session, owner, "material-s3", now)
            session.add(SchoolMaterialCommand(job_id=material_job, media_id=source.id))
        with subprocess.Popen(
            [
                sys.executable,
                "tools/run_learning_pack_worker.py",
                "--namespace",
                coordinator.namespace,
            ],
            env={
                **os.environ,
                "TUTOR_ENV": "dev",
                "TUTOR_PSEUDONYM_SECRET": uuid4().hex,
                "TUTOR_DATABASE_URL": engine.url.render_as_string(hide_password=False),
                "TUTOR_LEARNING_PACK_REDIS_URL": redis_url,
                "TUTOR_LEARNING_PACK_PDF_S3_CONFIG": str(config_path),
                "TUTOR_LEARNING_PACK_MEDIA_S3_CONFIG": str(media_path),
                "TUTOR_IMPORT_OCR_MODE": "disabled",
                "TUTOR_LEARNING_PACK_SAMPLE_FONT": str(
                    Path(reportlab_path).parent / "fonts" / "Vera.ttf"
                ),
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as worker:
            try:
                deadline = monotonic() + 25
                while monotonic() < deadline:
                    assert worker.poll() is None
                    with sessions() as session:
                        statuses = [
                            session.get_one(LearningJob, item).status
                            for item in (job_id, material_job)
                        ]
                    if statuses == ["succeeded", "succeeded"]:
                        break
                    assert "failed" not in statuses
                    sleep(0.1)
                else:
                    pytest.fail(f"Independent worker did not complete both jobs: {statuses}")
            finally:
                worker.terminate()
                worker.wait(timeout=10)
        with sessions() as session:
            assert session.get_one(LearningJob, job_id).status == "succeeded"
            assert session.get_one(LearningPackOutbox, job_id).delivered_at is not None
            publication = session.get_one(LearningPackPublication, job_id)
            assert publication.student_pdf == publication.solution_pdf == b""
            manifest = publication.manifest_json
            extracted = session.get_one(SchoolMaterialResult, material_job)
            assert extracted.expires_at == expiry
            assert [page["text"] for page in extracted.pages_json] == [
                "Private practice document",
                "Continuation page",
            ]
        assert set(manifest["pdf_objects"]) == {"student", "solution"}
        for variant, key in manifest["pdf_objects"].items():
            body = store.read(key)
            assert body.startswith(b"%PDF")
            assert sha256(body).hexdigest() == manifest[f"{variant}_sha256"]
        assert (
            RedisPaperQueue(coordinator.client, namespace=coordinator.namespace).receive() is None
        )
    finally:
        config_path.unlink(missing_ok=True)
        media_path.unlink(missing_ok=True)
        page = store.client.list_objects_v2(Bucket=store.bucket, Prefix=store.prefix)
        for item in page.get("Contents", []):
            assert item["Key"].startswith(store.prefix)
            store.client.delete_object(Bucket=store.bucket, Key=item["Key"], IfMatch=item["ETag"])
        store.client.close()


def test_redis_paper_delivery_retries_and_duplicates_are_harmless(request, onboarded, app, clock):
    coordinator = request.getfixturevalue("real_coordinator")
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 0, "weekdays": [1]},
        }
    )
    job = onboarded.data("POST", "/learning/packs", expect=202, json={"school_minutes": 0})
    sessions = app.state.session_factory
    queue = RedisPaperQueue(coordinator.client, namespace=coordinator.namespace)

    def disconnect_after_send(job_id):
        queue.send(job_id)
        raise ConnectionError("Redis reply lost")

    with pytest.raises(ConnectionError, match="reply lost"):
        deliver_one(sessions, clock.now, disconnect_after_send)
    assert deliver_one(sessions, clock.now, queue.send)
    assert not deliver_one(sessions, clock.now, queue.send)
    assert queue.receive() == job["id"]
    assert prepare_one(sessions, clock.now, queued_id=job["id"])
    assert queue.receive() == job["id"]
    assert not prepare_one(sessions, clock.now, queued_id=job["id"])
    assert queue.receive() is None
    assert onboarded.data("GET", f"/learning/jobs/{job['id']}")["status"] == "succeeded"


def test_busy_redis_does_not_starve_database_recovery(request, onboarded, app, clock):
    coordinator = request.getfixturevalue("real_coordinator")
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["chemistry"],
            "learning_settings": {"mode": "boarding", "weekly_minutes": 0, "weekdays": [1]},
        }
    )
    sessions = app.state.session_factory
    queue = RedisPaperQueue(coordinator.client, namespace=coordinator.namespace)
    jobs = []
    for key in ("lost-delivery", "first-delivery", "next-delivery"):
        job = onboarded.data(
            "POST", "/learning/packs", expect=202, key=key, json={"school_minutes": 0}
        )
        jobs.append(job["id"])
        assert deliver_one(sessions, clock.now, queue.send)
        if key == "lost-delivery":
            assert queue.receive() == job["id"]
        clock.advance(1)

    worker = LearningPackWorker(sessions, clock.now, None, queue=queue)
    assert worker.process_paper_once()
    assert worker.process_paper_once()
    with sessions() as session:
        assert [session.get_one(LearningJob, job).status for job in jobs] == [
            "succeeded",
            "succeeded",
            "queued",
        ]
    assert queue.receive() == jobs[-1]


@pytest.mark.parametrize("continuous", [False, True])
def test_mysql_recovers_paper_job_after_redis_message_is_lost(request, continuous):
    engine = request.getfixturevalue("mysql_engine")
    coordinator = request.getfixturevalue("real_coordinator")
    apply_migrations(engine, sorted(Path("migrations").glob("*.sql")))
    sessions = sessionmaker(engine)
    queue = RedisPaperQueue(coordinator.client, namespace=coordinator.namespace)
    now = datetime(2026, 11, 18, tzinfo=UTC)

    def submit(command_key):
        owner = str(uuid4())
        with sessions.begin() as session:
            session.add(User(id=owner, role="student", created_at=now, updated_at=now))
            session.flush()
            job = enqueue(session, owner, command_key, now)
            session.add(
                LearningPackCommand(
                    job_id=job,
                    input_json={
                        "settings": {"weekly_minutes": 0, "weekdays": [1]},
                        "subjects": ["chemistry"],
                        "school_minutes": 0,
                    },
                )
            )
            session.flush()
            session.add(LearningPackOutbox(job_id=job, created_at=now))
        return job

    job = submit("lost-delivery")
    assert deliver_one(sessions, lambda: now, queue.send)
    assert queue.receive() == job
    assert queue.receive() is None
    assert not deliver_one(sessions, lambda: now, queue.send)
    redis = coordinator.client.connection_pool.connection_kwargs
    redis_url = (
        f"redis://:{quote(redis['password'], safe='')}@127.0.0.1:{redis['port']}/{redis['db']}"
    )
    command = [
        sys.executable,
        "tools/run_learning_pack_worker.py",
        "--namespace",
        coordinator.namespace,
    ]
    env = {
        **os.environ,
        "TUTOR_ENV": "dev",
        "TUTOR_PSEUDONYM_SECRET": uuid4().hex,
        "TUTOR_DATABASE_URL": engine.url.render_as_string(hide_password=False),
        "TUTOR_LEARNING_PACK_REDIS_URL": redis_url,
    }
    if continuous:
        # Avoid the pre-07:00 window when the suite happens to run early Monday in Shanghai.
        current = datetime.now(UTC)
        offset = 480
        local = current + timedelta(minutes=offset)
        if local.weekday() == 0 and local.hour < 7:
            offset = -720
            local = current + timedelta(minutes=offset)
        env["TUTOR_REPORT_UTC_OFFSET_MINUTES"] = str(offset)
        week = local.date() - timedelta(days=local.weekday() + 7)
        parent_id = str(uuid4())
        with sessions.begin() as session:
            owner = session.get_one(LearningJob, job).student_id
            consent = min(now, current)
            session.add(User(id=parent_id, role="parent", created_at=consent, updated_at=consent))
            session.flush()
            session.add(
                ParentStudentLink(
                    id=str(uuid4()),
                    parent_id=parent_id,
                    student_id=owner,
                    consent_at=consent,
                    created_at=consent,
                )
            )
        with subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ) as worker:

            def wait_for_success(job_id):
                deadline = monotonic() + 15
                while monotonic() < deadline:
                    assert worker.poll() is None
                    with sessions() as session:
                        if session.get_one(LearningJob, job_id).status == "succeeded":
                            return
                    sleep(0.1)
                pytest.fail("Worker did not complete the paper job")

            try:
                wait_for_success(job)
                later_job = submit("after-start")
                wait_for_success(later_job)
                with sessions() as session:
                    assert session.get_one(LearningPackOutbox, later_job).delivered_at is not None
                    assert session.get_one(WeeklyReportSnapshot, (owner, week, 1)).revision == 1
            finally:
                worker.terminate()
                worker.wait(timeout=10)
    else:
        result = subprocess.run([*command, "--once"], env=env, capture_output=True, timeout=20)
        assert result.returncode == 0
    assert not prepare_one(sessions, lambda: now, queued_id=job)
    with sessions() as session:
        assert session.get_one(LearningJob, job).status == "succeeded"
        assert session.get_one(LearningPackOutbox, job).delivered_at == now
