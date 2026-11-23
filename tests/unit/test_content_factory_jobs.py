from datetime import timedelta

from tutor_api.db import new_id
from tutor_api.models import ContentFactoryJob, LearningJob
from tutor_api.services.content_factory_jobs import RETRY_DELAY, cancel, claim, finish


def test_expired_worker_cannot_finish_or_publish_after_cancellation(db, reviewer, clock):
    now = clock.now()
    job = ContentFactoryJob(
        id=new_id(),
        requested_by=reviewer.user_id,
        kind="analyze_source",
        parameters_json={},
        status="queued",
        available_at=now,
        attempts=0,
    )
    db.add(job)
    db.flush()
    first = claim(db, job.id, now)
    assert first and claim(db, job.id, now) is None
    later = now + timedelta(minutes=10)
    second = claim(db, job.id, later)
    assert second and second != first
    assert not finish(db, job.id, first, later, result={"old": True})
    assert cancel(db, reviewer.user_id, job.id)
    assert not finish(db, job.id, second, later, result={"new": True})
    assert db.get_one(ContentFactoryJob, job.id).status == "cancelled"
    assert db.get_one(ContentFactoryJob, job.id).result_json is None
    assert db.get(LearningJob, job.id) is None


def test_retries_are_delayed_and_only_current_worker_can_store_review_output(db, reviewer, clock):
    now = clock.now()
    job = ContentFactoryJob(
        id=new_id(),
        requested_by=reviewer.user_id,
        kind="analyze_source",
        parameters_json={},
        status="queued",
        available_at=now,
        attempts=0,
    )
    db.add(job)
    db.flush()
    first = claim(db, job.id, now)
    assert first and finish(db, job.id, first, now, retryable=True)
    db.refresh(job)
    assert job.status == "retry_wait"
    assert claim(db, job.id, now) is None
    now += RETRY_DELAY
    second = claim(db, job.id, now)
    assert second and finish(db, job.id, second, now, retryable=True)
    now += RETRY_DELAY
    third = claim(db, job.id, now)
    assert third and finish(db, job.id, third, now, retryable=True)
    db.refresh(job)
    assert job.status == "failed"
    assert claim(db, job.id, now + RETRY_DELAY) is None

    separate = ContentFactoryJob(
        id=new_id(),
        requested_by=reviewer.user_id,
        kind="analyze_source",
        parameters_json={},
        status="queued",
        available_at=now,
        attempts=0,
    )
    db.add(separate)
    db.flush()
    token = claim(db, separate.id, now)
    assert token and finish(db, separate.id, token, now, result={"findings": []})
    db.refresh(separate)
    assert separate.status == "review_required"
    assert separate.result_json == {"findings": []}
