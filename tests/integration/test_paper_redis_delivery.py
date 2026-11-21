import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import quote
from uuid import uuid4

import pytest
from migration_runner import apply_migrations
from sqlalchemy.orm import sessionmaker
from test_durable_receipts import real_coordinator  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401

from tutor_api.models import (
    LearningJob,
    LearningPackCommand,
    LearningPackOutbox,
    ParentStudentLink,
    User,
    WeeklyReportSnapshot,
)
from tutor_api.services.learning_jobs import enqueue
from tutor_api.services.learning_pack_outbox import RedisPaperQueue, deliver_one
from tutor_api.services.learning_pack_worker import LearningPackWorker, prepare_one


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
