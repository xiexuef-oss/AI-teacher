"""Persistent queue transitions; callers own the surrounding transaction."""

from datetime import datetime, timedelta

from sqlalchemy import and_, case, delete, null, or_, select, update
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import not_found
from tutor_api.models import LearningJob, LearningPackPhotoOcr, LearningPackRenderCheckpoint, User

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=10)
RETRY_DELAY = timedelta(minutes=1)


def _discard_checkpoint(db: Session, job_id: str) -> None:
    db.execute(
        delete(LearningPackRenderCheckpoint).where(LearningPackRenderCheckpoint.job_id == job_id)
    )
    db.execute(
        update(LearningPackPhotoOcr)
        .where(LearningPackPhotoOcr.job_id == job_id, LearningPackPhotoOcr.pages_json.is_not(None))
        .values(pages_json=null())
    )


def enqueue(db: Session, student_id: str, command_key: str, now: datetime) -> str:
    # Serialize the existence check and insert for one owner on both engines.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(User).where(User.id == student_id).values(updated_at=User.updated_at))
    if db.scalar(select(User.id).where(User.id == student_id).with_for_update()) is None:
        raise not_found()
    existing = db.scalar(
        select(LearningJob.id)
        .where(LearningJob.student_id == student_id, LearningJob.command_key == command_key)
        .with_for_update()
    )
    if existing is not None:
        return existing
    job = LearningJob(
        id=new_id(),
        student_id=student_id,
        command_key=command_key,
        status="queued",
        attempts=0,
        available_at=now,
    )
    db.add(job)
    db.flush()
    return job.id


def claim(db: Session, job_id: str, now: datetime) -> str | None:
    expired = and_(LearningJob.status == "running", LearningJob.lease_until <= now)
    row = update(LearningJob).where(LearningJob.id == job_id)
    failed = db.execute(
        row.where(expired, LearningJob.attempts >= MAX_ATTEMPTS).values(
            status="failed", lease_token=None, lease_until=None
        )
    )
    if failed.rowcount == 1:
        _discard_checkpoint(db, job_id)
    token = new_id()
    result = db.execute(
        row.where(
            LearningJob.attempts < MAX_ATTEMPTS,
            or_(
                expired,
                and_(
                    LearningJob.status.in_(("queued", "retry_wait")),
                    LearningJob.available_at <= now,
                ),
            ),
        ).values(
            status="running",
            attempts=LearningJob.attempts + 1,
            lease_until=now + LEASE,
            lease_token=token,
        )
    )
    return token if result.rowcount == 1 else None


def _active_lease(job_id: str, token: str, now: datetime):
    return and_(
        LearningJob.id == job_id,
        LearningJob.status == "running",
        LearningJob.lease_token == token,
        LearningJob.lease_until > now,
    )


def has_active_lease(
    db: Session, job_id: str, token: str, now: datetime, *, lock: bool = False
) -> bool:
    query = select(LearningJob.id).where(_active_lease(job_id, token, now))
    return db.scalar(query.with_for_update() if lock else query) is not None


def finish(
    db: Session,
    job_id: str,
    token: str,
    now: datetime,
    *,
    success: bool,
    retryable: bool = True,
    needs_review: bool = False,
) -> bool:
    if success:
        status = "needs_review" if needs_review else "succeeded"
    elif retryable:
        status = case((LearningJob.attempts >= MAX_ATTEMPTS, "failed"), else_="retry_wait")
    else:
        status = "failed"
    result = db.execute(
        update(LearningJob)
        .where(_active_lease(job_id, token, now))
        .values(status=status, available_at=now + RETRY_DELAY, lease_token=None, lease_until=None)
    )
    if (
        result.rowcount == 1
        and db.scalar(select(LearningJob.status).where(LearningJob.id == job_id)) != "retry_wait"
    ):
        _discard_checkpoint(db, job_id)
    return result.rowcount == 1


def cancel(db: Session, student_id: str, job_id: str) -> bool:
    result = db.execute(
        update(LearningJob)
        .where(
            LearningJob.id == job_id,
            LearningJob.student_id == student_id,
            LearningJob.status.in_(("queued", "retry_wait", "running")),
        )
        .values(status="cancelled", lease_token=None, lease_until=None)
    )
    if result.rowcount == 1:
        _discard_checkpoint(db, job_id)
    return result.rowcount == 1
