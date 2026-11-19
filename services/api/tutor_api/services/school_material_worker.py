"""Local school-material text extraction under a durable learning-job lease."""

from sqlalchemy import and_, delete, or_, select

from tutor_api.blob_store import BlobNotFound
from tutor_api.models import LearningJob, SchoolMaterialCommand, SchoolMaterialResult
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.learning_jobs import claim, finish, has_active_lease


def process_one(factory, clock, settings, store, gateway=None):
    now = clock()
    with factory() as db:
        row = db.execute(
            select(LearningJob.id, LearningJob.student_id, SchoolMaterialCommand.media_id)
            .join(SchoolMaterialCommand, SchoolMaterialCommand.job_id == LearningJob.id)
            .where(
                or_(
                    and_(
                        LearningJob.status.in_(("queued", "retry_wait")),
                        LearningJob.available_at <= now,
                    ),
                    and_(LearningJob.status == "running", LearningJob.lease_until <= now),
                )
            )
            .order_by(LearningJob.available_at, LearningJob.id)
            .limit(1)
        ).one_or_none()
        if row is None:
            return False
        job_id, owner, media_id = row
        token = claim(db, job_id, now)
        db.commit()
    if token is None:
        return False

    expires_at = None
    try:
        blob = store.stat(media_id, owner=owner, now=clock())
        expires_at = blob.expires_at
        if blob.purpose != "school_material":
            raise BlobNotFound()
        data = store.read(media_id, owner=owner, now=clock(), temporary=True)
        kind = {"application/pdf": "pdf", "image/jpeg": "jpeg", "image/png": "png"}[blob.mime]
        extracted = (
            parse_isolated(data, "pdf", settings)["pages"]
            if kind == "pdf"
            else [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]
        )
        if settings.import_ocr_mode == "mock" and gateway is not None:

            def checkpoint():
                with factory() as db:
                    now = clock()
                    return blob.expires_at > now and has_active_lease(db, job_id, token, now)

            recognize_pages(
                extracted, data, kind, settings, gateway, parse_isolated, job_id, checkpoint
            )
        pages = [
            {"page_number": page["number"], "text": page["text"], "needs_ocr": not page["text"]}
            for page in extracted
        ]
        with factory.begin() as db:
            now = clock()
            active_source = blob.expires_at > now
            if (
                finish(db, job_id, token, now, success=active_source, retryable=False)
                and active_source
            ):
                db.add(
                    SchoolMaterialResult(
                        job_id=job_id, pages_json=pages, expires_at=blob.expires_at
                    )
                )
    except BlobNotFound:
        with factory.begin() as db:
            finish(db, job_id, token, clock(), success=False, retryable=False)
    except Exception:
        with factory.begin() as db:
            now = clock()
            finish(
                db,
                job_id,
                token,
                now,
                success=False,
                retryable=expires_at is None or expires_at > now,
            )
        raise
    return True


def purge_expired_results(factory, now):
    with factory.begin() as db:
        db.execute(delete(SchoolMaterialResult).where(SchoolMaterialResult.expires_at <= now))
