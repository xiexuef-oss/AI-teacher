"""Publish committed paper jobs; the database remains responsible for claiming them."""

from sqlalchemy import select

from tutor_api.models import LearningPackOutbox


class RedisPaperQueue:
    def __init__(self, client, *, namespace: str):
        self.client = client
        self.key = f"{namespace}:learning-packs"

    def send(self, job_id: str) -> None:
        self.client.lpush(self.key, job_id)

    def receive(self) -> str | None:
        job_id = self.client.rpop(self.key)
        return job_id.decode("ascii") if isinstance(job_id, bytes) else job_id


def deliver_one(factory, clock, send) -> bool:
    with factory.begin() as db:
        pending = db.scalar(
            select(LearningPackOutbox)
            .where(LearningPackOutbox.delivered_at.is_(None))
            .order_by(LearningPackOutbox.created_at, LearningPackOutbox.job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if pending is None:
            return False
        send(pending.job_id)
        pending.delivered_at = clock()
    return True
