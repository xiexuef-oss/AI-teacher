"""逐题事务的持久化批次；成功映射和草稿一起提交，不依赖 HTTP 响应送达。"""

from pydantic import ValidationError
from sqlalchemy import select, update

from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.idempotency import read_key, request_fingerprint
from tutor_api.proto_models import DocumentImportBatch, DocumentImportCandidate, IdempotencyRecord
from tutor_api.schemas import AdminQuestionImportIn
from tutor_api.services import document_import_service as workspace
from tutor_api.services.question_provenance import document_origins
from tutor_api.services.review_service import import_draft


def submit(ctx, job_id, body, digest):
    job = workspace.owned_job(ctx, job_id)
    batch = ctx.db.get(DocumentImportBatch, digest)
    if batch is None:
        workspace.require_state(job, {"needs_review", "partial_failure", "completed", "failed"})
        if ctx.db.scalar(
            select(DocumentImportBatch.key_digest).where(
                DocumentImportBatch.job_id == job_id, DocumentImportBatch.completed.is_(False)
            )
        ):
            raise conflict("batch_in_progress", "存在未完成批次，请复用原幂等键恢复")
        candidates = {item.id for item in workspace.job_candidates(ctx.db, job_id)}
        if any(id not in candidates for id in body.candidate_ids):
            raise unprocessable("candidate_ids", "候选题不属于当前任务")
        workspace.advance(ctx, job, body.expected_revision)
        # advance 已取得 SQLite 写锁；再次核对全局键，避免检查到领取之间被其他操作抢占。
        claimed = ctx.db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == ctx.actor_id,
                IdempotencyRecord.idempotency_key == read_key(ctx),
            )
        )
        if claimed is not None:
            raise conflict("idempotency_key_conflict", "幂等键已由另一请求提交，请重新读取结果")
        batch = DocumentImportBatch(
            key_digest=digest,
            job_id=job_id,
            fingerprint=request_fingerprint(ctx, body),
            items_json=[],
            response_json=None,
            completed=False,
            created_at=ctx.now(),
        )
        ctx.db.add(batch)
        workspace.audit(ctx, job, "submit_start", {"count": len(body.candidate_ids)})
        ctx.db.commit()
    elif batch.fingerprint != request_fingerprint(ctx, body):
        raise conflict("idempotency_key_conflict", "幂等键已用于不同请求")
    if batch.completed:
        return batch.response_json
    for candidate_id in body.candidate_ids:
        # 先取得写事务，序列化同一批次的并发重试以及取消/编辑。
        locked = ctx.db.execute(
            update(DocumentImportBatch)
            .where(DocumentImportBatch.key_digest == digest)
            .values(key_digest=digest)
        )
        if locked.rowcount != 1:
            raise not_found()
        ctx.db.refresh(batch)
        if any(item["candidate_id"] == candidate_id for item in batch.items_json):
            ctx.db.commit()
            continue
        ctx.db.refresh(job)
        candidate = ctx.db.get(DocumentImportCandidate, candidate_id, populate_existing=True)
        result = {
            "candidate_id": candidate_id,
            "question_id": None,
            "status": "failed",
            "error": None,
        }
        try:
            with ctx.db.begin_nested():
                if candidate.question_id is not None:
                    result.update(question_id=candidate.question_id, status="already_imported")
                else:
                    if job.status == "cancelled" or job.expires_at <= ctx.now():
                        raise unprocessable("job", "任务已取消或过期，未导入此题")
                    if candidate.confirmed_by != ctx.actor_id or candidate.payload_json is None:
                        raise unprocessable("confirmed", "候选题尚未人工确认")
                    payload = AdminQuestionImportIn.model_validate(candidate.payload_json)
                    if payload.question.content.stem != candidate.text:
                        raise unprocessable("payload", "题面与校对文本不一致")
                    question = import_draft(
                        ctx.db,
                        actor_id=ctx.actor_id,
                        body=payload,
                        now=ctx.now(),
                        request_id=ctx.request_id,
                        document_origins=document_origins(
                            ctx.db,
                            actor_id=ctx.actor_id,
                            job_id=job_id,
                            locations=candidate.locations_json,
                        ),
                    )
                    candidate.question_id, candidate.error_json = question.id, None
                    result.update(question_id=question.id, status="imported")
        except (ApiError, ValidationError) as error:
            message = error.message if isinstance(error, ApiError) else "结构化题目格式无效"
            code = error.code if isinstance(error, ApiError) else "invalid_payload"
            result["error"] = {"code": code, "message": message}
            candidate.error_json = result["error"]
        batch.items_json = [*batch.items_json, result]
        job.revision += 1
        job.updated_at = ctx.now()
        ctx.db.commit()
    locked = ctx.db.execute(
        update(DocumentImportBatch)
        .where(DocumentImportBatch.key_digest == digest)
        .values(key_digest=digest)
    )
    if locked.rowcount != 1:
        raise not_found()
    ctx.db.refresh(batch)
    if batch.completed:
        return batch.response_json
    ctx.db.refresh(job)
    candidates = workspace.job_candidates(ctx.db, job_id)
    if job.status != "cancelled":
        job.status = (
            "completed"
            if candidates and all(item.question_id for item in candidates)
            else "partial_failure"
            if any(item.error_json for item in candidates)
            else "needs_review"
        )
    job.revision += 1
    job.updated_at = ctx.now()
    ctx.db.flush()
    response = {"job": workspace.summary(ctx.db, job), "items": batch.items_json}
    batch.completed, batch.response_json = True, response
    workspace.audit(ctx, job, "submit_complete", {"count": len(batch.items_json)})
    # 与通用幂等响应一起由 run_idempotent 提交；前面的逐题检查点已经持久化。
    return response
