"""Local OCR page checkpoints: commit a dispatch marker before invoking the gateway.

This prevents worker recovery from repeating a logical invocation. It does not
replace gateway attempt budgets, billing settlement or provider idempotency.
"""

import hashlib
import json
from copy import deepcopy

from ai_gateway.prompts import build_messages
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob, DocumentImportOcrAttempt
from tutor_api.services.document_extract import DocumentParseError


def request_digest(request):
    value = {
        "request": request.model_dump(mode="json", exclude={"request_id", "trace_id"}),
        "messages": build_messages(request),
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def recovered_page(page, prior, file, digest):
    cached = next((item for item in file.pages_json if item["number"] == page["number"]), None)
    if prior.state == "completed" and prior.request_digest == digest and cached:
        return deepcopy(cached)
    recovered = deepcopy(page)
    recovered["warnings"].append(
        "此前 OCR 调用结果无法可靠恢复，未自动重发，请对照原图人工录入。"
    )
    return recovered


class LocalOcrProgress:
    def __init__(self, factory, clock, job_id, file_id, lease, active, *, gateway):
        self.factory, self.clock = factory, clock
        self.job_id, self.file_id, self.lease = job_id, file_id, lease
        self.active, self.gateway = active, gateway

    def invoke(self, request):
        return self.gateway.invoke(request)

    def _job(self, db) -> DocumentImportJob:
        job = self.active(db, self.job_id, self.lease, self.clock())
        if job is None:
            raise DocumentParseError("import_cancelled", "任务已取消、过期或由另一工作器接管")
        return job

    def begin(self, page, request):
        digest = request_digest(request)
        with self.factory() as db:
            self._job(db)  # Job write lock serializes dispatch with lease takeover/cancellation.
            key = (self.file_id, page["number"])
            prior = db.get(DocumentImportOcrAttempt, key)
            if prior is not None:
                file = db.get(DocumentImportFile, self.file_id)
                return recovered_page(page, prior, file, digest)
            db.add(
                DocumentImportOcrAttempt(
                    file_id=self.file_id,
                    page=page["number"],
                    job_id=self.job_id,
                    lease_id=self.lease,
                    request_digest=digest,
                    trace_id=request.trace_id,
                    state="dispatch_unknown",
                    created_at=self.clock(),
                )
            )
            db.commit()  # No open transaction is held during the gateway call.
        return None

    def complete(self, page):
        with self.factory() as db:
            self._save(db, page)
            db.commit()

    def _save(self, db, page):
        job = self._job(db)
        attempt = db.get(DocumentImportOcrAttempt, (self.file_id, page["number"]))
        if (
            attempt is None
            or attempt.lease_id != self.lease
            or attempt.state != "dispatch_unknown"
        ):
            raise DocumentParseError("import_cancelled", "OCR 页面执行代次已失效")
        file = db.get(DocumentImportFile, self.file_id)
        pages = [item for item in file.pages_json if item["number"] != page["number"]]
        file.pages_json = sorted([*pages, deepcopy(page)], key=lambda item: item["number"])
        attempt.state = "completed"
        job.revision += 1
        job.updated_at = self.clock()
