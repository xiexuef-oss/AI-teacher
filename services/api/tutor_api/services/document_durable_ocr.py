"""Opt-in local OCR orchestration using shared durable invocation/budget storage."""

import hashlib
import hmac
from copy import deepcopy
from datetime import UTC, timedelta
from uuid import uuid4

from sqlalchemy import select, update

from ai_gateway.audit import AuditRecord
from tutor_api.gateway_io import pseudonym
from tutor_api.proto_models import DocumentImportFile, DocumentImportJob, DocumentImportOcrAttempt
from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_ocr_progress import (
    LocalOcrProgress,
    recovered_page,
    request_digest,
)
from tutor_api.services.invocation_store import InvocationBudgetExceeded, intents


class DurableOcrProgress(LocalOcrProgress):
    def __init__(self, *args, settings, gateway, store):
        super().__init__(*args, gateway=gateway)
        if not settings.pseudonym_secret:
            raise ValueError("持久OCR需要稳定去标识密钥")
        if self.factory.kw["bind"].url != store.factory.kw["bind"].url:
            raise ValueError("持久OCR与任务数据库不一致")
        self.secret, self.store = settings.pseudonym_secret, store
        self.record, self.plan = None, None

    def _binding(self, purpose, value):
        return hmac.new(
            self.secret.encode(), f"document-ocr:{purpose}:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def begin(self, page, request):
        with self.factory() as db:
            job = self._job(db)
            file = db.get(DocumentImportFile, self.file_id)
            if file is None or file.job_id != self.job_id:
                raise DocumentParseError("import_cancelled", "OCR 文件不属于当前任务")
            request.student_pseudonym = pseudonym(self.secret, job.actor_id)
            digest = request_digest(request)
            slot = self._binding("resource", f"{job.actor_id}:{job.id}:{file.id}:{page['number']}")
            actor = self._binding("actor", job.actor_id)
            file_digest = file.sha256
            value = dict(
                schema_version=2,
                invocation_id=self._binding("invocation", slot)[:32],
                actor_digest=actor,
                budget_key=request.student_pseudonym,
                context_kind="document_ocr",
                resource_digest=slot,
                file_digest=file_digest,
                page=page["number"],
                context_generation=0,
                fingerprint=digest,
                context_digest=digest,
                quota_day=self.clock().astimezone(UTC).date().isoformat(),
                fence=1,
                state="prepared",
                attempts=[],
            )
            prior = db.get(DocumentImportOcrAttempt, (self.file_id, page["number"]))
            cached = recovered_page(page, prior, file, digest) if prior else None
        # End the context transaction before invoking the independent store.
        if cached is not None:
            self._recover(value)
            return cached
        self.record = self.store.prepare(value)
        if self.record["state"] != "prepared":
            self._recover(value)
            return self._manual(page, "此前OCR状态未完成，未自动重发，请人工核对。")
        try:
            self.plan = self.gateway.prepare_single_attempt(request)
        except ValueError:
            self._cancel()
            return self._manual(page, "OCR 路由或预算不可用，请人工录入。")

        def guard(db):
            current = self._job(db)
            current_file = db.get(DocumentImportFile, self.file_id)
            if (
                self._binding("actor", current.actor_id) != actor
                or current_file is None
                or current_file.job_id != self.job_id
                or current_file.sha256 != file_digest
                or db.get(DocumentImportOcrAttempt, (self.file_id, page["number"])) is not None
            ):
                raise DocumentParseError("import_cancelled", "OCR 页面上下文已改变")
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
            db.flush()

        limits = self.gateway._config.budgets
        try:
            self.record = self.store.dispatch(
                value["invocation_id"],
                actor,
                expected_fence=self.record["fence"],
                attempt_id=uuid4().hex,
                estimated_cost_micros=self.plan.estimated_cost_micros,
                request_cost_cap=limits.per_request_max_cost_micros,
                student_limit=limits.student_daily_requests,
                platform_limit=limits.platform_daily_requests,
                student_cost_limit=limits.student_daily_max_cost_micros,
                platform_cost_limit=limits.platform_daily_max_cost_micros,
                context_guard=guard,
                recover_after=self.clock() + timedelta(seconds=self.plan.timeout_s),
            )
        except InvocationBudgetExceeded:
            self._cancel()
            return self._manual(page, "OCR 额度不足，本页未发送，请人工录入。")
        return None

    @staticmethod
    def _manual(page, message):
        result = deepcopy(page)
        result["warnings"].append(message)
        return result

    def _cancel(self):
        self.store.cancel(
            self.record["invocation_id"],
            self.record["actor_digest"],
            expected_fence=self.record["fence"],
        )

    def _recover(self, current):
        record = self.store.read(current["invocation_id"], current["actor_digest"])
        if record is None or record["state"] in (
            "applied",
            "closed_unknown",
            "stale",
            "cancelled_unsent",
        ):
            return
        with self.factory.begin() as db:
            self._job(db)  # The recovery owner takes the job lock before the intent.
            row = (
                db.execute(
                    select(intents)
                    .where(
                        intents.c.id == current["invocation_id"],
                        intents.c.actor_digest == current["actor_digest"],
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] in (
                "applied",
                "closed_unknown",
                "stale",
                "cancelled_unsent",
            ):
                return
            record = row["metadata_json"]
            stale = record["context_digest"] != current["context_digest"]
            if not stale and record["state"] == "prepared":
                return
            if not stale and record["state"] == "dispatch_unknown":
                record = self.store.transitions.mark_unknown(record, expected_fence=record["fence"])
                changed = db.execute(
                    update(intents)
                    .where(
                        intents.c.id == current["invocation_id"],
                        intents.c.actor_digest == current["actor_digest"],
                        intents.c.state == "dispatch_unknown",
                        intents.c.fence == record["fence"],
                    )
                    .values(state=record["state"], metadata_json=record)
                )
                if changed.rowcount != 1:
                    raise ValueError("OCR invocation changed concurrently")
            self.store.applied_in_transaction(
                db,
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=record["fence"],
                context_digest=current["context_digest"],
                retire_stale=stale,
                close_unknown=not stale and record["state"] == "outcome_unknown",
            )

    def invoke(self, request):
        response = self.gateway.invoke_single_attempt(self.plan)
        if response.provider_calls != 1:
            self.record = self.store.mark_unknown(
                self.record["invocation_id"],
                self.record["actor_digest"],
                expected_fence=self.record["fence"],
            )
            return response.model_copy(update={"validated_output": None, "status": "degraded"})
        audit = AuditRecord(
            request_id=request.request_id,
            trace_id=response.trace_id,
            student_pseudonym=request.student_pseudonym,
            task_type="ocr_extract",
            provider=response.provider,
            model_id=response.model_id,
            status=response.status,
            error_code=response.error_code,
            provider_calls=1,
            latency_ms=response.latency_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            image_units=response.usage.image_units,
            estimated_cost_micros=response.usage.estimated_cost_micros,
            schema_valid=True if response.status == "ok" else None,
            review_required=response.review_required,
            created_at=self.clock(),
        )
        self.record = self.store.settle_metadata(
            self.record["invocation_id"],
            self.record["actor_digest"],
            expected_fence=self.record["fence"],
            attempt_id=self.record["attempts"][0]["attempt_id"],
            audit=audit,
        )
        if (response.usage.estimated_cost_micros or 0) > self.plan.estimated_cost_micros:
            return response.model_copy(
                update={
                    "validated_output": None,
                    "status": "degraded",
                    "error_code": "BUDGET_EXCEEDED",
                }
            )
        return response

    def complete(self, page):
        try:
            self._complete(page)
        except DocumentParseError:
            self._retire_invalid()
            raise

    def _complete(self, page):
        with self.factory() as db:
            self._save(db, page)
            self.store.applied_in_transaction(
                db,
                self.record["invocation_id"],
                self.record["actor_digest"],
                expected_fence=self.record["fence"],
                context_digest=self.record["context_digest"],
                close_unknown=self.record["state"] == "outcome_unknown",
            )
            db.commit()

    def _retire_invalid(self):
        with self.factory.begin() as db:
            job = db.scalar(
                select(DocumentImportJob)
                .where(DocumentImportJob.id == self.job_id)
                .with_for_update()
            )
            if (
                job is not None
                and job.status == "processing"
                and job.lease_id == self.lease
                and job.expires_at > self.clock()
                and job.lease_until > self.clock()
            ):
                return
            row = (
                db.execute(
                    select(intents)
                    .where(
                        intents.c.id == self.record["invocation_id"],
                        intents.c.actor_digest == self.record["actor_digest"],
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] not in (
                "prepared",
                "dispatch_unknown",
                "outcome_unknown",
                "settled_metadata",
            ):
                return
            record = row["metadata_json"]
            invalid_digest = hashlib.sha256(
                ("document-ocr:invalid-context:" + record["context_digest"]).encode()
            ).hexdigest()
            self.store.applied_in_transaction(
                db,
                record["invocation_id"],
                record["actor_digest"],
                expected_fence=record["fence"],
                context_digest=invalid_digest,
                retire_stale=True,
            )
