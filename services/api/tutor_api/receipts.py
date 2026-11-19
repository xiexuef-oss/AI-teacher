"""Injectable receipt stores. Durable SQL receipts, never Redis, authorize replay."""

from contextlib import contextmanager

from sqlalchemy import event, select

from tutor_api.db import new_id
from tutor_api.errors import conflict
from tutor_api.models import IdempotencyReceipt


class LegacyProtoReceiptStore:
    durable = False

    def lookup(self, ctx, key, digest):
        from tutor_api.proto_models import IdempotencyRecord

        return ctx.db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == ctx.actor_id, IdempotencyRecord.idempotency_key == key
            )
        )

    def validate(self, ctx, digest, fingerprint):
        from tutor_api.proto_models import DocumentImportBatch

        reserved = ctx.db.get(DocumentImportBatch, digest)
        if reserved is not None and reserved.fingerprint != fingerprint:
            raise conflict(
                "idempotency_key_conflict", "同一个 Idempotency-Key 已被用于另一个不同的请求"
            )

    def reserve(self, ctx, key, digest, fingerprint):
        return None

    def finish(self, ctx, reserved, key, digest, fingerprint, status, payload):
        from tutor_api.proto_models import IdempotencyRecord

        ctx.db.add(
            IdempotencyRecord(
                id=new_id(),
                user_id=ctx.actor_id,
                idempotency_key=key,
                fingerprint=fingerprint,
                status_code=status,
                response_json=payload,
                created_at=ctx.now(),
            )
        )

    @contextmanager
    def protect(self, ctx):
        yield


class SqlReceiptStore:
    durable = True

    def lookup(self, ctx, key, digest):
        record = ctx.db.scalar(
            select(IdempotencyReceipt).where(
                IdempotencyReceipt.actor_id == ctx.actor_id, IdempotencyReceipt.key_digest == digest
            )
        )
        if record is not None and (
            record.state != "complete"
            or record.status_code is None
            or not isinstance(record.response_json, dict)
        ):
            raise conflict("conflict", "回执状态不完整，需要检查后重试")
        return record

    def validate(self, ctx, digest, fingerprint):
        if "/admin/import-jobs" in ctx.request.url.path:
            raise RuntimeError("Formal receipts do not support prototype import transactions")

    def reserve(self, ctx, key, digest, fingerprint):
        record = IdempotencyReceipt(
            id=new_id(),
            actor_id=ctx.actor_id,
            key_digest=digest,
            fingerprint=fingerprint,
            state="reserved",
            created_at=ctx.now(),
        )
        ctx.db.add(record)
        ctx.db.flush()  # Unique DB lock precedes the business action, even without Redis.
        return record

    def finish(self, ctx, reserved, key, digest, fingerprint, status, payload):
        reserved.state, reserved.status_code, reserved.response_json = "complete", status, payload
        ctx.db.info["receipt_commit_allowed"] = True

    @contextmanager
    def protect(self, ctx):
        if "receipt_commit_allowed" in ctx.db.info:
            raise RuntimeError("Nested receipt transactions are not supported")
        ctx.db.info["receipt_commit_allowed"] = False

        def guard(session):
            if not session.in_nested_transaction() and not session.info.get(
                "receipt_commit_allowed"
            ):
                raise RuntimeError("Business actions must not commit before receipt completion")

        event.listen(ctx.db, "before_commit", guard)
        try:
            yield
        finally:
            event.remove(ctx.db, "before_commit", guard)
            ctx.db.info.pop("receipt_commit_allowed", None)
