"""Process paper photo OCR jobs under a durable learning-job lease."""

from sqlalchemy import and_, null, or_, select, update

from ai_gateway.durable import invoke as invoke_durable
from tutor_api.blob_store import BlobNotFound
from tutor_api.gateway_io import pseudonym
from tutor_api.models import LearningJob, LearningPackPhotoOcr
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_ocr import recognize_pages
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.learning_jobs import claim, finish, has_active_lease


class PhotoOcrInvocation:
    def __init__(self, gateway, store, secret, owner, request_id, guard):
        self.gateway, self.store, self.secret = gateway, store, secret
        self.owner, self.request_id, self.guard = owner, request_id, guard

    def begin(self, page, request):
        request.student_pseudonym = pseudonym(self.secret, self.owner)
        request.request_id = self.request_id

    def invoke(self, request):
        return invoke_durable(
            self.gateway, request, self.store, self.secret, context_guard=self.guard
        )

    def complete(self, page):
        pass


def process_photo_ocr(factory, clock, settings, store, gateway, invocation_store=None):
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
        saved_pages = dict(command.pages_json or {})
        token = claim(db, job_id, now)
    if token is None:
        return False

    def active():
        with factory() as db:
            current = clock()
            return current < expiry and has_active_lease(db, job_id, token, current)

    def guard(db):
        if db.get_bind().dialect.name == "sqlite":
            db.execute(
                update(LearningJob)
                .where(LearningJob.id == job_id)
                .values(status=LearningJob.status)
            )
        current = clock()
        if current >= expiry or not has_active_lease(db, job_id, token, current, lock=True):
            raise DocumentParseError("import_cancelled", "当前纸笔识别任务已取消或过期")

    try:
        transcripts = []
        external = (
            settings.import_ocr_mode == "configured"
            and settings.allow_external_model_calls
            and bool(settings.pseudonym_secret)
            and invocation_store is not None
            and gateway is not None
            and gateway.external_calls_possible
        )
        if (
            settings.import_ocr_mode in {"mock", "configured"}
            and gateway is not None
            and (external or not gateway.external_calls_possible)
        ):
            for photo in photos:
                if not active():
                    break
                blob = store.stat(photo, owner=owner, now=clock())
                kind = {"image/png": "png", "image/jpeg": "jpeg"}.get(blob.mime)
                if blob.purpose != "ocr_source" or kind is None:
                    raise BlobNotFound()
                if photo in saved_pages:
                    transcripts.append(saved_pages[photo])
                    continue
                data = store.read(photo, owner=owner, now=clock(), temporary=True)
                pages = [{"number": 1, "text": "", "method": "unavailable", "warnings": []}]
                recognize_pages(
                    pages,
                    data,
                    kind,
                    settings,
                    gateway,
                    parse_isolated,
                    job_id,
                    active,
                    progress=PhotoOcrInvocation(
                        gateway,
                        invocation_store,
                        settings.pseudonym_secret,
                        owner,
                        f"paper-ocr:{job_id}:{photo}",
                        guard,
                    )
                    if external
                    else None,
                )
                if pages[0]["method"] == "ocr" and pages[0]["text"].strip():
                    text = pages[0]["text"].strip()
                    if sum(map(len, transcripts)) + len(transcripts) + len(text) > 8000:
                        break
                    with factory.begin() as db:
                        guard(db)
                        saved_pages[photo] = text
                        db.get_one(LearningPackPhotoOcr, job_id).pages_json = dict(saved_pages)
                    transcripts.append(text)
        candidate = "\n".join(transcripts) if len(transcripts) == len(photos) else ""
        with factory.begin() as db:
            current = clock()
            valid = current < expiry
            if finish(db, job_id, token, current, success=valid, retryable=False):
                command = db.get_one(LearningPackPhotoOcr, job_id)
                command.pages_json = null()
                if valid and candidate:
                    command.candidate = candidate
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
                LearningPackPhotoOcr.expires_at <= now,
                or_(
                    LearningPackPhotoOcr.candidate.is_not(None),
                    LearningPackPhotoOcr.pages_json.is_not(None),
                ),
            )
            .values(candidate=None, pages_json=null())
        )
