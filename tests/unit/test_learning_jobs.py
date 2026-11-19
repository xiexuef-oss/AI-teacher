from datetime import UTC, datetime, timedelta

from tutor_api.models import LearningJob
from tutor_api.services.learning_jobs import cancel, claim, enqueue, finish

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def test_duplicate_enqueue_and_expired_lease(db, student):
    job = enqueue(db, student.user_id, "pack-1", NOW)
    assert enqueue(db, student.user_id, "pack-1", NOW) == job
    first = claim(db, job, NOW)
    assert first is not None
    assert claim(db, job, NOW) is None
    later = NOW + timedelta(minutes=11)
    second = claim(db, job, later)
    assert second is not None and second != first
    assert not finish(db, job, first, later, success=True)
    assert finish(db, job, second, later, success=True)
    assert claim(db, job, later) is None


def test_retry_delay_and_owner_scoped_cancel(db, student):
    job = enqueue(db, student.user_id, "pack-2", NOW)
    lease = claim(db, job, NOW)
    assert lease is not None
    assert finish(db, job, lease, NOW, success=False)
    assert claim(db, job, NOW) is None
    later = NOW + timedelta(minutes=1)
    lease = claim(db, job, later)
    assert lease is not None
    assert not cancel(db, "other-owner", job)
    assert cancel(db, student.user_id, job)
    assert not finish(db, job, lease, later, success=True)


def test_crashes_exhaust_attempts_across_transactions(db, student):
    job = enqueue(db, student.user_id, "pack-3", NOW)
    db.commit()
    for attempt in range(3):
        assert claim(db, job, NOW + timedelta(minutes=11 * attempt)) is not None
        db.commit()

    assert claim(db, job, NOW + timedelta(minutes=33)) is None
    db.commit()
    stored = db.get(LearningJob, job)
    assert stored.status == "failed"
    assert stored.attempts == 3
    assert stored.lease_token is None
