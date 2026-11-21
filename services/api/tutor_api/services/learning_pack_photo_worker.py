"""Process paper photo OCR jobs under a durable learning-job lease."""

from sqlalchemy import and_, or_, select, update

from tutor_api.blob_store import BlobNotFound
from tutor_api.models import LearningJob, LearningPackPhotoOcr
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.learning_jobs import claim, finish, has_active_lease


def process_photo_ocr(factory, clock, settings, store, gateway):
    now = clock()
    with factory.begin() as db:
        row = db.execute(
            select(LearningJob.id, LearningJob.student_id, LearningPackPhotoOcr)
            .join(LearningPackPhotoOcr, LearningPackPhotoOcr.job_id == LearningJob.id)
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
        job_id, owner, command = row
        photos, expiry = command.photo_ids_json, command.expires_at
        token = claim(db, job_id, now)
    if token is None:
        return False

    def active():
        with factory() as db:
            current = clock()
            return current < expiry and has_active_lease(db, job_id, token, current)

    try:
        transcripts = []
        if (
            settings.import_ocr_mode in {"mock", "configured"}
            and gateway is not None
            and not gateway.external_calls_possible
        ):
            for photo in photos:
                if not active():
                    break
                blob = store.stat(photo, owner=owner, now=clock())
                kind = {"image/png": "png", "image/jpeg": "jpeg"}.get(blob.mime)
                if blob.purpose != "ocr_source" or kind is None:
                    raise BlobNotFound()
                data = store.read(photo, owner=owner, now=clock(), temporary=True)
                pages = [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]
                recognize_pages(
                    pages, data, kind, settings, gateway, parse_isolated, job_id, active
                )
                if pages[0]["method"] == "ocr" and pages[0]["text"].strip():
                    transcripts.append(pages[0]["text"].strip())
        candidate = "\n".join(transcripts) if len(transcripts) == len(photos) else ""
        with factory.begin() as db:
            current = clock()
            valid = current < expiry
            if (
                finish(db, job_id, token, current, success=valid, retryable=False)
                and valid
                and 0 < len(candidate) <= 8000
            ):
                db.get_one(LearningPackPhotoOcr, job_id).candidate = candidate
    except (BlobNotFound, DocumentParseError):
        with factory.begin() as db:
            finish(db, job_id, token, clock(), success=False, retryable=False)
    except Exception:
        with factory.begin() as db:
            current = clock()
            finish(db, job_id, token, current, success=False, retryable=current < expiry)
        raise
    return True


def purge_expired_candidates(factory, now):
    with factory.begin() as db:
        db.execute(
            update(LearningPackPhotoOcr)
            .where(
                LearningPackPhotoOcr.expires_at <= now, LearningPackPhotoOcr.candidate.is_not(None)
            )
            .values(candidate=None)
        )
